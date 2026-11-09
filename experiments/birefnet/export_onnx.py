#!/usr/bin/env python3
"""
Export BiRefNet_lite -> ONNX (opset avec deform_conv2d substitué par ops standard),
puis VALIDATION onnxruntime CPU : correction (diff vs torch) + latence à froid/à chaud + taille.

C'est le go/no-go final phase 3 : si l'ONNX tourne sur onnxruntime vanilla sous ~10s/img,
BiRefNet_lite est intégrable comme mode optionnel « détourage fin ».

Usage :
  python3 export_onnx.py --variant lite
  python3 export_onnx.py --variant lite --image /chemin/photo.jpg   # valide sur une vraie image
"""
import os
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
import argparse
import time
import numpy as np
import cv2
import torch
import torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = {
    "lite":    ("ZhengPeng7/BiRefNet_lite", 1024),
    "general": ("ZhengPeng7/BiRefNet", 1024),
    "matting": ("ZhengPeng7/BiRefNet-matting", 1024),
}
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


class Wrap(nn.Module):
    """Sort uniquement la carte finale sigmoïdée (1 sortie propre pour l'ONNX)."""
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, x):
        out = self.m(x)
        out = out[-1] if isinstance(out, (list, tuple)) else out
        return out.sigmoid()


def preprocess(img_rgb, size):
    x = cv2.resize(img_rgb, (size, size)).astype(np.float32) / 255.0
    x = (x - MEAN) / STD
    return x.transpose(2, 0, 1)[None].astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="lite", choices=list(VARIANTS))
    ap.add_argument("--image", default=None)
    ap.add_argument("--opset", type=int, default=17)
    args = ap.parse_args()

    repo_id, size = VARIANTS[args.variant]
    out_path = os.path.join(HERE, "weights", f"birefnet_{args.variant}.onnx")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # 1. charge le modèle torch (CPU, fp32)
    from transformers import AutoModelForImageSegmentation
    print(f"[export] chargement {repo_id} …")
    model = AutoModelForImageSegmentation.from_pretrained(repo_id, trust_remote_code=True)
    model.eval().to("cpu").float()
    wrap = Wrap(model).eval()

    # 2. enregistre la substitution deform_conv2d -> ops ONNX standard
    import deform_conv2d_onnx_exporter as dce
    dce.register_deform_conv2d_onnx_op()

    # Les einops.rearrange du décodeur BiRefNet cassent l'inférence de forme statique :
    # au moment du symbolic, l'input ET l'offset du deform_conv ont une taille = None
    # (indép. de la version torch). Fix robuste : on ENREGISTRE d'abord les tailles
    # spatiales réelles via un forward instrumenté (dans l'ordre des appels), puis on les
    # réinjecte dans create_dcn_params dans le même ordre pendant l'export.
    dummy = torch.randn(1, 3, size, size, dtype=torch.float32)

    import sys as _sys
    bmod = next(m for name, m in _sys.modules.items()
                if name.endswith(".birefnet") and hasattr(m, "deform_conv2d"))
    _rec_hw = []
    _orig_dc = bmod.deform_conv2d

    def _rec(*a, **k):
        inp = k.get("input", a[0] if a else None)
        _rec_hw.append((int(inp.shape[2]), int(inp.shape[3])))
        return _orig_dc(*a, **k)
    bmod.deform_conv2d = _rec
    with torch.no_grad():
        wrap(dummy)  # passe d'enregistrement
    bmod.deform_conv2d = _orig_dc
    print(f"[export] {len(_rec_hw)} deform_conv enregistrés, tailles: {_rec_hw}")

    # réinjection dans l'ordre
    _orig_gtds = dce.get_tensor_dim_size
    dce._fallback_hw = None

    def _gtds(tensor, dim):
        v = _orig_gtds(tensor, dim)
        if v is None:
            if dim == 0:  # batch : on exporte en batch 1
                return 1
            if dim in (2, 3) and dce._fallback_hw is not None:
                return dce._fallback_hw[dim - 2]
        return v
    dce.get_tensor_dim_size = _gtds

    _orig_cdp = dce.create_dcn_params
    _idx = {"i": 0}

    def _cdp(input, weight, offset, *a, **k):
        i = _idx["i"]
        dce._fallback_hw = _rec_hw[i] if i < len(_rec_hw) else None
        _idx["i"] = i + 1
        try:
            return _orig_cdp(input, weight, offset, *a, **k)
        finally:
            dce._fallback_hw = None
    dce.create_dcn_params = _cdp
    print("[export] deform_conv2d onnx op enregistré (+ réinjection tailles réelles)")

    # 3. export (taille fixe 1024 = pipeline réel)
    print(f"[export] torch.onnx.export …")
    print(f"[export] torch.onnx.export -> {out_path} (opset {args.opset}) …")
    with torch.no_grad():
        torch.onnx.export(
            wrap, dummy, out_path,
            input_names=["input"], output_names=["mask"],
            opset_version=args.opset, do_constant_folding=False,
        )
    mb = os.path.getsize(out_path) / 1e6
    print(f"[export] OK — {mb:.1f} Mo")

    # 4. validation onnxruntime CPU
    import onnxruntime as ort
    so = ort.SessionOptions()
    sess = ort.InferenceSession(out_path, so, providers=["CPUExecutionProvider"])

    if args.image and os.path.exists(args.image):
        rgb = cv2.cvtColor(cv2.imread(args.image), cv2.COLOR_BGR2RGB)
    else:
        rgb = (np.random.rand(size, size, 3) * 255).astype(np.uint8)
    inp = preprocess(rgb, size)

    # correction vs torch
    with torch.no_grad():
        ref = wrap(torch.from_numpy(inp)).numpy()
    t0 = time.time(); ort_out = sess.run(None, {"input": inp})[0]; cold = time.time() - t0
    t1 = time.time(); _ = sess.run(None, {"input": inp})[0]; warm = time.time() - t1
    maxdiff = float(np.abs(ref - ort_out).max())

    print("\n========== VERDICT ONNX ==========")
    print(f"variante        : {args.variant}  ({repo_id})")
    print(f"fichier ONNX    : {mb:.1f} Mo   ({out_path})")
    print(f"onnxruntime CPU : à froid {cold:.2f}s | à chaud {warm:.2f}s  @ {size}px")
    print(f"correction      : max|torch - onnx| = {maxdiff:.4f}  ({'OK' if maxdiff < 0.02 else 'À VÉRIFIER'})")
    print(f"providers       : {sess.get_providers()}")
    print("==================================")


if __name__ == "__main__":
    main()
