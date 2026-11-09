# -*- mode: python ; coding: utf-8 -*-
"""
Mask Bridge - PyInstaller Spec File
Builds the maskbridge_engine binary from cli.py (main entry point).
Excludes heavy unused modules for a smaller binary.
"""

import sys
import os

block_cipher = None

# Backend source directory
backend_dir = os.path.join('MaskBridge.lrplugin', 'backend')

# Add missing Python SSL DLLs (robust detection, handles venv)
extra_binaries = []
python_base = getattr(sys, 'base_prefix', sys.prefix)
python_dlls_dir = os.path.join(python_base, 'DLLs')

if os.path.exists(python_dlls_dir):
    import glob
    # Standard Python 3.12+ DLLs
    for dll in glob.glob(os.path.join(python_dlls_dir, 'libcrypto-*.dll')):
        extra_binaries.append((dll, '.'))
    for dll in glob.glob(os.path.join(python_dlls_dir, 'libssl-*.dll')):
        extra_binaries.append((dll, '.'))
    # Module itself
    for dll in glob.glob(os.path.join(python_dlls_dir, '_ssl.pyd')):
        extra_binaries.append((dll, '.'))

# All Python source files to include as hidden imports
hiddenimports = [
    'inference_engine',
    'server',
    'validation',
    'atomic_io',
    'runtime_paths',
    'dashboard_window',
    'build_info',
    'PIL.Image',
    'PIL.PngImagePlugin',
    'PIL.TiffImagePlugin',
    # Core dependencies
    'onnxruntime',
    'cv2',
    'numpy',
    'certifi',
    # Standard library modules used at runtime
    'http.server',
    'json',
    'hashlib',
    'ssl',
    'urllib.request',
    'urllib.error',
    'urllib.parse',
    'threading',
    'socket',
    'logging',
    'unicodedata',
    'argparse',
    'traceback',
    'pathlib',
    'platform',
]

# Heavy modules to exclude (not used by Mask Bridge)
excludes = [
    # ML frameworks (only onnxruntime is needed)
    'torch', 'torchvision', 'torchaudio',
    'tensorflow', 'keras', 'tensorboard',
    # Data science
    'matplotlib', 'scipy', 'pandas', 'sklearn', 'scikit-learn',
    # Testing
    'pytest', '_pytest', 'pluggy',
    # Web frameworks / serialization
    'pydantic', 'fastapi', 'uvicorn', 'starlette',
    'flask', 'django', 'jinja2',
    # GUI
    'tkinter', '_tkinter',
    # Build / packaging
    'setuptools', 'distutils', 'pip', 'pkg_resources',
    'ensurepip', 'venv',
    # Standard library not needed
    'test', 'unittest', 'pydoc', 'doctest',
    'lib2to3', 'xmlrpc',
    'multiprocessing', 'concurrent',
    'asyncio',
    'pdb', 'profile', 'pstats',
    'idlelib', 'turtle', 'turtledemo',
    'sqlite3', 'dbm',
    # Other heavy packages
    'pygments', 'IPython', 'notebook', 'jupyter',
    'sympy', 'networkx',
    'fsspec', 'pyarrow',
    'transformers', 'huggingface_hub',
    'safetensors', 'tokenizers',
]

a = Analysis(
    [os.path.join(backend_dir, 'cli.py')],
    pathex=[backend_dir],
    binaries=extra_binaries,
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='maskbridge_engine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='maskbridge_engine',
)
