#!/usr/bin/env python3
"""
Convertit birefnet_lite.onnx (fp32) -> fp16, puis MESURE l'impact qualité réel :
pour chaque image de test on passe fp32 ET fp16 dans onnxruntime CPU et on compare
les alphas (max diff, mean diff, % pixels qui bougent de >2/255). Sort aussi une
planche visuelle fp32 | fp16 | diff×5 par image pour inspection à l'œil.

Go/no-go fp16 : si max diff alpha reste faible (<~3/255) et rien de visible sur les
bords/cheveux, on ship fp16 (~112 Mo au lieu de 223).

Usage : python3 to_fp16.py [photo.jpg ...]
"""
import os
import sys
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
import time
import numpy as np
import cv2
import onnx
from onnxconverter_common import float16
import onnxruntime as ort

HERE = os.path.dirname(os.path.abspath(__file__))
FP32 = os.path.join(HERE, "weights", "birefnet_lite.onnx")
FP16 = os.path.join(HERE, "weights", "birefnet_lite_fp16.onnx")
SIZE = 1024
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)

# Photos sur lesquelles comparer fp32 et fp16 : python3 to_fp16.py a.jpg b.jpg
# (portraits avec cheveux, animaux à poils longs). Sans photo, seule la conversion a lieu.
TEST_IMAGES = sys.argv[1:]


def preprocess(img_rgb, size):
    x = cv2.resize(img_rgb, (size, size)).astype(np.float32) / 255.0
    x = (x - MEAN) / STD
    return x.transpose(2, 0, 1)[None].astype(np.float32)


def run(sess, inp):
    # respecte le dtype d'entrée attendu par la session (fp32 ou fp16)
    want = sess.get_inputs()[0].type
    x = inp.astype(np.float16) if "float16" in want else inp
    return sess.run(None, {"input": x})[0][0, 0].astype(np.float32)  # (H,W) alpha 0..1


def main():
    # 1. conversion fp16
    print(f"[fp16] chargement {FP32} …")
    m32 = onnx.load(FP32)
    # keep_io_types=True laisse un Conv avec types mixtes (bug d'insertion de Cast sur
    # ce graphe deform-conv). On convertit tout le graphe uniformément en fp16, I/O
    # comprises, et on alimente l'entrée en fp16.
    # noms des Cast->FLOAT présents dans le graphe ORIGINAL (à recâbler en fp16).
    # On NE touche PAS aux Cast que le convertisseur va insérer aux frontières des
    # ops laissées en fp32 (Resize…) : ceux-là doivent rester Cast->FLOAT.
    orig_float_casts = {
        n.name for n in m32.graph.node
        if n.op_type == "Cast" and any(a.name == "to" and a.i == 1 for a in n.attribute)
    }
    print(f"[fp16] Cast->FLOAT d'origine à recâbler : {len(orig_float_casts)}")

    print("[fp16] conversion float16 (graphe entier, I/O fp16, shape-infer ON)…")
    m16 = float16.convert_float_to_float16(
        m32, keep_io_types=False, disable_shape_infer=False)

    # Le convertisseur laisse ces Cast d'origine avec to=FLOAT(1) tout en marquant leurs
    # voisins en float16 -> type mismatch. Le graphe étant uniformément fp16, on les passe
    # en Cast->FLOAT16(10). Les Cast de frontière insérés par le convertisseur (noms *_cast_*
    # absents de l'original) restent en FLOAT pour alimenter les ops fp32-bloquées.
    flipped = 0
    for n in m16.graph.node:
        if n.op_type == "Cast" and n.name in orig_float_casts:
            for a in n.attribute:
                if a.name == "to" and a.i == 1:
                    a.i = 10
                    flipped += 1
    print(f"[fp16] Cast FLOAT->FLOAT16 recâblés : {flipped}")
    onnx.save(m16, FP16)
    a = os.path.getsize(FP32) / 1e6
    b = os.path.getsize(FP16) / 1e6
    print(f"[fp16] fp32 {a:.1f} Mo -> fp16 {b:.1f} Mo  ({b/a*100:.0f}%)")

    # 2. sessions
    so = ort.SessionOptions()
    s32 = ort.InferenceSession(FP32, so, providers=["CPUExecutionProvider"])
    s16 = ort.InferenceSession(FP16, so, providers=["CPUExecutionProvider"])

    # latence warm fp16
    dummy = np.random.rand(1, 3, SIZE, SIZE).astype(np.float16)
    s16.run(None, {"input": dummy})
    t = time.time(); s16.run(None, {"input": dummy}); warm16 = time.time() - t

    outdir = os.path.join(HERE, "out", "_fp16_check")
    os.makedirs(outdir, exist_ok=True)

    print("\n========== IMPACT QUALITÉ fp32 -> fp16 ==========")
    print(f"{'image':<40} {'maxΔ/255':>9} {'meanΔ/255':>10} {'%px>2':>7}")
    worst = 0.0
    for img_path in TEST_IMAGES:
        if not os.path.exists(img_path):
            print(f"  (absente) {img_path}")
            continue
        rgb = cv2.cvtColor(cv2.imread(img_path), cv2.COLOR_BGR2RGB)
        inp = preprocess(rgb, SIZE)
        a32 = run(s32, inp)
        a16 = run(s16, inp)
        d = np.abs(a32 - a16)
        maxd = d.max() * 255
        meand = d.mean() * 255
        pct = (d * 255 > 2).mean() * 100
        worst = max(worst, maxd)
        name = os.path.basename(img_path)
        print(f"{name:<40} {maxd:>9.2f} {meand:>10.3f} {pct:>6.2f}%")

        # planche visuelle : fp32 | fp16 | diff amplifiée
        h = 512
        def to_img(al):
            g = (np.clip(al, 0, 1) * 255).astype(np.uint8)
            g = cv2.resize(g, (h, h), interpolation=cv2.INTER_NEAREST)
            return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
        diff_amp = np.clip(d * 5, 0, 1)
        panel = np.hstack([to_img(a32), to_img(a16), to_img(diff_amp)])
        cv2.imwrite(os.path.join(outdir, name.replace(".jpg", "_fp16cmp.png")), panel)

    print("=================================================")
    print(f"pire écart alpha    : {worst:.2f}/255")
    print(f"latence fp16 warm   : {warm16:.2f}s @ {SIZE}px")
    print(f"planches            : {outdir}/*_fp16cmp.png  (fp32 | fp16 | diff×5)")
    verdict = "GO fp16" if worst < 3.0 else ("À INSPECTER" if worst < 8 else "fp16 RISQUÉ")
    print(f"verdict             : {verdict}")


if __name__ == "__main__":
    main()
