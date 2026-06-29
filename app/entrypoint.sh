#!/bin/bash
set -e

MODE=$1

echo "Mode: $MODE"

case "$MODE" in

  build-engine)
    echo "Building TensorRT engine..."
    echo "Initializing GPU..."

    python3 - <<EOF
import torch
torch.cuda.init()
EOF

    sleep 5

    /usr/src/tensorrt/bin/trtexec \
      --onnx="/app/model/my_model.onnx" \
      --saveEngine="/app/model/my_model.engine"

    echo "Engine build complete"
    ;;

  serve)
    echo "Starting application..."
    exec python3 src/main.py
    ;;

  debug)
    echo "Starting debug mode (container will stay alive)..."
    exec tail -f /dev/null
    ;;

  test)
    echo "Running test mode..."
    exec python3 src/main.py \
      --input=FILE \
      --file=./video/test_640.mp4 \
      --drawtracking=True
    ;;

  validate)
    VIDEO="${VALIDATE_VIDEO:-./video/template-validation-9.mp4}"
    echo "Running validation mode on: $VIDEO"
    exec python3 src/main.py \
      --input=FILE \
      --file="$VIDEO" \
      --drawtracking=True
    ;;

  *)
    echo "Unknown mode: $MODE"
    exit 1
    ;;

esac