"""Validate an extracted macOS archive in isolation; no external HTTP request.

Run with the release Python and --archive ZIP --output receipt.json.
This exercises the compiled engine, not Adobe Lightroom.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import socket
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile

from PIL import Image, ImageCms

import release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-notarization', action='store_true',
                        help='Require Apple notarization on the extracted engine (online check)')
    args = parser.parse_args()
    archive = args.archive.resolve()
    checks = {}
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None, 'ZIP CRC mismatch'
        for entry in bundle.infolist():
            path = Path(entry.filename)
            assert not path.is_absolute() and '..' not in path.parts, 'Unsafe archive path'
    checks['zip_crc'] = True
    with tempfile.TemporaryDirectory(prefix='maskbridge-macos-qa-') as temporary:
        root = Path(temporary)
        # Keep accents, apostrophe and non-Latin characters in the install path.
        install = root / "Installation été d’essai 日本"
        subprocess.run(['ditto', '-x', '-k', str(archive), str(install)], check=True, timeout=120)
        plugin = install / 'MaskBridge.lrplugin'
        engine = plugin / 'backend/maskbridge_engine'
        exe = engine / 'maskbridge_engine'
        models = plugin / 'backend/models'
        manifest = json.loads((plugin / 'release-manifest.json').read_text())
        release.verify_package(plugin)
        assert release.sha(exe) == manifest['engine_sha256']
        info = release.inspect_engine(engine)
        assert info['sources'] == manifest['sources']
        assert info['version'] == manifest['version'] == '1.2.0'
        checks['package_models_exclusions_provenance'] = True
        # No Python on PATH: the customer engine must be standalone.
        env = dict(os.environ, PATH='/usr/bin:/bin:/usr/sbin:/sbin')
        def run(*command):
            return subprocess.run(command, check=True, capture_output=True, text=True,
                                  env=env, timeout=180)
        native_files = []
        for path in engine.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            with path.open('rb') as stream:
                magic = stream.read(4)
            if magic in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
                run('codesign', '--verify', '--strict', str(path))
                native_files.append(str(path.relative_to(engine)))
        identity = run('codesign', '-dvv', str(exe))
        assert 'Authority=Developer ID Application' in identity.stderr
        assert native_files
        checks['developer_id_and_all_native_signatures'] = len(native_files)
        if args.require_notarization:
            run('codesign', '-vvvv', '-R=notarized', '--check-notarization', str(exe))
            checks['apple_notarization_on_extracted_engine'] = True
        started = time.perf_counter()
        run(str(exe), '--self-test', '--model-dir', str(models))
        checks['compiled_rfdetr_birefnet_alpha_without_python'] = True
        checks['self_test_seconds'] = round(time.perf_counter() - started, 3)
        logpath = root / 'server.log'
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        with logpath.open('w') as log:
            process = subprocess.Popen([str(exe), '--server', '--port', str(port), '--preload',
                                        '--model-dir', str(models)], env=env, stdout=log, stderr=log)
            try:
                statefile = plugin / 'backend/.server_state.json'
                deadline = time.monotonic() + 90
                state = None
                while time.monotonic() < deadline:
                    assert process.poll() is None, logpath.read_text()[-2000:]
                    if statefile.exists():
                        state = json.loads(statefile.read_text())
                        break
                    time.sleep(.1)
                assert state, 'Server did not publish state within 90 seconds'
                def request(endpoint, data=None, authenticated=True, origin=None):
                    headers = {'Content-Type': 'application/json'}
                    if authenticated:
                        headers['X-MaskBridge-Token'] = state['token']
                    if origin:
                        headers['Origin'] = origin
                    req = urllib.request.Request(f"http://127.0.0.1:{state['port']}{endpoint}",
                        data=None if data is None else json.dumps(data).encode(), headers=headers)
                    try:
                        response = urllib.request.urlopen(req, timeout=30)
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        return response.status, json.load(response)
                health = {}
                while time.monotonic() < deadline:
                    code, health = request('/health')
                    if health.get('models_loaded'):
                        break
                    time.sleep(.1)
                assert code == 200 and health.get('models_loaded') and health['pid'] == process.pid
                checks['server_models_and_pid_unicode_install'] = True
                assert request('/matte', [])[0] == 400
                assert request('/matte', {}, authenticated=False)[0] in (401, 403)
                assert request('/matte', {}, origin='https://example.invalid')[0] == 401
                checks['invalid_body_authentication_and_origin_rejected'] = True
                photo = root / unicodedata.normalize('NFD', 'entrée 日本.png')
                mask = root / unicodedata.normalize('NFD', 'résultat 日本.png')
                alpha = root / 'détourage.png'
                icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
                Image.new('RGB', (96, 64), 'white').save(photo, icc_profile=icc)
                original = photo.read_bytes()
                assert request('/matte', {'input': str(photo), 'output': str(mask)})[0] == 200
                assert mask.is_file()
                assert request('/merge-alpha', {'rgb_path': str(photo), 'mask_path': str(mask),
                                               'output_path': str(alpha)})[0] == 200
                with Image.open(alpha) as result:
                    assert result.mode == 'RGBA' and result.size == (96, 64)
                    assert result.info.get('icc_profile') == icc
                    assert result.getchannel('A').getextrema() == (255, 255)
                checks['unicode_matte_alpha_and_icc'] = True
                alias = root / 'alias.png'
                alias.symlink_to(photo)
                assert request('/matte', {'input': str(photo), 'output': str(alias)})[0] >= 400
                assert request('/matte', {'input': str(photo), 'output': str(photo)})[0] >= 400
                assert photo.read_bytes() == original
                checks['source_and_symlink_alias_preserved'] = True
                generated = root / 'masque sans clé.png'
                code, body = request('/process', {'image': str(photo), 'output': str(generated),
                    'model_dir': str(models), 'prompts': ['person']})
                assert code == 200 and body.get('status') == 'success' and generated.is_file(), body
                assert photo.read_bytes() == original
                checks['ai_mask_without_any_key'] = True
                assert request('/shutdown')[0] == 200
                assert process.wait(timeout=15) == 0
                assert not any((plugin / 'backend' / name).exists() for name in
                               ('.server_state.json', '.server_token', '.server_port'))
                checks['shutdown_cleans_state'] = True
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    receipt = {'archive': archive.name, 'sha256': release.sha(archive),
               'bytes': archive.stat().st_size, 'checks': checks,
               'verifier_sha256': release.sha(Path(__file__)),
               'scope': 'macOS arm64 compiled archive; no Lightroom SDK',
               'native_signed_files': native_files}
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
