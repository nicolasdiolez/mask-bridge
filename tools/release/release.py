"""One release pipeline for macOS and Windows (Python 3.13).

Build stages a new engine and smoke-tests it before replacing the local engine.
Package never rebuilds or publishes: it verifies provenance, copies the readable
Lua sources into a private staging directory and checks their Lua 5.1 syntax,
then creates a platform-specific archive.
"""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / 'MaskBridge.lrplugin'
BACKEND = PLUGIN / 'backend'
ENGINE = BACKEND / 'maskbridge_engine'
sys.path.insert(0, str(BACKEND))
from cli import MODEL_SHA256, verify_model, VERSION


def check_lua51_syntax(path):
    """Parse a plugin file as Lua 5.1 (Lightroom's dialect) without running it."""
    from lupa.lua51 import LuaRuntime
    check = LuaRuntime().eval('function(code, name) local chunk, err = loadstring(code, name); return err end')
    error = check(Path(path).read_text(encoding='utf-8'), '@' + Path(path).name)
    if error is not None:
        raise RuntimeError(f'{Path(path).name} is not valid Lua 5.1: {error}')


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, cwd=ROOT, **kwargs)


def sha(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_hashes():
    paths = list(BACKEND.glob('*.py')) + [ROOT / 'maskbridge_engine.spec', BACKEND / 'requirements.txt',
        ROOT / 'tools/release/release.py', ROOT / 'tools/release/requirements-lock.txt',
        ROOT / 'tools/release/sign_windows.ps1']
    return {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in sorted(paths) if p.name != 'build_info.py'}


def executable(directory=ENGINE):
    return directory / ('maskbridge_engine.exe' if os.name == 'nt' else 'maskbridge_engine')


def preflight():
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError('Use Python 3.13 in the release environment on both platforms')
    if os.name == 'nt' and (sys.version_info[:3] < (3, 13, 15) or platform.machine().upper() != 'AMD64'):
        raise RuntimeError('Windows releases require Python >=3.13.15 (3.13 series), x64')
    import re
    for name, version in re.findall(r'^([\w.-]+)==([^\s\\]+)', (ROOT / 'tools/release/requirements-lock.txt').read_text(), re.M):
        if name == 'macholib' and os.name == 'nt':
            continue
        if metadata.version(name) != version:
            raise RuntimeError(f'Release dependency differs from lock: {name}=={version}')
    for name in MODEL_SHA256:
        ok, message = verify_model(str(BACKEND / 'models' / name), name)
        if not ok:
            raise RuntimeError(message)


def inspect_engine(directory=ENGINE):
    result = run(executable(directory), '--build-info', capture_output=True, text=True)
    info = json.loads(result.stdout)
    if info.get('sources') != source_hashes():
        raise RuntimeError('Engine differs from current backend sources. Rebuild before packaging.')
    if info.get('models') != MODEL_SHA256:
        raise RuntimeError('Engine was built for other model weights')
    if info.get('architecture') != platform.machine() or info.get('python') != platform.python_version():
        raise RuntimeError('Engine architecture/Python differ from the release environment')
    if info.get('version') != VERSION:
        raise RuntimeError('Engine version differs from the plugin')
    for name, version in info.get('dependencies', {}).items():
        if metadata.version(name) != version:
            raise RuntimeError(f'Engine dependency differs from the release environment: {name}')
    return info


def collect_notices(target):
    target.mkdir(parents=True, exist_ok=True)
    pending = ['onnxruntime', 'numpy', 'opencv-python-headless', 'certifi', 'Pillow', 'pyinstaller']
    seen = set()
    from packaging.requirements import Requirement
    while pending:
        name = pending.pop()
        dist = metadata.distribution(name)
        name = dist.metadata['Name']
        if name in seen:
            continue
        seen.add(name)
        for requirement in dist.requires or []:
            req = Requirement(requirement)
            if req.marker is None or req.marker.evaluate():
                pending.append(req.name)
        for entry in dist.files or []:
            if any(word in entry.name.lower() for word in ('license', 'copying', 'notice')) and entry.suffix not in ('.py', '.pyc'):
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    destination = target / f'{name}-{dist.version}' / str(entry).replace('..', '_parent_')
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
    return {name: metadata.version(name) for name in sorted(seen)}


def build():
    preflight()
    info = {'version': VERSION, 'sources': source_hashes(), 'models': MODEL_SHA256,
            'python': platform.python_version(), 'platform': platform.platform(),
            'architecture': platform.machine(), 'built_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'commit': run('git', 'rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip()}
    generated = BACKEND / 'build_info.py'
    with tempfile.TemporaryDirectory(prefix='maskbridge-build-') as staging:
        staging = Path(staging)
        info['dependencies'] = collect_notices(staging / 'notices')
        generated.write_text('BUILD_INFO = ' + repr(info) + '\n', encoding='utf-8')
        try:
            env = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(staging / 'cache'))
            if os.name == 'nt':
                env['PATH'] = os.pathsep.join([str(Path(sys.executable).parent), sys.base_prefix,
                    str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']])
            run(sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--distpath', staging / 'dist',
                '--workpath', staging / 'work', ROOT / 'maskbridge_engine.spec',
                env=env)
            candidate = staging / 'dist' / 'maskbridge_engine'
            inspect_engine(candidate)
            run(executable(candidate), '--self-test', '--model-dir', BACKEND / 'models')
            shutil.copytree(staging / 'notices', candidate / 'THIRD_PARTY_NOTICES', dirs_exist_ok=True)
            backup = BACKEND / 'maskbridge_engine.previous'
            for target in (backup, ENGINE):
                if target.is_symlink() or not target.resolve().is_relative_to(BACKEND.resolve()):
                    raise RuntimeError('Unsafe engine replacement path')
            if backup.exists():
                shutil.rmtree(backup)
            if ENGINE.exists():
                ENGINE.rename(backup)
            try:
                shutil.copytree(candidate, ENGINE, symlinks=True)
            except BaseException:
                if ENGINE.exists():
                    shutil.rmtree(ENGINE)
                if backup.exists():
                    backup.rename(ENGINE)
                raise
        finally:
            generated.unlink(missing_ok=True)
    print('Engine rebuilt and smoke-tested; previous engine retained as maskbridge_engine.previous')


def verify_package(directory):
    info = (directory / 'Info.lua').read_text(encoding='utf-8')
    import re
    for name in re.findall(r'[A-Za-z][A-Za-z0-9_]*\.lu[ac]', info):
        if not (directory / name).is_file():
            raise RuntimeError(f'Missing Lightroom entry point: {name}')
    for name in ('MaskBridgeMatte.lua', 'MaskBridgeUtils.lua', 'MaskBridgeConfig.lua', 'dkjson.lua', 'MaskBridgeInit.lua', 'MaskBridgeShutdown.lua'):
        if not (directory / name).is_file():
            raise RuntimeError(f'Missing plugin dependency: {name}')
    # The MIT licence asks for its notice in every copy of the software.
    if not (directory / 'LICENSE.txt').is_file():
        raise RuntimeError('Missing MIT licence notice: LICENSE.txt')
    # Open source: Lightroom runs the readable Lua sources, byte for byte those
    # recorded in the release manifest. No compiled Lua ships. ("._" files are
    # AppleDouble attribute records that ditto adds to macOS archives.)
    manifest = json.loads((directory / 'release-manifest.json').read_text(encoding='utf-8'))
    shipped = {path.name: sha(path) for path in directory.glob('*.lua') if not path.name.startswith('._')}
    if shipped != manifest.get('lua'):
        raise RuntimeError('Packaged Lua sources differ from the release manifest')
    for name, digest in MODEL_SHA256.items():
        if sha(directory / 'backend' / 'models' / name) != digest:
            raise RuntimeError(f'Model mismatch: {name}')
    for path in directory.rglob('*'):
        relative = path.relative_to(directory)
        # PyInstaller's OpenCV hook requires these public bootstrap sources.
        # Backend modules ship as bytecode inside the PYZ archive; their
        # sources live in the repository.
        cv2_runtime = relative.parts[:4] == ('backend', 'maskbridge_engine', '_internal', 'cv2')
        if path.name.startswith('.server_') or (path.suffix in ('.py', '.pyc') and not cv2_runtime) or path.suffix in ('.log', '.luc') or path.name in ('tests', '.DS_Store'):
            raise RuntimeError(f'Development artifact in package: {path}')


def windows_signature(exe):
    result = run('powershell.exe', '-NoProfile', '-NonInteractive', '-File',
        ROOT / 'tools/release/sign_windows.ps1', '-InspectOnly', '-Executable', exe,
        capture_output=True, text=True)
    return json.loads(result.stdout.strip())


def authorize_windows_package(signature, candidate, allow_unsigned):
    valid = signature['status'] == 'Valid' and signature['timestamped']
    if not candidate and not valid:
        if not (allow_unsigned and signature['status'] == 'NotSigned'):
            raise RuntimeError('Windows signature missing/invalid; sign or explicitly use --allow-unsigned-windows for a NotSigned engine')
    return bool(not candidate and allow_unsigned and not valid)


def package(candidate=False, allow_unsigned_windows=False):
    preflight()
    info = inspect_engine()
    if os.name == 'nt':
        info['signature'] = windows_signature(executable())
        info['unsigned_windows_authorized'] = authorize_windows_package(info['signature'], candidate, allow_unsigned_windows)
    if sys.platform == 'darwin' and not candidate:
        run('codesign', '--verify', '--deep', '--strict', executable())
        identity = run('codesign', '-dvv', executable(), capture_output=True, text=True)
        if 'Authority=Developer ID Application' not in identity.stderr:
            raise RuntimeError('Sign the rebuilt engine before making a commercial package')
        run('codesign', '-vvvv', '-R=notarized', '--check-notarization', executable())
    label = 'Windows' if os.name == 'nt' else 'macOS'
    archive = ROOT / f'MaskBridge_v{VERSION}_{label}{"_candidate" if candidate else ""}.zip'
    with tempfile.TemporaryDirectory(prefix='maskbridge-package-') as tmp:
        stage = Path(tmp) / PLUGIN.name
        stage.mkdir()
        for pattern in ('*.lua', 'TranslatedStrings_*.txt', 'README.md', 'CHANGELOG.md', 'THIRD_PARTY_LICENSES.md'):
            for path in PLUGIN.glob(pattern):
                shutil.copy2(path, stage / path.name)
        shutil.copy2(ROOT / 'LICENSE', stage / 'LICENSE.txt')
        for folder in ('docs', 'licenses'):
            shutil.copytree(PLUGIN / folder, stage / folder)
        (stage / 'backend/models').mkdir(parents=True)
        for name in MODEL_SHA256:
            shutil.copy2(BACKEND / 'models' / name, stage / 'backend/models' / name)
        shutil.copytree(ENGINE, stage / 'backend/maskbridge_engine', symlinks=True)
        # The plugin ships its Lua sources unchanged; each one must parse as
        # Lua 5.1 (Lightroom's dialect). Nothing is compiled to bytecode.
        for path in sorted(stage.glob('*.lua')):
            check_lua51_syntax(path)
        for pattern in ('*.py', '*.spec', 'requirements*.txt'):
            for path in (stage / 'backend').glob(pattern):
                path.unlink()
        info['lua'] = {p.name: sha(p) for p in PLUGIN.glob('*.lua')}
        info['engine_sha256'] = sha(executable())
        info['candidate'] = candidate
        (stage / 'release-manifest.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
        verify_package(stage)
        fd, temporary = tempfile.mkstemp(prefix=archive.stem + '-', suffix='.zip', dir=archive.parent)
        os.close(fd)
        try:
            if sys.platform == 'darwin':
                run('ditto', '-c', '-k', '--keepParent', stage, temporary)
            else:
                with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as bundle:
                    for path in sorted(stage.rglob('*')):
                        if path.is_file():
                            bundle.write(path, str(path.relative_to(stage.parent)))
            with zipfile.ZipFile(temporary) as bundle:
                if bundle.testzip() is not None:
                    raise RuntimeError('Archive CRC verification failed')
            os.replace(temporary, archive)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print(f'Created and verified: {archive}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'package', 'verify'])
    parser.add_argument('--candidate', action='store_true', help='Explicit local test package; not a signed commercial release')
    parser.add_argument('--allow-unsigned-windows', action='store_true', help='Explicitly authorize a commercial Windows package without Authenticode')
    args = parser.parse_args()
    if args.command == 'build': build()
    elif args.command == 'package': package(args.candidate, args.allow_unsigned_windows)
    else: preflight(); inspect_engine(); print('Source, model and engine provenance verified')


if __name__ == '__main__':
    main()
