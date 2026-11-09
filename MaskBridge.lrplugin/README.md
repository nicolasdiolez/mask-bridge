# Mask Bridge

**Version 1.2.0** | AI-powered mask generation for Adobe Lightroom Classic | Free and open source (MIT)

## Overview

Mask Bridge is a professional Lightroom Classic plugin that automatically generates precise object masks using **RF-DETR** (Real-time Detection Transformer), a state-of-the-art AI that combines detection and segmentation in a single pass.

Mask Bridge is **free and open source** under the MIT license. There is no account, no license key and no activation: the AI runs entirely on your computer, and generating masks needs no internet connection.

## Features

### AI-Powered Segmentation
- **RF-DETR Engine:** Next-generation real-time detection and segmentation
- **80 Object Classes:** Humans, vehicles, animals, furniture, electronics, and more
- **Fast Batch Masking:** clean, natively smooth masks across hundreds of photos
- **Fine Detail (hair/fur):** optional maximum-quality mode that resolves individual hair and fur strands with a BiRefNet matting pass (processing time varies by PC and image; best for single shots or small selections). Off by default.
- **Sensitivity Control:** Four levels — Precise, Balanced, Generous, Maximum
- **Custom & Exclude Classes:** Add specific COCO classes by name, or exclude unwanted ones

### Export Lightroom Masks
- **Grayscale PNG Export:** Convert Lightroom's native masks to standalone image files (white = mask, black = background)
- **4 Export Modes:**
  - **New AI Mask** — generate a new Lightroom AI mask (Subject, Sky, Background, People, Objects, Landscape) and export it
  - **Existing Mask** — export a specific mask already applied to the photo (available when a single photo is selected)
  - **All Masks (Combined)** — merge all masks into a single PNG
  - **All Masks (Individual)** — export each mask as a separate file
- **Enhanced Detection:** Two-pass processing for accurate results on dark backgrounds

### Export Options
- **Multiple Formats:** JPEG, TIFF (8/16-bit), PNG
- **Flexible Resolution:** Presets (4096, 2048, 1024, 512) or custom value
- **TIFF Compression:** None, LZW, or ZIP
- **Quality Control:** Adjustable JPEG quality (50-100%)
- **PNG Alpha / Transparency:** Export 32-bit RGBA PNG with transparent background

### Workflow
- **Batch Processing:** Process hundreds of photos with model caching
- **Live Preview:** Test settings before full batch
- **File > Export Integration:** select "Mask Bridge (Export)" as the export service — objects to mask, invert, masks-only, PNG alpha, fine detail and naming, directly in the export dialog — sensitivity and exclusions follow your Dashboard settings
- **Mask Naming:** Multiple patterns (.mask.png, _mask.png, -mask.png, _MaskBridge.png)
- **Preset System:** Save and reuse your favorite configurations

### Dashboard Controls
- **Reload AI:** Restart the AI engine
- **Shutdown AI:** Stop the AI server to free system resources
- **Sound Notifications:** Optional completion sound after batch processing (macOS)

### Free and Open Source
- **No key, no account:** every feature works as soon as the plugin is installed
- **Local and offline:** photos and masks never leave your computer
- **Source code:** [github.com/nicolasdiolez/mask-bridge](https://github.com/nicolasdiolez/mask-bridge)
- **Download:** ready-to-install builds at [nicolasdiolez.com/maskbridge](https://nicolasdiolez.com/maskbridge), pay what you want from €0; the **Support Mask Bridge** button in the Dashboard opens that page
- **Build it yourself:** see BUILDING.md in the source repository

## Requirements

- **Adobe Lightroom Classic** 14.0 or newer
- **Disk Space:** ~420 MB (including both AI models)
- **OS:** macOS 14+ (Sonoma, Apple Silicon) or Windows 10/11

> 💡 The plugin uses a **standalone binary** - no Python installation required!
>
> 📦 The AI models are **bundled with the plugin** - no model download required, works fully offline on first launch.

## Installation

See the [Installation Guide](docs/INSTALL.md) for detailed instructions.

**Quick Start:**
1. Copy `MaskBridge.lrplugin` to your Lightroom `Modules/` folder
2. In Lightroom: **File → Plug-in Manager → Add**
3. Enable the plugin

## First Use

1. Open the Dashboard: **Library → Plug-in Extras → Mask Bridge Dashboard**
2. Choose object categories and click **Generate masks**

## Usage

### Generate AI Masks
1. Select photos in Lightroom
2. Open the Dashboard (**Library → Plug-in Extras → Mask Bridge Dashboard**)
3. Configure settings (format, resolution, sensitivity)
4. Choose object categories or enter custom classes
5. Optionally enable **Fine detail (hair/fur)** for maximum edge quality (slower), and/or **Export with Transparency (PNG Alpha)**
6. Click **Generate masks**

### Export Lightroom Masks
1. Select photos in Lightroom
2. Open the Dashboard and click **Export Lightroom Masks**
3. Choose a mode (New AI Mask, Existing Mask, All Combined, All Individual)
4. Click **Export Lightroom Masks** to generate grayscale PNGs

## Supported Objects

Mask Bridge detects 80 COCO classes. See [DETECTION_CLASSES.md](docs/DETECTION_CLASSES_en.md) for the complete list.

**Categories:**
- 👤 Humans (person)
- 🚗 Vehicles (car, truck, bus, motorcycle, bicycle, boat, airplane, train)
- 🐕 Animals (dog, cat, horse, cow, sheep, bird, elephant, bear, zebra, giraffe...)
- 🪑 Furniture (chair, couch, bed, dining table, toilet)
- 📱 Electronics (tv, laptop, cell phone, keyboard, mouse, remote)
- 🌿 Plants (potted plant)

## Troubleshooting

See the [FAQ](docs/FAQ.md) for common issues and solutions.

**Quick fixes:**
- **Plugin not visible:** Ensure folder is in `Modules/`
- **No detections:** Try increasing sensitivity
- **Empty masks:** Check that selected categories match image content
- **LR Mask export blank:** Make sure the photo has at least one mask applied before using "Existing Mask" or "All" modes

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## License

- **Plugin:** MIT — see `LICENSE` at the root of the [source repository](https://github.com/nicolasdiolez/mask-bridge), shipped as `LICENSE.txt` in the plugin folder of each release archive
- **AI Models:** Apache 2.0 (RF-DETR), MIT (BiRefNet) — see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)

---

© 2026 Nicolas Diolez. Released under the MIT license.
