# Building Mask Bridge

The Lua plugin runs as is. The engine (`backend/`) is a Python program frozen with PyInstaller, so each platform builds its own engine: an archive built on an Apple Silicon Mac is not a Windows or Intel Mac build.

## Prerequisites

- Python **3.13** (3.13.15 or later in the 3.13 series), 64-bit
- Git
- macOS 14+ on Apple Silicon, or Windows 10/11 x64
- About 2 GB of free disk space for the environment, models and build

## 1. Environment

macOS:

```sh
python3.13 -m venv .venv-release
.venv-release/bin/python -m pip install pip==26.2.1
.venv-release/bin/python -m pip install --require-hashes -r tools/release/requirements-lock.txt
```

Windows (PowerShell):

```powershell
py -3.13 -m venv .venv-release
.venv-release\Scripts\python.exe -m pip install pip==26.2.1
.venv-release\Scripts\python.exe -m pip install --require-hashes -r tools/release/requirements-lock.txt
```

The lock file pins every dependency with its hashes. Do not upgrade a single library inside the build environment; change `tools/release/requirements.in`, regenerate the lock, and reinstall.

## 2. Models

```sh
.venv-release/bin/python tools/fetch_models.py
```

This downloads the two models into `MaskBridge.lrplugin/backend/models/` and checks their SHA-256:

- `rfdetr_seg_medium.onnx`: RF-DETR Seg Medium (Apache 2.0), the ONNX export published as [PierreMarieCurie/rf-detr-onnx](https://huggingface.co/PierreMarieCurie/rf-detr-onnx);
- `birefnet_lite_fp16.onnx`: [BiRefNet_lite](https://huggingface.co/ZhengPeng7/BiRefNet_lite) (MIT), exported to ONNX and converted to fp16 for Mask Bridge.

To rebuild the BiRefNet file yourself (its SHA-256 may differ with other library versions): create the pinned conda environment of `experiments/birefnet/setup_onnx_env.sh`, run `export_onnx.py --variant lite`, then `to_fp16.py photo1.jpg photo2.jpg…`, which converts the model and compares fp32 and fp16 alphas on the photos you pass. The comments in these scripts are in French.

## 3. Tests

```sh
.venv-release/bin/python -m pytest MaskBridge.lrplugin/backend/tests -q
```

The suite covers the engine, the HTTP server, path safety, the Lua plugin (run against a Lightroom SDK double) and the release scripts. It does not open Lightroom.

## 4. Build the engine

macOS:

```sh
./build_backend_optimized.sh
```

Windows:

```powershell
.venv-release\Scripts\python.exe tools\release\release.py build
```

`build` freezes the engine in a temporary folder, runs both models with the frozen engine, then replaces `backend/maskbridge_engine` (the previous engine is kept in `backend/maskbridge_engine.previous`).

## 5. Package

macOS, unsigned test archive:

```sh
./package_plugin.sh --candidate
.venv-release/bin/python tools/release/verify_macos.py --archive MaskBridge_v<version>_macOS_candidate.zip --output native-validation.json
```

Windows, unsigned archive:

```powershell
.venv-release\Scripts\python.exe tools\release\release.py package --candidate
.venv-release\Scripts\python.exe tools\release\verify_windows.py MaskBridge_v<version>_Windows_candidate.zip native-validation
```

`package` does not rebuild: it refuses an engine older than the Python sources, checks versions, source and model hashes, the dependency lock and the architecture, then writes the ZIP atomically with a `release-manifest.json`. The verification scripts unzip the archive into a temporary Unicode path and run both models and the HTTP server from the packaged engine, without Python on the PATH.

## Signing

Official macOS releases are signed with a Developer ID and notarized by Apple (`codesign_and_notarize.sh`, with credentials in the maintainer's keychain). Without signing, macOS Gatekeeper blocks a downloaded engine; a build you made yourself on the same Mac runs normally.

Windows releases are currently unsigned; `codesign_windows.bat` and `tools/release/sign_windows.ps1` sign them when `MASKBRIDGE_SIGNING_THUMBPRINT` points to a certificate in the personal store.

## Continuous integration

`.github/workflows/ci.yml` runs the tests on macOS and Windows, builds the Windows engine (the build runs both models) and packages a Windows candidate on every push to `main` and every pull request, and keeps the ZIP as a workflow artifact. The full archive check, `tools/release/verify_windows.py`, needs more memory for BiRefNet than GitHub's Windows runners provide: it runs on a Windows PC before each release. Workflow artifacts are test builds, not releases: official builds are signed by the maintainer and distributed at [nicolasdiolez.com/maskbridge](https://nicolasdiolez.com/maskbridge), with their SHA-256 in the GitHub release notes.

## Installing your build

Unzip the archive, then in Lightroom Classic use **File › Plug-in Manager › Add** and choose `MaskBridge.lrplugin`. To update, quit Lightroom, replace the folder, and restart.
