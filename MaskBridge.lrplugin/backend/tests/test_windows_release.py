"""Windows regressions from the September 2026 release audit."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import unicodedata
import urllib.request

import numpy as np
from PIL import Image
import pytest

from atomic_io import atomic_write
from inference_engine import MaskBridgeEngine, _intra_op_threads
from runtime_paths import ensure_private_directory
from validation import validate_path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / 'MaskBridge.lrplugin'
windows = pytest.mark.skipif(sys.platform != 'win32', reason='Windows filesystem/SDK launch')


@windows
@pytest.mark.parametrize('path', [r'\\?\C:\Windows\no-write.png', r'\\.\NUL',
    r'C:\Program Files (x86)\no-write.png', r'C:\photos\image.png:stream', r'C:\photos\CON.png'])
def test_windows_sensitive_or_device_paths_rejected(path):
    with pytest.raises(ValueError):
        validate_path(path)


@windows
def test_nfd_input_output_and_neighbor_preserved(tmp_path):
    source = tmp_path / unicodedata.normalize('NFD', 'entrée.png')
    requested = tmp_path / unicodedata.normalize('NFD', 'résultat.png')
    neighbor = tmp_path / 'résultat.png'
    Image.new('RGB', (32, 32), 'white').save(source)
    neighbor.write_bytes(b'previous unrelated export')
    MaskBridgeEngine.process_matte_to_alpha(str(source), str(requested))
    assert requested.exists()
    assert neighbor.read_bytes() == b'previous unrelated export'
    rgba = tmp_path / unicodedata.normalize('NFD', 'détourage.png')
    MaskBridgeEngine.merge_rgb_mask_to_rgba(str(source), str(requested), str(rgba))
    with Image.open(rgba) as result:
        assert result.mode == 'RGBA' and np.asarray(result)[:, :, 3].min() == 255


@windows
def test_http_preserves_exact_nfd_paths(tmp_path):
    import server
    # Exercise the real handler without invoking any AI model.
    old = server._auth_token
    server._auth_token = 'test-only'
    http = server.BoundedHTTPServer(('127.0.0.1', 0), server.MaskBridgeHandler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        source = tmp_path / unicodedata.normalize('NFD', 'départ.png')
        output = tmp_path / unicodedata.normalize('NFD', 'arrivée.png')
        Image.new('RGB', (32, 32), 'white').save(source)
        req = urllib.request.Request(f'http://127.0.0.1:{http.server_port}/matte',
            data=json.dumps({'input': str(source), 'output': str(output)}).encode(),
            headers={'X-MaskBridge-Token': 'test-only', 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.load(response)
        assert result['output'] == str(output) and output.exists()
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)
        server._auth_token = old


@windows
def test_private_runtime_removes_shared_acl(tmp_path):
    path = tmp_path / 'runtime'
    path.mkdir()
    ensure_private_directory(path)
    token = path / 'fake-token'
    atomic_write(token, b'not-a-secret')
    # SDDL uses language-independent SIDs. No real token is accessed.
    command = "$env:PSModulePath=$PSHOME+'\\Modules'; (Get-Acl -LiteralPath '" + str(token).replace("'", "''") + "').Sddl"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
        capture_output=True, text=True, errors='replace', check=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW)
    assert '(A;' in result.stdout
    for identity in ('BU', 'AU', 'WD'):
        assert ';;;' + identity + ')' not in result.stdout


@windows
@pytest.mark.parametrize('value, expected', [('4', 4), ('999', 8), ('0', 1), ('-1', 1), ('bad', 4)])
def test_windows_thread_budget(monkeypatch, value, expected):
    monkeypatch.setattr(os, 'process_cpu_count', lambda: 8)
    monkeypatch.setenv('MASKBRIDGE_ORT_THREADS', value)
    assert _intra_op_threads() == expected


def lua_utils():
    lua = pytest.importorskip('lupa.lua51').LuaRuntime(unpack_returned_tuples=True)
    lua.globals().plugin_path = PLUGIN.as_posix()
    lua.execute('''
        _PLUGIN={path=plugin_path}; WIN_ENV=true; os.getenv=nil
        package.path=plugin_path.."/?.lua;"..package.path
        async=false; scheduled=0; errors={}
        function LOC(s) return s end
        tasks={pcall=pcall,startAsyncTask=function(fn)
            scheduled=scheduled+1; async=true; fn(); async=false end}
        dialogs={showBezel=function() end,showError=function(e) errors[#errors+1]=e end}
        function import(n)
            if n=="LrTasks" then return tasks end
            if n=="LrDialogs" then return dialogs end
            if n=="LrPathUtils" then return {child=function(a,b) return a.."/"..b end,
                getStandardFilePath=function() return "C:/redirected profile" end} end
            return {}
        end
        utils=require 'MaskBridgeUtils'
    ''')
    return lua


def test_settings_dialog_runs_async_and_respects_busy_operation():
    lua = lua_utils()
    source = (PLUGIN / 'MaskBridgeDashboard.lua').read_text(encoding='utf-8')
    lua.execute('''
        MaskBridgeUtils=utils; edited=0; props={}; prefs={}
        LrTasks=tasks; LrDialogs=dialogs
        function saveSettings() end
        function editFormatOptions()
            assert(async, 'Modal dialogs require an async SDK task'); edited=edited+1
        end
    ''')
    helpers = source[source.index('        local function settingsDialog('):source.index('        local function editFormatOptions(')]
    callback = lua.execute(helpers + '\nreturn function() settingsDialog("formatOptions", editFormatOptions) end')
    callback()
    assert lua.globals().edited == 1
    assert not lua.globals().utils.isBusy()
    lua.execute('held=utils.beginOperation("export")')
    callback()
    assert lua.globals().edited == 1
    lua.execute('utils.endOperation(held); function editFormatOptions() error("dialog failed") end')
    callback()
    assert not lua.globals().utils.isBusy()
    assert len(lua.globals().errors) == 1


APPDATA_LR = 'C:\\Users\\nico\\AppData\\Roaming\\Adobe\\Lightroom'
STATE = APPDATA_LR + '\\MaskBridge\\Runtime-v2'
NONCE = '6912ab34c5d6e7f'


def launch_files(engine, models, state=STATE, appdata=APPDATA_LR, nonce=NONCE):
    return lua_utils().globals().utils.windowsLaunchFiles(engine, models, state, appdata, nonce)


def batch_unescape(text):
    """What cmd does to a quoted batch-file argument without delayed expansion."""
    assert '%' not in text.replace('%%', ''), text
    return text.replace('%%', '%')


def test_windows_launcher_quotes_paths_and_doubles_percent():
    engine = 'C:\\photo %PATH% ! & ^ (café) 日本\\backend\\maskbridge_engine\\maskbridge_engine.exe'
    models = 'C:\\photo %PATH% ! & ^ (café) 日本\\backend\\models'
    content, command, path = launch_files(engine, models)
    assert not content.startswith('\ufeff') and content.startswith('@echo off\r\n')
    assert content.endswith('\r\n') and '\n' not in content.replace('\r\n', '')
    lines = content.split('\r\n')[:-1]
    assert lines[1] == 'setlocal DisableDelayedExpansion'
    assert lines[2] == 'if not "%~1"=="' + NONCE + '" exit /b 9'
    assert lines[3] == '"%SystemRoot%\\System32\\chcp.com" 65001 >nul'
    launch = re.fullmatch(r'"([^"]*)" --spawn-server --model-dir "([^"]*)" --state-dir "([^"]*)"'
                          r' >"([^"]*)" 2>&1', lines[4])
    assert launch, lines[4]
    assert [batch_unescape(group) for group in launch.groups()] == [
        engine, models, STATE, STATE + '\\launch.log']
    assert lines[5] == 'exit /b %errorlevel%' and len(lines) == 6
    assert path == STATE + '\\launch.cmd'
    assert command == '@"' + path + '" ' + NONCE and command.isascii()


def test_windows_launcher_uses_appdata_variable_for_non_ascii_state():
    appdata = 'C:\\Users\\Zoé 日本 100% !\\AppData\\Roaming\\Adobe\\Lightroom'
    state = appdata + '\\MaskBridge\\Runtime-v2'
    content, command, path = launch_files('C:\\e\\engine.exe', 'C:\\m', state, appdata)
    assert path == state + '\\launch.cmd'
    assert command == '@"%APPDATA%\\Adobe\\Lightroom\\MaskBridge\\Runtime-v2\\launch.cmd" ' + NONCE
    assert command.isascii()
    # Non-ASCII stays in the UTF-8 file, never in the command line.
    assert '--state-dir "' + state.replace('%', '%%') + '"' in content


@pytest.mark.parametrize('user', ['nico 100%', 'nico!'])
def test_windows_launcher_keeps_cmd_specials_out_of_literal_command(user):
    appdata = 'C:\\Users\\' + user + '\\AppData\\Roaming\\Adobe\\Lightroom'
    _, command, _ = launch_files('C:\\e\\engine.exe', 'C:\\m', appdata + '\\MaskBridge\\Runtime-v2', appdata)
    assert command.startswith('@"%APPDATA%\\') and user not in command


@pytest.mark.parametrize('state, appdata', [
    ('D:\\Profils redirigés\\Lightroom\\MaskBridge\\Runtime-v2', 'D:\\Profils redirigés\\Lightroom'),
    ('C:\\Users\\Zoé\\AppData\\Roaming\\Adobe\\Lightroom\\MaskBridge\\Runtime-v2', None),
    ('C:\\Users\\Zoé\\Other\\MaskBridge\\Runtime-v2', 'C:\\Users\\Zoé\\AppData\\Roaming\\Adobe\\Lightroom'),
])
def test_windows_launcher_refuses_non_ascii_state_outside_appdata(state, appdata):
    with pytest.raises(Exception, match='profile folder'):
        launch_files('C:\\e\\engine.exe', 'C:\\m', state, appdata)


@pytest.mark.parametrize('bad', ['C:\\a"b', 'C:\\a\nb', 'C:\\a\rb', 'C:\\a\tb', 'C:\\a\x01b', ''])
@pytest.mark.parametrize('position', [0, 1, 2])
def test_windows_launcher_refuses_quote_or_control_characters(bad, position):
    paths = ['C:\\e\\engine.exe', 'C:\\m', STATE]
    paths[position] = bad
    with pytest.raises(Exception, match='cannot start the engine'):
        launch_files(*paths)


@pytest.mark.parametrize('nonce', ['', 'x" & calc', '12 34', None])
def test_windows_launcher_refuses_unsafe_nonce(nonce):
    with pytest.raises(Exception, match='nonce'):
        launch_files('C:\\e\\engine.exe', 'C:\\m', nonce=nonce)


def test_windows_launcher_keeps_trailing_backslash_from_escaping_a_quote():
    content, _, _ = launch_files('C:\\e\\engine.exe', 'C:\\models\\')
    assert '--model-dir "C:\\models\\."' in content


def test_windows_launcher_has_no_script_interpreter_or_encoding():
    content, command, _ = launch_files('C:\\é\\engine.exe', 'C:\\é\\models')
    source = (PLUGIN / 'MaskBridgeUtils.lua').read_text(encoding='utf-8')
    for text in (content, command, source):
        lowered = text.lower()
        for word in ('powershell', 'encodedcommand', 'base64', 'wscript', 'cscript', 'mshta'):
            assert word not in lowered


WINDOWS_START_DOUBLE = """
    commands={}; created={}
    local paths={child=function(a,b) return a.."/"..b end,
        getStandardFilePath=function(kind) assert(kind=="appData"); return appdata end}
    local files={exists=function(p) return p:match("maskbridge_engine%.exe$") ~= nil end,
        delete=function() end,
        createAllDirectories=function(p) created[#created+1]=p; makedirs(p) end}
    local tasks={pcall=pcall, sleep=function() end,
        startAsyncTask=function(fn) fn() end,
        execute=function(cmd) commands[#commands+1]=cmd; return 9 end}
    function import(n)
        if n=="LrPathUtils" then return paths end
        if n=="LrFileUtils" then return files end
        if n=="LrTasks" then return tasks end
        return {}
    end
    package.loaded.MaskBridgeUtils=nil
    utils=require 'MaskBridgeUtils'
    -- POSIX test paths: keep '/' so that every file stays under tmp_path.
    utils.normalizePath=function(p) return p end
"""


def test_windows_start_writes_launcher_and_stops_on_launch_failure(tmp_path):
    lua = lua_utils()
    appdata = tmp_path / 'Adobe' / 'Lightroom'
    lua.globals().appdata = appdata.as_posix()
    lua.globals().makedirs = lambda path: os.makedirs(path, exist_ok=True)
    lua.execute(WINDOWS_START_DOUBLE)
    assert lua.globals().utils.startServer(None) is False
    state = appdata / 'MaskBridge' / 'Runtime-v2'
    assert list(lua.globals().created.values()) == [state.as_posix()]
    commands = list(lua.globals().commands.values())
    assert len(commands) == 1 and commands[0].isascii()
    nonce = commands[0].rsplit(' ', 1)[1]
    assert commands[0] == '@"' + state.as_posix() + '\\launch.cmd" ' + nonce
    # The launcher path is joined with '\', a sibling file name on POSIX.
    written = (state.parent / 'Runtime-v2\\launch.cmd').read_bytes()
    assert written.startswith(b'@echo off\r\n') and b'"' + nonce.encode() + b'"' in written
    assert b' --spawn-server --model-dir ' in written
    log = (state / 'maskbridge_debug.log').read_text(encoding='utf-8')
    assert 'Engine launcher failed with exit code 9' in log


@windows
def test_unsigned_verification_returns_failure():
    # An unsigned executable must fail verification. Verification must never
    # turn the failure into exit 0, as the old .bat script did. The pip launcher
    # of the build environment is an unsigned distlib stub.
    unsigned = Path(sys.executable).with_name('pip.exe')
    assert unsigned.is_file(), unsigned
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
        str(ROOT / 'tools/release/sign_windows.ps1'), '-VerifyOnly', '-Executable',
        str(unsigned)], capture_output=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode != 0
    assert b'NotSigned' in result.stderr


def release_module():
    spec = importlib.util.spec_from_file_location('release_tests', ROOT / 'tools/release/release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('status,timestamped,allowed,expected', [
    ('Valid', True, False, False), ('NotSigned', False, True, True),
    ('NotSigned', False, False, None), ('HashMismatch', False, True, None),
    ('NotTrusted', True, True, None), ('Valid', False, True, None)])
def test_commercial_signature_policy(status, timestamped, allowed, expected):
    release = release_module()
    signature = {'status': status, 'timestamped': timestamped}
    if expected is None:
        with pytest.raises(RuntimeError):
            release.authorize_windows_package(signature, False, allowed)
    else:
        assert release.authorize_windows_package(signature, False, allowed) is expected
