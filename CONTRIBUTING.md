# Contributing to Mask Bridge

Thank you for helping. Mask Bridge works on people's photo catalogs and original files, so a few rules matter more than style.

## Reporting a problem

Open an [issue](https://github.com/nicolasdiolez/mask-bridge/issues) with:

- your system (macOS version and chip, or Windows version) and Lightroom Classic version;
- the Mask Bridge version (Plug-in Manager);
- what you did, what you expected, what happened;
- the diagnostic report: **File › Plug-in Manager › Mask Bridge › Copy diagnostic report**. It includes the end of the engine log, with local paths (your user name, your folders) and photo file names. Read it before pasting it into the issue and replace anything you would rather keep private, or send it to maskbridge@nicolasdiolez.com instead.

Do not attach photos you cannot share publicly.

To report a security problem, do not open an issue: see [SECURITY.md](SECURITY.md).

## Rules every change must keep

**Original files**
- Never overwrite or modify an original, including when another path points to the same file (hard links, symlinks, case or Unicode variants).
- Reserve free output names for the whole batch before writing, and reject any overlap between inputs and outputs.
- Keep Unicode filenames exactly as they are, and keep ICC profiles.

**Lightroom catalog**
- Before changing anything in Lightroom, keep the recovery snapshot, check catalog access and the selection.
- Keep the operation lock, the options frozen when a batch starts, and clean-up or restoration on error. A crash is not a guaranteed restoration: do not claim it is.

**Results**
- Distinguish a server that is alive, models that are ready, and a result that was actually written. A requested output that is missing, the alpha PNG in particular, is a visible failure.
- Count confirmed outputs, not requests.

**Time and cancellation**
- Bound processing, temporary renders and timeouts.
- Keep cancellation between jobs and waiting for jobs already started. Do not promise to interrupt a native inference immediately, and never replay a change after an uncertain answer.

**Masks**
- Matte estimates a binary silhouette; it is not an exact export of Lightroom's gradient masks. Any change to mask processing must keep details, holes and alpha, and be checked on representative photos (hair, thin structures, holes, reflective objects).

**Build**
- A change to the Python engine requires rebuilding the engine before packaging; `package` refuses a stale engine.
- Keep the hash-locked dependencies, Lua 5.1 compatibility for the plugin, the third-party notices and the package exclusions.
- The engine makes no network connection during use. Keep it that way.

## Pull requests

1. Branch from `main`, one topic per pull request.
2. Run the tests that cover what you changed, then the whole suite:
   `python -m pytest MaskBridge.lrplugin/backend/tests -q` (see [BUILDING.md](BUILDING.md)).
3. In the description, report separately: Python/Lua tests, real inference, tests inside Lightroom, and the platforms you tried. An Apple Silicon build validates neither Windows nor an Intel Mac.
4. Interface text exists in 9 languages (`TranslatedStrings_*.txt`). Add new keys to all of them; an English placeholder is acceptable if you mark it in the pull request.

By contributing, you agree that your contribution is released under the [MIT license](LICENSE).
