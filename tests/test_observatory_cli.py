import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_harness_observatory import cli


def _package_archive(path: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "bin").mkdir()
        (root / "codex-path").mkdir()
        (root / "codex-resources").mkdir()
        (root / "codex-package.json").write_text(json.dumps(cli.EXPECTED_PACKAGE), encoding="utf-8")
        for relative, body in {
            "bin/codex": "#!/bin/sh\nprintf 'codex-cli 0.150.0-alpha.12.2\\n'\n",
            "bin/codex-code-mode-host": "#!/bin/sh\nexit 0\n",
            "codex-resources/bwrap": "#!/bin/sh\nexit 0\n",
            "codex-path/rg": "#!/bin/sh\nexit 0\n",
        }.items():
            target = root / relative
            target.write_text(body, encoding="utf-8")
            target.chmod(0o755)
        with tarfile.open(path, "w:gz") as archive:
            for item in sorted(root.rglob("*")):
                archive.add(item, arcname=item.relative_to(root), recursive=False)


class ObservatoryCliTest(unittest.TestCase):
    def test_module_entrypoint_supports_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "codex_harness_observatory", "--help"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Launch the isolated Codex Harness Observatory", result.stdout)

    def test_dispatches_through_same_environment_and_preserves_current_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            configure = cwd / "bin" / "codex-configure"
            configure.parent.mkdir()
            configure.touch()
            configure.chmod(0o755)
            with (
                mock.patch.object(cli, "_same_venv_codex_configure", return_value=configure),
                mock.patch.object(cli, "_ensure_launch_root"),
                mock.patch.object(cli.os, "execvpe", side_effect=AssertionError("stop")) as execvpe,
                mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True),
                mock.patch("pathlib.Path.cwd", return_value=cwd),
            ):
                with self.assertRaises(AssertionError):
                    cli.main(["--tui"])
            command = execvpe.call_args.args[1]
            self.assertEqual(
                command,
                [
                    str(configure),
                    "launch",
                    "--",
                    str(cli._python_executable()),
                    "-m",
                    "codex_harness_observatory",
                    "_run",
                    "--tui",
                ],
            )
            self.assertTrue(
                execvpe.call_args.args[2]["PATH"].startswith(
                    str(cli._python_executable().parent)
                )
            )

    def test_desktop_is_rejected_by_installed_launcher(self):
        output = io.StringIO()
        with mock.patch("sys.stderr", output):
            self.assertEqual(cli.main(["--desktop"]), 2)
        self.assertIn("source checkout only", output.getvalue())

    def test_automatic_ports_and_reported_addresses(self):
        process = mock.Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as temporary:
            app_log = Path(temporary) / "app-server.log"
            app_log.write_text(
                "codex app-server (WebSockets)\n"
                "  listening on: ws://127.0.0.1:43123\n"
                "  readyz: http://127.0.0.1:43123/readyz\n",
                encoding="utf-8",
            )
            viewer_log = Path(temporary) / "trace-viewer.log"
            viewer_log.write_text(
                "Codex Harness Observatory: http://127.0.0.1:51234\n",
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(cli._port("OBSERVATORY_APP_SERVER_PORT", "0"), 0)
                self.assertEqual(cli._port("OBSERVATORY_VIEWER_PORT", "0"), 0)
            app_url = cli._wait_for_bound_url(
                "Codex app server", "ws", process, app_log, 0.1
            )
            viewer_url = cli._wait_for_bound_url(
                "log web server", "http", process, viewer_log, 0.1
            )

        self.assertEqual(app_url, "ws://127.0.0.1:43123")
        self.assertEqual(
            cli._app_server_ready_url(app_url), "http://127.0.0.1:43123/readyz"
        )
        self.assertEqual(viewer_url, "http://127.0.0.1:51234")

    def test_explicit_port_override_is_preserved(self):
        with mock.patch.dict(
            os.environ, {"OBSERVATORY_VIEWER_PORT": "8765"}, clear=True
        ):
            self.assertEqual(cli._port("OBSERVATORY_VIEWER_PORT", "0"), 8765)

    def test_installs_secure_package_once_and_reuses_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / ".codex-configure" / "codex-home"
            codex_home.mkdir(parents=True)
            archive = root / "release.tar.gz"
            _package_archive(archive)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()

            def fake_download(url: str, destination: Path) -> None:
                if url.endswith(".sha256"):
                    destination.write_text(f"{digest}  {cli.CORE_ARCHIVE_NAME}\n", encoding="utf-8")
                else:
                    shutil.copyfile(archive, destination)

            with mock.patch.object(cli, "_download", side_effect=fake_download) as download:
                first = cli.install_core(codex_home)
                second = cli.install_core(codex_home)

            self.assertEqual(first, second)
            self.assertTrue(first.is_file())
            self.assertEqual(download.call_count, 2)
            self.assertEqual(stat.S_IMODE(first.stat().st_mode) & 0o111, 0o111)

    def test_archive_rejects_symlink_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "unsafe.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                member = tarfile.TarInfo("bin/codex")
                member.type = tarfile.SYMTYPE
                member.linkname = "/tmp/codex"
                archive.addfile(member)
            with tarfile.open(archive_path, "r:gz") as archive:
                with self.assertRaises(cli.ObservatoryError):
                    cli._validate_archive(archive)


if __name__ == "__main__":
    unittest.main()
