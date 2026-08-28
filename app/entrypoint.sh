#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 LOONIS Wennaël

set -e

MODE=$1

echo "Mode: $MODE"

case "$MODE" in

  build-engine)
    echo "Building TensorRT engine..."

    # NOTE: do NOT torch.cuda.init() here — on Jetson Orin Nano unified memory it
    # carves out GPU device memory before trtexec starts, leaving trtexec only
    # ~5-9 MB for tactics (needs 43+ MB) → "Engine set up failed". trtexec manages
    # its own TensorRT/CUDA session; no torch pre-init is needed.

    # Model artifacts are named after the dataset dir (e.g. sheep_template,
    # mike). MODEL_NAME is injected by the build-engine k3s Job (rendered from
    # build_model.yml = basename of TRAINING_PROJECT_DIR). Fallback `my_model`
    # for legacy deploys built before this naming convention.
    MODEL_FILE="${MODEL_NAME:-my_model}"
    export MODEL_FILE
    echo "Building engine for model: ${MODEL_FILE}"

    # Per-model build precision. Read /app/build-config.json keyed by
    # MODEL_FILE. Default fp32 (legacy/backward compat — pigs stay FP32 at
    # 30 FPS; imgsz=1280 models use fp16 for ~15 FPS on Orin Nano). The build
    # config is rsync'd to the Jetson by build_model.yml alongside the ONNX.
    PRECISION=$(python3 - <<'PYEOF'
import json, os
cfg = {}
try:
    with open("/app/build-config.json") as f:
        cfg = json.load(f)
except (FileNotFoundError, json.JSONDecodeError, OSError):
    pass
m = cfg.get(os.environ.get("MODEL_FILE", ""), {})
print(str(m.get("precision", "fp32")).lower())
PYEOF
    )
    echo "Build precision for ${MODEL_FILE}: ${PRECISION}"

    EXTRA_FLAGS=""
    if [ "$PRECISION" = "fp16" ]; then
      EXTRA_FLAGS="--fp16"
    fi

    /usr/src/tensorrt/bin/trtexec \
      --onnx="/app/model/${MODEL_FILE}.onnx" \
      $EXTRA_FLAGS \
      --saveEngine="/app/model/${MODEL_FILE}.engine"

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