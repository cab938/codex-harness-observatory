#!/usr/bin/env python3
"""Copy a local Codex auth cache into an isolated disposable Nellodee VM."""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys


# Sent as a command, never together with the credential data on the command line.
REMOTE_INSTALL = r'''
import json, os, pathlib, stat, sys, tempfile
try:
    home = pathlib.Path(sys.argv[1])
    parent = pathlib.Path('/home/codex')
    if parent.resolve(strict=True) != parent:
        raise ValueError('Unexpected guest home')
    current = parent
    for part in home.relative_to(parent).parts:
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('Test home path must contain only owned directories')
    os.chmod(home, 0o700)
    fd, temporary = tempfile.mkstemp(prefix='.auth-', dir=home)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(sys.stdin.buffer.read())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, home / 'auth.json')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    auth = (home / 'auth.json').stat()
    directory = home.stat()
    if auth.st_uid != os.getuid() or stat.S_IMODE(auth.st_mode) != 0o600 or stat.S_IMODE(directory.st_mode) != 0o700:
        raise ValueError('Permission verification failed')
    print(json.dumps({'uid': os.getuid(), 'home_mode': '0700', 'auth_mode': '0600'}))
except Exception:
    print('Guest installation or verification failed.', file=sys.stderr)
    sys.exit(1)
'''


def copy_auth(instance, source, destination):
    if not re.fullmatch(r'avm-nellodee-[0-9a-f]{12}', instance):
        raise ValueError('Expected a managed Nellodee disposable instance ID.')
    path = PurePosixPath(destination)
    parts = path.parts
    if (str(path) != destination or len(parts) < 4 or parts[:3] != ('/', 'home', 'codex')
            or parts[3] in {'.codex', '.ssh', '.config', '.local'}
            or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', part) or part in {'.', '..'} for part in parts[3:])):
        raise ValueError('Test CODEX_HOME must be a dedicated directory under /home/codex, outside normal configuration directories.')
    try:
        data = source.read_bytes()
        auth = json.loads(data)
    except FileNotFoundError:
        raise ValueError('Auth file not found. If login uses a keyring, create a file-backed auth.json first or supply --source.') from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('Cannot read a valid JSON auth file.') from None
    if not isinstance(auth, dict) or not (isinstance(auth.get('tokens'), dict) and auth['tokens']
                                         or isinstance(auth.get('OPENAI_API_KEY'), str) and auth['OPENAI_API_KEY']):
        raise ValueError('Auth file has no recognizable tokens or API key; file-backed login may be needed.')
    try:
        info_result = subprocess.run(['agent-vm', 'info', instance], capture_output=True, check=True)
        info = json.loads(info_result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        raise ValueError('Cannot resolve the instance with agent-vm info.') from None
    if (not isinstance(info, dict) or info.get('id') != instance or info.get('host') != 'nellodee'
            or info.get('kind') != 'instance' or info.get('status') != 'ready'
            or not isinstance(info.get('ssh_config'), str) or not os.path.isabs(info['ssh_config'])):
        raise ValueError('Instance is not a ready, managed disposable Nellodee VM with SSH access.')
    command = shlex.join(['python3', '-c', REMOTE_INSTALL, destination])
    try:
        result = subprocess.run(['ssh', '-T', '-F', info['ssh_config'], instance, command],
                                input=data, capture_output=True, check=True)
        report = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        raise ValueError('SSH transfer or guest verification failed; inspect VM access and test home.') from None
    if (not isinstance(report, dict) or not isinstance(report.get('uid'), int)
            or report.get('home_mode') != '0700' or report.get('auth_mode') != '0600'):
        raise ValueError('Guest did not confirm expected ownership and permissions.')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('instance', help='Ready agent-vm instance ID on Nellodee')
    parser.add_argument('destination', help='Dedicated guest test CODEX_HOME under /home/codex')
    parser.add_argument('--source', type=Path, default=Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'auth.json',
                        help='Local auth.json (default: $CODEX_HOME/auth.json, else ~/.codex/auth.json)')
    args = parser.parse_args()
    try:
        report = copy_auth(args.instance, args.source.expanduser(), args.destination)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Installed for {args.instance}; guest uid {report['uid']}, directory 0700, auth.json 0600.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
