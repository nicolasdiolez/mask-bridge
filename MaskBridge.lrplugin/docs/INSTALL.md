# Mask Bridge - Installation Guide

**Version 1.2.0** | AI Plugin for Adobe Lightroom Classic | Free and open source (MIT)

---

## Prerequisites

| Component | Required Version |
|-----------|-----------------|
| macOS | 14.0 (Sonoma) or later — Apple Silicon |
| Windows | 10 or 11 (64-bit) |
| Adobe Lightroom Classic | 14.0 or later |
| Disk Space | ~420 MB (including both AI models) |
| RAM | Allow memory for both Lightroom and the AI engine. For Windows HD, 32 GB is recommended; 8 GB and 16 GB configurations have not been validated. |

Windows HD processing can use substantially more memory than Standard. In the Windows validation on a PC with 28 GB available RAM, the engine retained over 12 GB of resident memory after a seven-photo HD batch. This is an observation, not an upper bound. Use Standard on memory-constrained systems and use **Stop** in the Dashboard after processing to release the engine's memory.

> No Python required: the plugin includes a standalone optimized engine for Apple Silicon (macOS) and Windows.

---

## Download

Mask Bridge is free and open source under the MIT license: no license key, no activation, no account.

- **Ready-to-install builds**: [nicolasdiolez.com/maskbridge](https://nicolasdiolez.com/maskbridge), pay what you want, from €0
- **Source code**: [github.com/nicolasdiolez/mask-bridge](https://github.com/nicolasdiolez/mask-bridge), to build Mask Bridge yourself
- **Checksums**: the SHA-256 of each archive is listed in its [release notes](https://github.com/nicolasdiolez/mask-bridge/releases)

---

## macOS Installation

### Step 1: Download

Download `MaskBridge_v1.2.0_macOS.zip` from [nicolasdiolez.com/maskbridge](https://nicolasdiolez.com/maskbridge).

### Step 2: Extract and copy

1. **Double-click** the archive to extract it
2. **Copy** the `MaskBridge.lrplugin` folder to:
   ```
   ~/Library/Application Support/Adobe/Lightroom/Modules/
   ```
   > Create the `Modules` folder if it doesn't exist.

### Step 3: Enable in Lightroom

1. Open **Lightroom Classic**
2. Go to **File > Plug-in Manager**
3. Click **Add** and select `MaskBridge.lrplugin`
4. Check the box to **enable** the plugin

### Step 4: macOS Security

The plugin binary is **signed and notarized by Apple** (Developer ID: Nicolas Diolez). On a standard setup, Gatekeeper validates the binary silently at first launch — no warning, no manual step.

> **Requires internet at first launch.** Apple's Gatekeeper verifies the notarization ticket online (CloudKit). Make sure you're connected to the internet the first time you run the plugin. Subsequent launches work offline.

**If Gatekeeper still blocks the binary** (rare — e.g. fully offline machine, strict enterprise profile):
1. Connect to the internet and reopen Lightroom, **or**
2. Go to **System Settings > Privacy & Security** and click **"Open Anyway"** for `maskbridge_engine`, **or**
3. As a last resort, run in Terminal:
   ```bash
   xattr -cr ~/Library/Application\ Support/Adobe/Lightroom/Modules/MaskBridge.lrplugin
   ```

---

## Windows Installation

### Step 1: Download

Download `MaskBridge_v1.2.0_Windows.zip` from [nicolasdiolez.com/maskbridge](https://nicolasdiolez.com/maskbridge).

### Step 2: Extract and copy

1. **Right-click** the archive > **Extract All**
2. **Copy** the `MaskBridge.lrplugin` folder to:
   ```
   C:\Users\{YourName}\AppData\Roaming\Adobe\Lightroom\Modules\
   ```
   > Create the `Modules` folder if it doesn't exist.

### Step 3: Enable in Lightroom

1. Open **Lightroom Classic**
2. Go to **File > Plug-in Manager**
3. Click **Add** and select `MaskBridge.lrplugin`
4. Check the box to **enable** the plugin

### Step 4: Windows security

This Windows release is **not digitally signed**. Windows may show an unknown-publisher or SmartScreen warning. Download only from the official Mask Bridge page and compare the ZIP SHA-256 with the checksum in the release notes on GitHub. Keep Microsoft Defender enabled. If the engine is blocked or quarantined, contact support with the detection name; do not add a blanket antivirus exclusion.

Runtime files and logs are stored in the user application-data folder under `MaskBridge/Runtime-v2`, protected by Windows permissions. Earlier versions kept license files under `%LOCALAPPDATA%/MaskBridge`; version 1.2.0 no longer uses them.

---

## Updating from an earlier version

1. **Quit Lightroom Classic** completely.
2. Extract the new archive.
3. **Replace** the old `MaskBridge.lrplugin` folder in `Modules/` with the new one (delete or move the old folder first: do not merge the two).
4. **Start Lightroom Classic** again.

> Lightroom only loads the plugin's translations at startup. If you replace the folder while Lightroom is open, new labels can appear in English until you restart it.

If the Plug-in Manager pointed to the old folder at another location, select the new folder with **Add** and remove the old entry.

---

## First Use

### 1. Open the Dashboard

**Library > Plug-in Extras > Mask Bridge Dashboard...**

### 2. Generate your first mask

1. Select photos in Lightroom
2. Open the Dashboard
3. Choose object categories (e.g. "Humans")
4. Click **Generate masks**

---

## Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| "Engine not found" | macOS: ensure internet access at first launch (notarization check); Windows: check antivirus |
| Empty masks | Check selected categories, increase sensitivity |
| Plugin not visible | Ensure the folder is inside `Modules/` |
| Export fails | Verify the output folder exists and is writable |

For more help, see [FAQ.md](FAQ.md).

---

(c) 2026 Nicolas Diolez. Released under the MIT license.
