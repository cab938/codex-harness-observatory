import json
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

from observatory import capture_archive
from observatory import trace_viewer


class CaptureArchiveTest(unittest.TestCase):
    def make_bundle(self, root):
        bundle = root / "bundle"
        (bundle / "payloads").mkdir(parents=True)
        files = {
            "manifest.json": b'{"schema_version":4,"format":"codex-harness-observatory","root_thread_id":null}\n',
            "trace.jsonl": b'{"schema_version":6,"seq":1,"payload":{"type":"run_started","trace_id":"x"}}\n',
            "payloads/frame.json": b'{ "number": 1e+02 }\r\n',
            "state.json": b'{"schema_version":5,"future": true}\n',
            "unknown.bin": b"\x00\xffother",
        }
        for name, data in files.items():
            (bundle / name).write_bytes(data)
        return bundle, files

    def test_export_round_trip_preserves_bundle_bytes_and_partial_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            bundle, files = self.make_bundle(root)
            (root / "outside.log").write_text("must not enter archive")
            output = root / "capture.zip"
            capture_archive.export_bundle(bundle, output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), set(files))
                self.assertEqual({name: archive.read(name) for name in files}, files)
            with capture_archive.open_capture(output) as extracted:
                self.assertTrue(extracted.is_dir())
                self.assertEqual(
                    {name: (extracted / name).read_bytes() for name in files}, files
                )
                header = trace_viewer.manifest_metadata(
                    extracted / "trace.jsonl", recorded=True
                )
                self.assertEqual(
                    (
                        header["capture_status"],
                        header["root_thread_id"]
                        if "root_thread_id" in header
                        else None,
                    ),
                    ("partial", None),
                )
                self.assertFalse(header["run_ended"])
            self.assertFalse(extracted.exists())
            with capture_archive.open_capture(bundle) as opened:
                self.assertEqual(opened, bundle)
            with capture_archive.open_capture(bundle / "trace.jsonl") as opened:
                self.assertEqual(opened, bundle / "trace.jsonl")

    def test_rejects_unsafe_ambiguous_duplicate_and_symlink_entries(self):
        bad_names = (
            "../outside",
            "/absolute",
            "C:/drive",
            "dir\\child",
            "dir/CON.txt",
            "Dir/file",
            "dir/FILE",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for name in bad_names[:5]:
                archive_path = root / "bad.zip"
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr("manifest.json", "{}")
                    archive.writestr("trace.jsonl", "")
                    entry = zipfile.ZipInfo(name)
                    # Keep the malformed ZIP name even when Windows normalizes os.sep.
                    entry.filename = name
                    archive.writestr(entry, "bad")
                with (
                    self.subTest(name=name),
                    self.assertRaises(trace_viewer.TraceInputError),
                ):
                    with capture_archive.open_capture(archive_path):
                        pass
            for entries in (
                ["Dir/file", "dir/FILE"],
                ["same", "same"],
                ["other/manifest.json", "other/trace.jsonl"],
            ):
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr("manifest.json", "{}")
                    archive.writestr("trace.jsonl", "")
                    for name in entries:
                        archive.writestr(name, "x")
                with (
                    self.subTest(entries=entries),
                    self.assertRaises(trace_viewer.TraceInputError),
                ):
                    with capture_archive.open_capture(archive_path):
                        pass
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("manifest.json", "{}")
                archive.writestr("trace.jsonl", "")
                entry = zipfile.ZipInfo("link")
                entry.create_system = 3
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(entry, "../outside")
            with self.assertRaises(trace_viewer.TraceInputError):
                with capture_archive.open_capture(archive_path):
                    pass

    @unittest.skipUnless(os.name == "nt", "Windows directory junctions")
    def test_export_rejects_windows_junction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            bundle, _ = self.make_bundle(root)
            outside = root / "outside"
            outside.mkdir()
            (outside / "unselected.txt").write_bytes(b"outside the selected bundle")
            junction = bundle / "linked"
            subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
                check=True,
                capture_output=True,
            )
            try:
                with self.assertRaisesRegex(
                    trace_viewer.TraceInputError, "non-regular"
                ):
                    capture_archive.export_bundle(bundle, root / "capture.zip")
            finally:
                os.rmdir(junction)

    def test_export_rejects_missing_nested_externalized_payload_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            bundle, _ = self.make_bundle(root)
            (bundle / "payloads/large.json").write_text(
                json.dumps(
                    {
                        "type": "inference_started",
                        "request_payload": {"path": "payloads/missing.json"},
                    }
                )
            )
            (bundle / "trace.jsonl").write_text(
                json.dumps(
                    {
                        "schema_version": 6,
                        "seq": 1,
                        "payload": {
                            "type": "oversized_event",
                            "original_type": "inference_started",
                            "event_payload": {"path": "payloads/large.json"},
                        },
                    }
                )
                + "\n"
            )
            output = root / "capture.zip"
            with self.assertRaisesRegex(
                trace_viewer.TraceInputError, "artifact is unavailable"
            ):
                capture_archive.export_bundle(bundle, output)
            self.assertFalse(output.exists())

    def test_export_checks_optional_reduced_state_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            bundle, _ = self.make_bundle(root)
            (bundle / "state.json").write_text(
                json.dumps(
                    {
                        "raw_payloads": {
                            "id": {
                                "raw_payload_id": "id",
                                "path": "payloads/missing.json",
                                "kind": {"type": "tool_result"},
                            }
                        }
                    }
                )
            )
            with self.assertRaisesRegex(
                trace_viewer.TraceInputError, "artifact is unavailable"
            ):
                capture_archive.export_bundle(bundle, root / "capture.zip")

    def test_growing_bundle_is_rejected_without_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            bundle, _ = self.make_bundle(root)
            output = root / "capture.zip"
            copy = capture_archive.shutil.copyfileobj
            changed = False

            def grow(source, destination, length):
                nonlocal changed
                copy(source, destination, length)
                if not changed:
                    with (bundle / "trace.jsonl").open("ab") as trace:
                        trace.write(b" ")
                    changed = True

            with mock.patch.object(
                capture_archive.shutil, "copyfileobj", side_effect=grow
            ):
                with self.assertRaisesRegex(trace_viewer.TraceInputError, "changed"):
                    capture_archive.export_bundle(bundle, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".observatory-*.zip")), [])


if __name__ == "__main__":
    unittest.main()
