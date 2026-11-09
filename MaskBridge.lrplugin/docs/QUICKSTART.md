# Mask Bridge - Quick Start Guide

> Generate your first AI mask in 2 minutes!

---

## 1. Download

Mask Bridge is free and open source (MIT license): no license key, no activation, no account.

1. Go to **[nicolasdiolez.com/maskbridge](https://nicolasdiolez.com/maskbridge)**: ready-to-install builds are pay what you want, from €0. The source code is on [GitHub](https://github.com/nicolasdiolez/mask-bridge).
2. Download `MaskBridge_v1.2.0_macOS.zip` or `MaskBridge_v1.2.0_Windows.zip`

---

## 2. Install

### macOS

1. **Extract** the downloaded archive
2. **Copy** `MaskBridge.lrplugin` to:
   ```
   ~/Library/Application Support/Adobe/Lightroom/Modules/
   ```
3. **Open Lightroom** > File > Plug-in Manager
4. **Add** and enable the plugin

> The binary is **signed and notarized by Apple** — no Gatekeeper warning on a standard setup. Just make sure you're **connected to the internet at first launch** so macOS can validate the notarization ticket online.
>
> If Gatekeeper still blocks it (fully offline / strict enterprise setup), open **System Settings > Privacy & Security** and click **Open Anyway**, or run:
> ```bash
> xattr -cr ~/Library/Application\ Support/Adobe/Lightroom/Modules/MaskBridge.lrplugin
> ```

### Windows

1. **Right-click** the archive > **Extract All**
2. Open the extracted folder, then **copy** `MaskBridge.lrplugin` to:
   ```
   C:\Users\<YourName>\AppData\Roaming\Adobe\Lightroom\Modules\
   ```
3. **Open Lightroom** > File > Plug-in Manager
4. **Add** and enable the plugin

> This Windows release is unsigned. Keep Microsoft Defender enabled; if it blocks the engine, contact support with the detection name and verify your download using the release checksum. Do not add a blanket antivirus exclusion.

---

## 3. Your First Mask

1. **Select** 1-10 photos in Lightroom
2. Open the **Mask Bridge Dashboard**
3. Check **Humans** (or another category)
4. Click **Preview** to test on one photo
5. Click **Generate X masks** for batch processing

PNG masks will be created in your chosen output folder.

---

## Quick Presets

| Button | Categories enabled |
|--------|-------------------|
| Portrait | Humans only |
| Product | Furniture, electronics |
| Vehicle | Cars, motorcycles... |
| All | All categories |

---

## 4. Export Lightroom Masks (Grayscale)

Export Lightroom's native masks (Subject, Sky, etc.) or your own masks as grayscale PNG files:

1. In the **Dashboard**, click **Export Lightroom Masks**.
2. Choose the mode:
   - **New AI Mask** — generates a new AI mask (Subject, Sky, Background, etc.)
   - **Existing Mask** — pick one specific mask already on your photo (single-photo selection; for several photos at once, use the modes below or New AI Mask)
   - **All Masks (Combined)** — exports all masks merged into a single PNG
   - **All Masks (Individual)** — exports each mask as a separate file
3. Click **Export Lightroom Masks** to start the conversion.

---

## Need Help?

- [Full installation guide](INSTALL.md)
- [FAQ & Troubleshooting](FAQ.md)
- maskbridge@nicolasdiolez.com

---

(c) 2026 Nicolas Diolez. Released under the MIT license.
