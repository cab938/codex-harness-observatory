import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


BRIDGE = pathlib.Path(__file__).parents[2] / "tools" / "desktop_core_bridge.sh"


class DesktopCoreBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.bridge_directory = pathlib.Path(self.temporary_directory.name)
        self.bridge = self.bridge_directory / "codex"
        shutil.copy2(BRIDGE, self.bridge)
        self.bridge.chmod(0o700)

        self.real_codex = self.bridge_directory / "real-codex"
        self.real_codex.write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n',
            encoding="utf-8",
        )
        self.real_codex.chmod(0o700)

        self.codex_app_root = self.bridge_directory / "codex-app-tools"
        (self.codex_app_root / "scripts").mkdir(parents=True)
        (self.codex_app_root / "server.mjs").touch()
        launcher = self.codex_app_root / "scripts" / "launch_codex_app_tools_mcp"
        launcher.touch()
        launcher.chmod(0o700)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_bridge(self, *arguments):
        result = subprocess.run(
            [self.bridge, *arguments],
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        return result.stdout.splitlines()

    def test_non_app_server_commands_pass_through_unchanged(self):
        self.assertEqual(self.run_bridge("--version"), ["--version"])

    def test_app_server_receives_bundled_codex_app_transport_before_original_arguments(self):
        arguments = self.run_bridge("app-server", "--listen", "unix:///tmp/demo.sock")

        self.assertIn(
            f'mcp_servers.codex_app.command="{self.codex_app_root}/scripts/launch_codex_app_tools_mcp"',
            arguments,
        )
        self.assertIn(
            f'mcp_servers.codex_app.cwd="{self.codex_app_root}"',
            arguments,
        )
        self.assertFalse(any("enabled_tools" in argument for argument in arguments))
        self.assertLess(arguments.index("app-server"), arguments.index("--listen"))
        self.assertEqual(arguments[-2:], ["--listen", "unix:///tmp/demo.sock"])


if __name__ == "__main__":
    unittest.main()
