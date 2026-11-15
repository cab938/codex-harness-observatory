"""The launcher routes each invocation to its own native capture."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import launch
import observatory._process_cleanup
import observatory.capture_archive
import observatory.trace_viewer


def test_cli_profiles_and_runs_are_routed_independently(tmp_path, monkeypatch):
    home = tmp_path / 'profile'
    home.mkdir()
    (home / 'config.toml').write_text('existing = true\n')
    runs = tmp_path / 'runs'
    seen = []
    app = SimpleNamespace(pid=123, poll=lambda: 0)
    monkeypatch.setattr(launch, '_validate_package_dir', lambda path: Path('/instrumented/codex'))
    monkeypatch.setattr(launch, '_verify_binary', lambda binary, home: None)
    monkeypatch.setattr(launch, '_start_viewer', lambda root, cwd, env, log: (None, 'http://127.0.0.1:1'))
    monkeypatch.setattr(launch, '_wait_for_bound_url', lambda *args: 'ws://127.0.0.1:2')
    monkeypatch.setattr(launch, '_wait_for_service', lambda *args: None)
    monkeypatch.setattr(launch, '_wait_for_capture', lambda *args: None)
    monkeypatch.setattr(launch.subprocess, 'Popen', lambda *args, **kwargs: (seen.append(kwargs['env'].copy()) or app))
    monkeypatch.setattr(launch.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(observatory._process_cleanup, 'stop_owned_descendants', lambda process: nullcontext())
    for _ in range(2):
        assert launch._run('cli', home, runs) == 0
    dirs = [Path(env['CODEX_ROLLOUT_TRACE_RUN_DIR']) for env in seen]
    assert len(set(dirs)) == 2
    assert all(path.parent == runs and path.is_dir() for path in dirs)
    assert all(env['CODEX_HOME'] == str(home) for env in seen)
    assert (home / 'config.toml').read_text() == 'existing = true\n'


def test_replay_routes_exact_capture_without_starting_client(tmp_path, monkeypatch):
    capture = tmp_path / 'capture'
    observed = []
    monkeypatch.setattr(observatory.capture_archive, 'open_capture', lambda path: nullcontext(path))
    monkeypatch.setattr(observatory.trace_viewer, 'main', lambda args: observed.append(args) or 0)
    assert launch.main(['replay', str(capture)]) == 0
    assert observed[0][:3] == [str(capture), '--serve', '--recorded']


def test_desktop_uses_same_selected_profile_and_native_run(tmp_path, monkeypatch):
    import observatory.desktop

    home = tmp_path / 'profile'
    runs = tmp_path / 'runs'
    observed = {}
    process = SimpleNamespace(wait=lambda: 0)
    monkeypatch.setattr(launch, '_validate_package_dir', lambda path: Path('/instrumented/codex'))
    monkeypatch.setattr(launch, '_verify_binary', lambda binary, home: None)
    monkeypatch.setattr(launch, '_start_viewer', lambda root, cwd, env, log: (None, 'http://127.0.0.1:1'))
    monkeypatch.setattr(launch, '_wait_for_capture', lambda *args: None)
    monkeypatch.setattr(observatory.desktop, 'resolve_desktop_candidate', lambda *args: object())
    def start(candidate, **kwargs):
        observed.update(kwargs)
        return process, Path('/socket')
    monkeypatch.setattr(observatory.desktop, 'start_desktop', start)
    monkeypatch.setattr(observatory.desktop, 'stop_desktop', lambda process: None)
    assert launch._run('desktop', home, runs) == 0
    assert observed['environment']['CODEX_HOME'] == str(home)
    assert observed['environment']['CODEX_ROLLOUT_TRACE_RUN_DIR'] == str(observed['run_dir'])
    assert observed['run_dir'].parent == runs


def test_viewer_starts_outside_distribution_without_pythonpath(tmp_path, monkeypatch):
    from urllib.request import urlopen
    import os

    monkeypatch.delenv('PYTHONPATH', raising=False)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    process, url = launch._start_viewer(run_dir, workspace, os.environ.copy(), run_dir / 'viewer.log')
    try:
        with urlopen(url + '/', timeout=5) as response:
            assert b'<html' in response.read().lower()
    finally:
        launch._terminate(process)
    assert process.poll() is not None
