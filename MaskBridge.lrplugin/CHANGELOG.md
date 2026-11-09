# Changelog

All notable changes to Mask Bridge are documented in this file.

## [1.2.0] - 2026-11-07

Mask Bridge is now free and open source software, released under the MIT license.

- Remove the license key, the activation and the free trial: every feature works as soon as the plugin is installed, with no account and no internet connection. The engine no longer contacts any licensing service.
- Replace the license panel of the Dashboard with a small **Support Mask Bridge** button that opens the support page in your browser. The footer button that writes to support is now labelled **Contact**.
- Show in the Plug-in Manager that Mask Bridge is open source under the MIT license, with links to the source code and to the support page.
- The plugin ships its Lua sources: release archives contain the readable `.lua` files instead of compiled `.luc` files, and the MIT license as `LICENSE.txt`.
- License files left by earlier versions (`license_cache.json`, `trial_marker.json`) are no longer read and can be deleted.
- Replace an engine left running by an earlier version instead of reusing it.
- On Windows, start the engine without PowerShell: Microsoft Defender could block the previous launcher, and the engine then never started.

## [1.1.1] - 2026-10-16

- Count photos where no object of the selected classes was detected apart from the generated masks: their empty mask is still saved, and the summary lists them separately.
- Show engine warnings (no object detected, unknown classes, HD unavailable) in the interface language.
- Leave the activation field empty instead of showing the saved licence key; leaving it empty reactivates the saved key.
- Add update instructions to the installation guide: quit Lightroom, replace the plugin folder, restart.

## [1.1.0] - 2026-10-15

- Add a free 14-day trial: a trial licence key from Lemon Squeezy, checked online like paid licences, limited to one computer, with a short offline allowance and a clear end-of-trial message. The Dashboard shows the days left and offers to buy a licence; a purchased key replaces the trial without manual deactivation.
- Export Lightroom AI masks (Matte) for a whole selection from the Library on Lightroom Classic 15.3 and later.
- Keep separate recovery snapshots for masters and virtual copies.
- Keep the Windows Dashboard above Lightroom only.
- Read licence caches and batch manifests as UTF-8 on every system, so non-ASCII text no longer invalidates an activation on Windows.
- Keep the machine identity stable on computers without a hardware network address.
- Translate the shared Cancel button in all interface languages.

## [1.0.2] - 2026-09-14

Shared maintenance sources; Windows distribution remains unsigned.

- Fix Generate in Lightroom by creating bounded export sessions outside the Lua iterator's non-yielding context.
- Drain the current render batch on cancellation and remove its canceled outputs before stopping.
- Show the underlying Lightroom export error, the configured plugin version and a clear licence-required message.
- Remove the fixed processing-time estimate from the HD description in all interface languages.

- Restore asynchronous, exclusive licence activation from the compact dialog.
- Preserve exact Unicode filenames and prevent normalization from replacing a neighboring file.
- Store Windows runtime state and logs in a private per-user directory with explicit NTFS permissions.
- Launch the engine without a visible console or shell expansion of installation paths.
- Reject Windows device paths, alternate streams and protected system destinations.
- Limit Windows ONNX CPU threads for concurrent exports; retain a bounded deployment override.
- Update the runtime to Python 3.13.15, verify locked dependencies and write release archives atomically.
- Record unsigned Windows distribution explicitly and make signature verification failures blocking.
- Update the Windows layout, activation translations and installation guidance.

Existing Windows and macOS archives do not acquire these changes automatically. Repackage and validate each platform from these sources before distribution; preserve the historical macOS 1.0.1 package.

## [1.0.0] - 2026-07-20

First public release of Mask Bridge — AI-powered mask generation for Adobe Lightroom Classic.

### AI Segmentation

- **RF-DETR engine** — a real-time detection transformer that combines detection and segmentation in a single pass (~0.5s per image on Apple Silicon), producing natively smooth masks
- **80 object classes** (COCO standard): people, vehicles, animals, furniture, electronics, and more
- **Sensitivity control** — four levels: Precise, Balanced, Generous, Maximum
- **Custom & exclude classes** — target or exclude specific classes by name
- **Fine detail (hair/fur) — optional** — a maximum-quality mode that resolves individual hair and fur strands using a BiRefNet matting pass, gated to the detected object (~5s per image; ideal for single shots or small selections rather than large batches). Off by default; when disabled, masks generate at full speed with a clean hard edge.
- **Bundled AI models** — the RF-DETR detection model and the BiRefNet fine-detail model ship inside the package and work fully offline on first launch (no download required)

### Export Lightroom Masks

Export Lightroom's native masks (Subject, Sky, Background, etc.) or your own brush/gradient masks as grayscale PNG files (white = mask, black = background).

- **New AI Mask** — generate a Lightroom AI mask (Subject, Sky, Background, People, Objects, Landscape) and export it
- **Existing Mask** — export a specific mask already applied to the photo (single-photo selection)
- **All Masks (Combined)** — merge all masks into a single PNG
- **All Masks (Individual)** — export each mask as a separate file
- Two-pass detection for accurate results on dark backgrounds

### Export Options

- **Formats**: JPEG (50–100% quality), TIFF (8/16-bit, with None/LZW/ZIP compression), PNG
- **Resolution**: Original, 4096, 2048, 1024, 512 px, or a custom value (100–10000 px)
- **PNG Alpha / Transparency** — export a 32-bit RGBA cutout with a transparent background; works with both AI mask generation and Lightroom mask exports

### Workflow

- **Batch processing** with model caching
- **Live preview** to test settings before running a full batch
- **File > Export integration** — choose objects, invert, masks-only, alpha, fine detail and naming directly in the export dialog — sensitivity and exclusions follow your Dashboard settings; a progress bar tracks the whole export + AI sequence and can be canceled
- **Mask naming patterns** and output directory selection
- **Preset system** to save and reuse configurations
- **Reload / Stop AI** — restart the engine (and re-validate the license) or free system resources directly from the Dashboard
- **Adaptive Dashboard** — sizes its scrollable area to the Lightroom window (fits small laptops, uses more space on large displays)
- **Notification sound** on completion (macOS), with a toggle to disable it

### Platforms & Licensing

- **macOS** 14.0+ (Sonoma, Apple Silicon) — engine signed and notarized by Apple (Developer ID: Nicolas Diolez); installs cleanly with no Gatekeeper warning. Internet is required at first launch for online notarization validation.
- **Windows** 10/11 (64-bit)
- **Standalone engine** — no Python installation required
- **LemonSqueezy licensing** — online activation with a 7-day offline grace period; Standard / Pro / Team plans
- Available in **9 languages**: English, French, German, Spanish, Italian, Portuguese, Japanese, Chinese, Arabic

---

© 2026 Nicolas Diolez. Released under the MIT license; see LICENSE.txt.
