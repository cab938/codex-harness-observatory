import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from src.scripts import vm_auth


class VmAuthTests(unittest.TestCase):
    def test_copy_uses_stdin_and_installs_owned_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source = tmp_path / 'source.json'
            payload = b'{"tokens": {"access_token": "synthetic-only"}}'
            source.write_bytes(payload)
            instance = 'avm-nellodee-012345abcdef'
            destination = '/home/codex/.obs-test'
            actual_run = subprocess.run
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                if argv[0] == 'agent-vm':
                    return subprocess.CompletedProcess(argv, 0, json.dumps({
                        'id': instance, 'host': 'nellodee', 'kind': 'instance', 'status': 'ready',
                        'ssh_config': '/tmp/instance-ssh-config',
                    }).encode(), b'')
                self.assertEqual(argv[:5], ['ssh', '-T', '-F', '/tmp/instance-ssh-config', instance])
                self.assertNotIn(payload, ' '.join(argv).encode())
                self.assertEqual(kwargs['input'], payload)
                script = vm_auth.REMOTE_INSTALL.replace("pathlib.Path('/home/codex')", f'pathlib.Path({str(tmp_path)!r})')
                return actual_run([sys.executable, '-c', script, str(tmp_path / '.obs-test')], **kwargs)

            with mock.patch.object(vm_auth.subprocess, 'run', side_effect=run):
                report = vm_auth.copy_auth(instance, source, destination)
            guest_home = tmp_path / '.obs-test'
            self.assertEqual(report, {'uid': os.getuid(), 'home_mode': '0700', 'auth_mode': '0600'})
            self.assertEqual((guest_home / 'auth.json').read_bytes(), payload)
            self.assertEqual(guest_home.stat().st_mode & 0o777, 0o700)
            self.assertEqual((guest_home / 'auth.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(calls), 2)

    def test_rejects_unisolated_destinations_and_non_disposable_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'auth.json'
            source.write_text('{"tokens": {"access_token": "synthetic-only"}}')
            with mock.patch.object(vm_auth.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    vm_auth.copy_auth('avm-nellodee-012345abcdef', source, '/home/codex/.codex')
                with self.assertRaises(ValueError):
                    vm_auth.copy_auth('avm-thelio-012345abcdef', source, '/home/codex/.obs-test')
                run.return_value = subprocess.CompletedProcess([], 0, json.dumps({
                    'id': 'avm-nellodee-012345abcdef', 'host': 'nellodee', 'kind': 'template-build',
                    'status': 'ready', 'ssh_config': '/tmp/config',
                }).encode(), b'')
                with self.assertRaises(ValueError):
                    vm_auth.copy_auth('avm-nellodee-012345abcdef', source, '/home/codex/.obs-test')
                self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
