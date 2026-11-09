"""--spawn-server: the engine starts its own detached server (Windows launcher)."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import cli


class FakePopen:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append((command, options))
        return type('Process', (), {'pid': 4242})()


@pytest.fixture
def folders(tmp_path):
    models = tmp_path / 'modèles 日本 100% !'
    models.mkdir()
    return str(models), str(tmp_path / 'état & profil' / 'Runtime-v2')


def test_spawn_server_starts_detached_server_and_returns(folders, monkeypatch):
    models, state = folders
    monkeypatch.setenv('MASKBRIDGE_STATE_DIR', 'stale value')
    popen = FakePopen()
    assert cli.spawn_server(models, state, popen=popen) == 0
    [(command, options)] = popen.calls
    assert command == [sys.executable, os.path.abspath(cli.__file__),
                       '--server', '--preload', '--model-dir', os.path.abspath(models)]
    assert options['env']['MASKBRIDGE_STATE_DIR'] == os.path.abspath(state)
    assert options['env']['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
    assert options['env']['PATH'] == os.environ['PATH']
    assert options['shell'] is False and options['close_fds'] is True
    for stream in ('stdin', 'stdout', 'stderr'):
        assert options[stream] is subprocess.DEVNULL
    assert os.path.isdir(state)


def test_spawn_server_runs_the_frozen_executable_itself(folders, monkeypatch):
    models, state = folders
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\Mask Bridge\maskbridge_engine.exe')
    popen = FakePopen()
    assert cli.spawn_server(models, state, popen=popen) == 0
    command = popen.calls[0][0]
    assert command[:4] == [r'C:\Mask Bridge\maskbridge_engine.exe', '--server', '--preload', '--model-dir']


def test_spawn_server_hides_console_and_detaches_on_windows(folders, monkeypatch):
    models, state = folders
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200, raising=False)
    popen = FakePopen()
    assert cli.spawn_server(models, state, popen=popen) == 0
    options = popen.calls[0][1]
    assert options['creationflags'] == 0x08000000 | 0x00000200
    assert 'start_new_session' not in options


def test_spawn_server_refuses_missing_model_dir(tmp_path, capsys):
    popen = FakePopen()
    assert cli.spawn_server(str(tmp_path / 'absent'), str(tmp_path / 'state'), popen=popen) == 2
    assert popen.calls == [] and 'model directory not found' in capsys.readouterr().err
    assert not (tmp_path / 'state').exists()


def test_spawn_server_requires_state_dir(folders):
    popen = FakePopen()
    assert cli.spawn_server(folders[0], None, popen=popen) == 2
    assert popen.calls == []


def test_spawn_server_reports_unusable_state_dir(folders, tmp_path, capsys):
    blocker = tmp_path / 'file'
    blocker.write_text('not a directory')
    popen = FakePopen()
    assert cli.spawn_server(folders[0], str(blocker / 'Runtime-v2'), popen=popen) == 3
    assert popen.calls == [] and 'cannot use state directory' in capsys.readouterr().err


def test_spawn_server_reports_start_failure(folders, capsys):
    def failing(command, **options):
        raise OSError('access denied')
    assert cli.spawn_server(*folders, popen=failing) == 4
    assert 'access denied' in capsys.readouterr().err


def test_main_dispatches_spawn_server(folders, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, 'spawn_server', lambda *args: calls.append(args) or 3)
    monkeypatch.setattr(sys, 'argv', ['maskbridge_engine', '--spawn-server',
                                      '--model-dir', folders[0], '--state-dir', folders[1]])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 3 and calls == [folders]
