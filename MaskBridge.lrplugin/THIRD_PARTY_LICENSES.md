# Third-Party Licenses

Mask Bridge includes the following third-party AI models and libraries:

---

## AI Models

### RF-DETR (Real-Time Detection Transformer with Segmentation)
- **Copyright:** © Roboflow
- **License:** Apache License 2.0
- **Source:** https://github.com/roboflow/rf-detr

### BiRefNet (Bilateral Reference Network) — `BiRefNet_lite`
- **Copyright:** © 2024 ZhengPeng7 (Peng Zheng)
- **License:** MIT License
- **Source:** https://github.com/ZhengPeng7/BiRefNet
- **Note:** Used as the optional fine-detail (matting) refinement model. Exported to
  ONNX and quantized to FP16 for this product; no model code is redistributed.

---

## MIT License (BiRefNet)

Copyright (c) 2024 ZhengPeng7

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## Apache License 2.0

Licensed under the Apache License, Version 2.0 (the "License");
you may not use these files except in compliance with the License.
You may obtain a copy of the License at:

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

---

## Python Libraries

The bundled engine (built with PyInstaller) embeds the following open-source
software:

| Library | License |
|---------|---------|
| Python | Python Software Foundation License |
| ONNX Runtime | MIT License |
| OpenCV | Apache 2.0 |
| NumPy | BSD License |
| Pillow | HPND / Pillow licence; bundled codec notices |
| certifi | Mozilla Public License 2.0 |
| PyInstaller bootloader | GPL 2.0 with Bootloader Exception (does not affect this product's licensing) |

---

## Lua Libraries

| Library | License |
|---------|---------|
| dkjson 2.11 (David Kolf's JSON module) | MIT License — http://dkolf.de/dkjson-lua/ |

---

For the full text of licenses, visit:
- Apache 2.0: https://www.apache.org/licenses/LICENSE-2.0
- MIT: https://opensource.org/licenses/MIT
- BSD: https://opensource.org/licenses/BSD-3-Clause
- MPL 2.0: https://www.mozilla.org/MPL/2.0/
- PSF: https://docs.python.org/3/license.html


## Included full notices and provenance

Full licence texts for RF-DETR, Python and the ONNX exporter are in `licenses/`.
The dkjson 2.11 source includes David Heiko Kolf's full MIT notice; its upstream
SHA-256 is `197cb50834c642f84b4cf99fe724932c50e6d9c92faec7ad89aa25e91df4d481`.
Upstream: https://dkolf.de/dkjson-lua/dkjson-2.11.lua.

The release builder collects distribution licence/NOTICE files, including native
codec notices when present, into `backend/maskbridge_engine/THIRD_PARTY_NOTICES/`.
`release-manifest.json` identifies the exact component versions and model hashes.
The local RF-DETR inference implementation uses the exporter's RGB square resize
and ImageNet normalisation contract; mask aggregation and class mapping are local.
BiRefNet Lite weights were converted to ONNX FP16; their provenance is documented
in the model experiment/export files retained in the development repository.
