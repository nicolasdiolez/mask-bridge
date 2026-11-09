# Mask Bridge: notes for coding agents

Mask Bridge is a Lightroom Classic plugin (Lua 5.1, `MaskBridge.lrplugin/*.lua`) with a local engine (Python 3.13 + ONNX Runtime, `MaskBridge.lrplugin/backend/`) frozen with PyInstaller. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the rules and [BUILDING.md](BUILDING.md) for the build.

## Setup and checks

```sh
python3.13 -m venv .venv-release
.venv-release/bin/python -m pip install --require-hashes -r tools/release/requirements-lock.txt
.venv-release/bin/python tools/fetch_models.py
.venv-release/bin/python -m pytest MaskBridge.lrplugin/backend/tests -q
```

Run the tests that cover your change first, then the whole suite. The suite runs the plugin's Lua against a Lightroom SDK double (Lua 5.1 through `lupa`); it never opens Lightroom.

## Rules that must survive every change

- Never modify or overwrite an original file, including through another path to the same file. Reserve output names for the whole batch and reject input/output overlaps. Keep Unicode names and ICC profiles.
- Before changing anything in a Lightroom catalog: recovery snapshot, catalog access and selection checks, the operation lock, options frozen at start, clean-up or restoration on error. Do not claim a crash restores anything.
- Count outputs that were actually written. A requested output that is missing (the alpha PNG in particular) is a visible failure. Distinguish engine alive, models ready and result produced.
- Bound processing time, temporary renders and timeouts. Keep cancellation between jobs and waiting for started jobs; never promise to interrupt a native inference, never replay a change after an uncertain answer.
- Matte estimates binary silhouettes from Lightroom renders; it is not an exact export of Lightroom's soft masks. Changes to mask processing must keep details, holes and alpha and be checked on representative photos.
- No license keys, trials, accounts, telemetry or network calls during use (`test_open_source.py` guards this). The engine listens on 127.0.0.1 behind a per-run token.
- The plugin stays Lua 5.1 and ships readable `.lua` sources. Interface strings exist in 9 `TranslatedStrings_*.txt` files: add every new key to all of them.
- A change to the Python engine requires rebuilding the engine before packaging. Keep the hash-locked dependencies, third-party notices and package exclusions. Model hashes in `tools/fetch_models.py` must match `MODEL_SHA256` in `backend/cli.py`.

## Git and reporting

- One branch per change, pull request to `main`, CI green before merge. Never rewrite `main`'s history.
- Never commit secrets, signing material, personal photos, local paths or private notes. Validation evidence that contains such material stays out of this repository.
- Report separately: Python/Lua tests, real inference, tests inside Lightroom, and each platform tried. An Apple Silicon build validates neither Windows nor an Intel Mac.

## Maintainer-only actions

Notarization (it uploads the engine to Apple), tags and GitHub releases, uploads to the download store and changes to nicolasdiolez.com happen only when the maintainer asks for them in the task.
