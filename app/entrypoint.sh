#!/bin/bash
set -e

MODE=$1

echo "Mode: $MODE"

if [ "$MODE" = "build-engine" ]; then
  echo "Building TensorRT engine..."
  #while true; do
  #  sleep 3600
  #done

  echo "Initializing GPU..."

  python3 - <<EOF
import torch
torch.cuda.init()
EOF

  sleep 5

  echo "Building TensorRT engine..."

  /usr/src/tensorrt/bin/trtexec \
    --onnx="/app/model/my_model.onnx" \
    --saveEngine="/app/model/my_model.engine" \

  echo "Engine build complete"
  exit 0
fi

if [ "$MODE" = "serve" ]; then
  echo "Starting application..."
  exec python3 src/main.py
fi

echo "Unknown mode: $MODE"
exit 1