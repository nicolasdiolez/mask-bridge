#!/bin/bash
# Env conda ISOLÉ aux versions figées pour l'export ONNX (deform-conv2d-onnx-exporter
# ne marche qu'avec un torch ancien ; le venv principal en torch 2.7 système échoue).
# Python 3.11 (wheels torch 2.1 dispo) + numpy<2 (requis par torch 2.1).
set -e
ENV=birefnet-onnx

conda create -y -n "$ENV" python=3.11
conda run -n "$ENV" pip install -q \
  "torch==2.1.2" "torchvision==0.16.2" "numpy==1.26.4" \
  "transformers==4.44.2" "timm" "einops" "kornia==0.7.3" \
  "onnx" "onnxruntime" "opencv-python-headless" \
  "deform-conv2d-onnx-exporter"
echo "✅ env '$ENV' prêt"
conda run -n "$ENV" python -c "import torch,torchvision,onnx,onnxruntime,deform_conv2d_onnx_exporter as d; print('torch',torch.__version__,'| tv',torchvision.__version__,'| onnx',onnx.__version__,'| ort',onnxruntime.__version__)"
