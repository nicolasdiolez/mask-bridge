"""Exercise an actual Windows ZIP and the Lua-generated Windows launcher (launch.cmd).

No user photographs, catalogues or external HTTP requests.
Usage: python tools/release/verify_windows.py archive.zip evidence-directory
"""
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from PIL import Image
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
archive, evidence = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
evidence.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'tools/release'))
import release

result = {'archive': archive.name, 'archive_sha256': release.sha(archive), 'checks': {}}
checks = result['checks']
with tempfile.TemporaryDirectory(prefix='maskbridge-final-') as temporary:
    tmp = Path(temporary)
    installation = tmp / 'installation café 日本 100% !'
    installation.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for entry in bundle.infolist():
            assert (installation / entry.filename).resolve().is_relative_to(installation.resolve())
        bundle.extractall(installation)
    plugin = installation / 'MaskBridge.lrplugin'
    release.verify_package(plugin)
    manifest = json.loads((plugin / 'release-manifest.json').read_text())
    exe = plugin / 'backend/maskbridge_engine/maskbridge_engine.exe'
    checks['archive_and_manifest'] = release.sha(exe) == manifest['engine_sha256']
    # Test candidates intentionally do not carry commercial unsigned authorization.
    # An invalid signature is still rejected, including for a candidate.
    checks['unsigned_explicit'] = manifest['signature']['status'] == 'NotSigned' and (
        manifest.get('candidate') is True or manifest.get('unsigned_windows_authorized') is True)
    checks['version'] = manifest['version'] == '1.2.0'
    result['build_commit'] = manifest['commit']
    result['python'] = manifest['python']
    env = dict(os.environ, PATH=os.environ['SystemRoot'] + r'\System32;' + os.environ['SystemRoot'])
    for name in ('PYTHONPATH', 'PYTHONHOME', 'PSModulePath'):
        env.pop(name, None)
    t = time.perf_counter()
    # The two-vCPU hosted runner takes about 280 s including BiRefNet and
    # process teardown; the desktop's former 240 s budget is too short.
    # Keep a finite upper bound, independent of the workflow's own timeout.
    completed = subprocess.run([str(exe), '--self-test', '--model-dir', str(plugin / 'backend/models')],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600,
        creationflags=subprocess.CREATE_NO_WINDOW)
    checks['compiled_rfdetr_birefnet_alpha_clean_path'] = completed.returncode == 0
    result['self_test_seconds'] = time.perf_counter() - t
    assert completed.returncode == 0, completed.stderr[-2000:]
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().plugin_path = plugin.as_posix()
    lua.execute('''
        _PLUGIN={path=plugin_path}; WIN_ENV=true; os.getenv=nil
        package.path=plugin_path.."/?.lua;"..package.path
        function import(n) return {} end
    ''')
    # Stock Lua 5.1's Windows C fopen is ANSI-only. Lightroom has its own
    # loader; load the archive's exact Lua bytes through Python for this
    # launcher-generation harness rather than testing stock Lua's fopen.
    lua.execute("package.loaded['MaskBridgeConfig']=(function() " + (plugin / 'MaskBridgeConfig.lua').read_text(encoding='utf-8') + ' end)()')
    lua.globals().utils = lua.execute((plugin / 'MaskBridgeUtils.lua').read_text(encoding='utf-8'))
    cmd_exe = os.path.join(os.environ['SystemRoot'], 'System32', 'cmd.exe')

    def launch(appdata, roaming, nonce='5f3a9c1e7b', run_nonce=None):
        """Write launch.cmd as startServer does and run the command as
        LrTasks.execute does (cmd /c), with this APPDATA in cmd's environment."""
        state = appdata / 'MaskBridge' / 'Runtime-v2'
        content, command, launcher = lua.globals().utils.windowsLaunchFiles(
            str(exe), str(plugin / 'backend/models'), str(state), str(appdata), nonce)
        assert command.isascii() and Path(launcher) == state / 'launch.cmd', (command, launcher)
        state.mkdir(parents=True, exist_ok=True)
        Path(launcher).write_bytes(content.encode('utf-8'))
        if run_nonce:
            command = command.replace(nonce, run_nonce)
        completed = subprocess.run(cmd_exe + ' /d /c ' + command, env=dict(env, APPDATA=str(roaming)),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW)
        return state, command, completed

    def launch_log(state):
        log = state / 'launch.log'
        return log.read_text(encoding='utf-8', errors='replace') if log.exists() else '(no launch.log)'

    def wait_state(state, deadline):
        statefile = state / '.server_state.json'
        while time.monotonic() < deadline:
            if statefile.exists():
                return json.loads(statefile.read_text())
            time.sleep(.1)
        raise AssertionError('Launcher did not publish state in ' + str(state))

    def health_of(state_record, deadline):
        while True:
            with urllib.request.urlopen(f"http://127.0.0.1:{state_record['port']}/health", timeout=20) as response:
                health = json.load(response)
            if health['models_loaded'] or time.monotonic() > deadline:
                return health
            time.sleep(.1)

    def shutdown(state, state_record):
        req = urllib.request.Request(f"http://127.0.0.1:{state_record['port']}/shutdown",
            headers={'X-MaskBridge-Token': state_record['token']})
        try:
            urllib.request.urlopen(req, timeout=20).close()
        except urllib.error.URLError:
            pass
        for _ in range(100):
            if not (state / '.server_state.json').exists():
                return True
            time.sleep(.1)
        return False

    # 1. ASCII state folder: launch.cmd is named literally on the command
    #    line; the engine and model paths inside it carry accents, Japanese,
    #    % and ! (installation folder) and are read as UTF-8 by cmd.
    plain = tmp / 'plain-profile' / 'Roaming'
    state_dir, command, completed = launch(plain / 'Adobe' / 'Lightroom', plain)
    result['literal_command'] = command
    assert completed.returncode == 0, (completed.returncode, launch_log(state_dir))
    state = wait_state(state_dir, time.monotonic() + 90)
    health = health_of(state, time.monotonic() + 90)
    checks['cmd_launch_literal_path_preload'] = health['models_loaded'] and health['pid'] == state['pid']
    checks['cmd_launch_literal_shutdown'] = shutdown(state_dir, state)

    # 2. A launcher reached through another APPDATA must not run (nonce).
    _, _, completed = launch(plain / 'Adobe' / 'Lightroom', plain, run_nonce='0badc0de')
    checks['cmd_launch_wrong_nonce_refused'] = (completed.returncode == 9
        and not (state_dir / '.server_state.json').exists())

    # 3. Non-ASCII state folder with % and !: the command names
    #    %APPDATA%\...\launch.cmd and cmd expands a Unicode APPDATA itself.
    roaming = tmp / 'profil café 日本 100% !' / 'Roaming'
    state_dir, command, completed = launch(roaming / 'Adobe' / 'Lightroom', roaming)
    result['appdata_command'] = command
    assert command.startswith('@"%APPDATA%\\'), command
    assert completed.returncode == 0, (completed.returncode, launch_log(state_dir))
    statefile = state_dir / '.server_state.json'
    deadline = time.monotonic() + 90
    state = wait_state(state_dir, deadline)
    def request(endpoint, data=None, auth=True, origin=False):
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['X-MaskBridge-Token'] = state['token']
        if origin:
            headers['Origin'] = 'https://example.invalid'
        req = urllib.request.Request(f"http://127.0.0.1:{state['port']}{endpoint}",
            data=None if data is None else json.dumps(data).encode(), headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=20)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)
    try:
        while time.monotonic() < deadline:
            _, health = request('/health')
            if health['models_loaded']:
                break
            time.sleep(.1)
        checks['cmd_launch_special_paths_preload'] = health['models_loaded'] and health['pid'] == state['pid']
        checks['no_shared_token'] = not (plugin / 'backend/.server_state.json').exists()
        checks['no_auth_rejected'] = request('/matte', {}, auth=False)[0] == 401
        checks['browser_origin_rejected'] = request('/health', origin=True)[0] == 401
        checks['schema_rejected'] = request('/matte', [])[0] == 400
        source = tmp / unicodedata.normalize('NFD', 'entrée café 日本 ! %.png')
        output = tmp / unicodedata.normalize('NFD', 'résultat.png')
        neighbor = tmp / 'résultat.png'
        neighbor.write_bytes(b'unrelated existing output')
        Image.new('RGB', (256, 128), 'white').save(source)
        original = release.sha(source)
        code, body = request('/matte', {'input': str(source), 'output': str(output)})
        checks['nfd_roundtrip'] = code == 200 and body['output'] == str(output) and output.exists()
        checks['nfc_neighbor_preserved'] = neighbor.read_bytes() == b'unrelated existing output'
        alpha = tmp / 'alpha.png'
        code, body = request('/merge-alpha', {'rgb_path': str(source), 'mask_path': str(output), 'output_path': str(alpha)})
        with Image.open(alpha) as photo:
            checks['native_alpha'] = code == 200 and photo.mode == 'RGBA'
        checks['original_preserved'] = request('/matte', {'input': str(source), 'output': str(source)})[0] >= 400 and release.sha(source) == original
        generated = tmp / 'masque sans clé.png'
        code, body = request('/process', {'image': str(source), 'output': str(generated),
            'model_dir': str(plugin / 'backend/models'), 'prompts': ['person']})
        checks['ai_mask_without_any_key'] = code == 200 and body.get('status') == 'success' and generated.is_file()
        start = time.perf_counter()
        for i in range(100):
            code, body = request('/matte', {'input': str(source), 'output': str(output)})
            assert code == 200
        result['hundred_matte_requests_seconds'] = time.perf_counter() - start
        checks['hundred_requests_completed'] = True
        checks['no_atomic_temporary_leaks'] = not list(tmp.glob('.maskbridge-*.tmp'))
    finally:
        request('/shutdown')
        for _ in range(100):
            if not statefile.exists():
                break
            time.sleep(.1)
        checks['shutdown_state_removed'] = not statefile.exists()
        # A short delay lets the executable release its directory before the
        # TemporaryDirectory context removes our own isolated installation.
        time.sleep(1)
assert all(checks.values()), checks
(evidence / 'native-validation.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
print(json.dumps(result, indent=2))
