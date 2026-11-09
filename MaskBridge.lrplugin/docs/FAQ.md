# Mask Bridge - FAQ & Troubleshooting

## General Questions

### What AI engine is used?

Mask Bridge uses **RF-DETR** (Real-time Detection Transformer), a state-of-the-art model that combines detection and segmentation in a single pass. It produces precise, natively smooth masks.

An optional **Fine detail** mode adds a second model, **BiRefNet**, for matting-grade edges (see below).

### What is "Fine detail (hair/fur)"?

**Fine detail** is an optional checkbox that produces maximum-quality edges — it resolves individual hair and fur strands that a standard mask blurs together. It runs a **BiRefNet** matting pass on top of the RF-DETR detection, refining only the object you asked for.

- **Cost:** Fine detail adds substantial CPU work. Processing time varies by computer, image size and subject count; use it for single shots or small selections.
- **Default:** off. Standard mode is faster and produces a clean hard edge.
- **The first Fine detail image takes longer** while BiRefNet loads and warms up. Subsequent requests reuse the loaded model. The model is released after 60 minutes without a Fine detail request to free RAM, so an occasional one-off shot pays that load again. Processing a selection in one go avoids it entirely.
- Works offline — the BiRefNet model is bundled with the plugin.
- **Safety fallback:** on some subjects that don't stand out from the scene (e.g. a chair in a busy room), the matting pass may not isolate the object. A coverage check can retain the standard mask when too much of the detected subject disappears. This check does not guarantee a better result: inspect difficult subjects in Preview before processing a large selection.

### What objects can be detected?

Mask Bridge detects **80 precise classes** (COCO standard), including:
- People
- Vehicles (car, motorcycle, bicycle, bus, airplane)
- Animals (dog, cat, bird, horse)
- Everyday objects (phone, laptop, suitcase, backpack)

See [DETECTION_CLASSES.md](DETECTION_CLASSES_en.md) for the full list.

### Can I detect custom objects?

The "Custom classes" field lets you use the **English names** of any of the 80 supported classes if they aren't in the quick-select list. Common French equivalents (e.g. `voiture`, `chien`) are also recognized.

*Example:* To detect teddy bears, type `teddy bear`.
*Note:* The plugin cannot detect arbitrary objects outside the 80 classes (e.g. specific jewelry, logos).

---

## Export & Formats

### Which export format should I choose?

| Format | Pros | Cons |
|--------|------|------|
| **JPEG** | Small files, universal compatibility | Lossy compression |
| **TIFF** | Lossless, 16-bit for advanced editing | Large files |
| **PNG** | Lossless, transparency support | Medium files |

**Recommendations:**
- Heavy retouching workflow: **TIFF 16-bit**
- Archiving / Web: **JPEG 90%**
- Photoshop compositing: **PNG**

### Which TIFF compression?

- **None**: No compression, largest files
- **LZW**: Lossless compression, good balance (recommended)
- **ZIP**: Best compression but slower

### Which resolution?

- **Original**: Keeps the native photo resolution
- **4096/2048/1024/512 px**: Limits the longest edge to that size
- **Custom**: Enter your own value (100-10000 px)

> For previews, use 1024 px. For final export, use Original or 4096 px.

### Can I use Mask Bridge directly from File > Export?

Yes. In the export dialog, choose **Mask Bridge (Export)** as the export service. The Mask Bridge panel at the top lets you set the objects to mask (prompts), invert, masks-only, PNG alpha and the mask naming pattern. The Dashboard remains the recommended workflow for large batches (progress, presets, exclude classes, resolution control).

---

## Export Lightroom Masks

### What is "Export Lightroom Masks"?

This feature exports Lightroom's **native** masks (Subject, Sky, Background, etc.) or your own brush/gradient masks as **grayscale PNG** files. White represents the masked area, black represents the background.

This is different from AI mask generation: it estimates binary silhouettes from Lightroom mask renders and saves them as standalone image files.

### What are the 4 modes?

| Mode | Description |
|------|-------------|
| **New AI Mask** | Generates a new Lightroom AI mask (Subject, Sky, Background, People, Objects, Landscape) then exports it |
| **Existing Mask** | Exports a specific mask you've already applied to the photo. Available only for a **single-photo** selection (mask IDs are per-photo); for several photos at once, use the All modes or New AI Mask. |
| **All Masks (Combined)** | Merges all existing masks into a single PNG |
| **All Masks (Individual)** | Exports each mask as a separate file |

### "Existing Mask" shows no masks

The photo must have at least one mask applied in the Develop module. Select the photo, go to Develop, apply a mask (e.g., Subject), then try again.

### The exported mask looks wrong on dark photos

Enhanced two-pass detection is always enabled and handles most dark backgrounds. If you still see issues, check that the photo's develop settings haven't been reset between export attempts.

### A very small mask disappears from the Combined export

Version 1.0.1 no longer removes regions based on their relative area. Small components and holes are preserved after thresholding. Since extraction uses rendered brightness, very faint masks can still be missed; this is an estimated binary silhouette, not a lossless native mask export.

---

## PNG Alpha / Transparency

### What does "Export with Transparency (PNG Alpha)" do?

When enabled, the plugin produces an additional **32-bit RGBA PNG** file alongside the grayscale mask. The original photo's RGB data is combined with the mask as an alpha channel, creating a cutout image with a transparent background.

Output filenames:
- AI batch (Generate masks): `photo.mask_alpha.png` (follows the mask naming pattern)
- Export Lightroom Masks: `photo_alpha.png`
- All Masks (Individual): `photo_MaskName_alpha.png` (one per mask)

### Does it work with both AI masks and Lightroom mask exports?

Yes. The PNG Alpha option works with:
- AI-generated masks (Generate masks)
- Export Lightroom Masks (all 4 modes)

### What format is the alpha file?

32-bit RGBA PNG. The RGB channels contain the original photo data, and the alpha channel contains the mask (white = opaque, black = transparent).

---

## AI Controls (Reload / Stop)

### What does "Reload" do?

It restarts the backend AI server. Use this if:
- The AI engine becomes unresponsive
- Processing seems stuck

### What does "Stop" do?

It stops the AI server completely, freeing memory and CPU resources. The server will restart automatically the next time you open the Dashboard.

### When should I use Stop?

Use it when you're done with mask generation and want to release the AI engine's memory. Memory use varies with the models and images processed; Windows HD validation observed over 12 GB of resident engine memory after a batch. Closing the Dashboard alone leaves the server running in the background. Wait for any active job to finish before using **Stop**.

---

## Common Issues

### "The plugin won't start"

1. **Check the installation**: the folder must be inside `Modules/`
2. **Restart Lightroom** completely
3. **Check logs**: `server_debug.log` in the plugin folder

### "Could not load script ..." errors at startup

Lightroom still has a plug-in entry pointing to a folder that was moved or deleted (e.g. an old copy added via **Add**). Open **File > Plug-in Manager**, select the entry shown in error and click **Remove**. Keep a single Mask Bridge installation — two copies loaded at the same time conflict with each other.

### "Models missing?"

The models are included in the plugin. If files are missing:
- Reinstall the full package (`MaskBridge_vX.Y.Z_macOS.zip` or `_Windows.zip`)
- Check that your antivirus hasn't deleted files

### "Masks are empty"

1. Verify that the **selected categories** match the objects in the image
2. Increase the **sensitivity** in settings
3. Use the **Preview** button to test on a single image

### "Processing is slow"

- The first processing is slower (loading models into memory)
- Subsequent runs are faster thanks to the cached server (~0.5s per image)
- **Fine detail (HD)** runs an additional BiRefNet pass; loading and processing time depend on your hardware and photographs. Turn it off for fast batch processing and enable it only when you need the finest edges.
- Processing a whole selection in one go is faster per photo than repeating single shots: the models stay loaded and several images are handled at once.

### "Binary / Engine not found"

If the Dashboard reports the engine is not found:
1. Make sure you copied the entire `backend` folder
2. **macOS**: Connect to the internet and restart Lightroom — Gatekeeper validates the notarization online at first launch. If still blocked, open **System Settings > Privacy & Security > Open Anyway**, or run `xattr -cr` on the plugin folder as a last resort.
3. **Windows**: Check your antivirus

---

## Free and Open Source

### Do I need a license key?

No. Since version 1.2.0, Mask Bridge is free and open source under the MIT license. There is no key, no activation and no account: every feature works as soon as the plugin is installed.

### I used a license key with an earlier version. What changes?

Nothing to do: install version 1.2.0 in place of the old one (see [Updating from an earlier version](INSTALL.md#updating-from-an-earlier-version)). Your key is no longer needed. Version 1.2.0 ignores the license files left by earlier versions, `license_cache.json` and `trial_marker.json`, in `~/Library/Application Support/MaskBridge/` (macOS) or `%LOCALAPPDATA%\MaskBridge\` (Windows). You can delete these two files.

### Does Mask Bridge connect to the internet?

No. The AI engine runs on your computer and only answers Lightroom, on `127.0.0.1`. The plugin goes online only when you click **Support Mask Bridge**, **Source code** or **Contact**, which open your browser or your e-mail application. On macOS, the system itself checks the Apple notarization online at the first launch (see below).

### How can I support Mask Bridge?

The **Support Mask Bridge** button in the Dashboard, also in **File > Plug-in Manager**, opens [nicolasdiolez.com/maskbridge](https://nicolasdiolez.com/maskbridge), where ready-to-install builds are pay what you want, from €0: choosing a price supports the project. The source code stays free on [GitHub](https://github.com/nicolasdiolez/mask-bridge).

### How do I get a new version?

Open your order from the confirmation e-mail, or sign in to Lemon Squeezy's [My Orders](https://app.lemonsqueezy.com/my-orders) page with the e-mail you used: new versions are added to your existing order, at no extra cost. To be told about new versions, watch the repository's releases on [GitHub](https://github.com/nicolasdiolez/mask-bridge/releases). Then follow [Updating from an earlier version](INSTALL.md#updating-from-an-earlier-version).

---

## macOS Issues

### "The developer cannot be verified"

The binary is **signed and notarized by Apple** (Developer ID: Nicolas Diolez), so this message should not appear on a standard setup with internet access.

If it still does (fully offline first launch, strict enterprise MDM, etc.):

1. Connect to the internet and reopen Lightroom — Gatekeeper validates the notarization online.
2. Or go to **System Settings > Privacy & Security** and click **Open Anyway**.
3. Last resort (Terminal):
   ```bash
   xattr -cr /path/to/MaskBridge.lrplugin
   ```

### Does the plugin need internet to launch?

Only the **first launch** on macOS requires internet so Gatekeeper can verify the Apple notarization ticket (the ticket is cached by macOS afterwards). Mask generation itself always works offline.

### Plugin can't find the binary

Verify that `maskbridge_engine` exists in `backend/maskbridge_engine/` and is executable:
```bash
chmod +x MaskBridge.lrplugin/backend/maskbridge_engine/maskbridge_engine
```

---

## Windows Issues

### "Windows Defender blocks the plugin"

This Windows release is unsigned. Check that the ZIP came from the official Mask Bridge page and compare its SHA-256 with the checksum in the release notes on GitHub. Keep Microsoft Defender enabled. If it blocks or quarantines the engine, contact support with the detection name; do not disable protection or add a blanket exclusion.

### Plugin doesn't detect the binary

Verify that `maskbridge_engine.exe` exists in the `backend/maskbridge_engine/` folder.

---

## Support

If your issue persists:

1. **Check the logs**: `server_debug.log`
2. **Contact support**: maskbridge@nicolasdiolez.com

Include in your message:
- Plugin version (v1.2.0)
- Operating system
- Description of the issue
- Log excerpt (if applicable)

---

(c) 2026 Nicolas Diolez. Released under the MIT license.


### Is Export Lightroom Masks a lossless native alpha export?

No. It estimates a **binary silhouette** from temporary Lightroom renders. Gradients,
partly opaque brush strokes and soft native alpha are not preserved. Small regions
and holes are retained by default; the tool no longer removes them by area. Working
renders use lossless TIFF. Use the AI Fine detail mode when a soft edge is required,
and inspect the result; neither path is a guarantee of pixel-perfect extraction.

Before temporary develop changes, Mask Bridge saves **Mask Bridge - Before export**
in the photo's Develop Snapshots. Settings are restored after normal processing and
handled errors. If Lightroom or the computer crashes during export, restore that
snapshot before continuing. Avoid changing the selected photo or mask during export.

### What happens when a destination already exists?

Mask Bridge keeps existing files and selects another output name. For example,
`image.jpg` can become `image_2.jpg`. Two masks with the same name get distinct paths.
An image or alpha that failed to export is reported as an incomplete operation.

### Does All include every recognized class?

The All shortcut selects the six Dashboard category groups. Use **View all classes**
and custom class names for other supported COCO classes. It does not add recognition
of arbitrary architecture, logos or objects outside that class list.
