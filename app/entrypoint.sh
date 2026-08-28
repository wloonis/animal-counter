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

    # BL-96 part (b): regenerate a STAGED <MODEL_FILE>.classes.yaml from the
    # freshly-compiled .onnx (the .onnx names are the source of truth for what
    # the engine outputs). This does NOT overwrite the active
    # /app/model/classes.yaml — an operator/ansible `cp` activates it. Pure
    # stdlib (re + ast), same grep technique as state.read_onnx_class_names()
    # and the validate script's cross-check. Best-effort: any error logs to
    # stderr and the heredoc still exits 0 (the engine already compiled — the
    # staged yaml is not a build gate; set -e-safe).
    python3 - <<'PYEOF'
import ast
import os
import re
import sys

model_file = os.environ.get("MODEL_FILE", "my_model")
onnx_path = os.path.join("/app/model", model_file + ".onnx")
staged_path = os.path.join("/app/model", model_file + ".classes.yaml")
tmp_path = os.path.join("/app/model", "." + model_file + ".classes.yaml.tmp")

try:
    with open(onnx_path, "rb") as fh:
        raw = fh.read()
except OSError as exc:
    sys.stderr.write(
        "WARN staged-classes.yaml: cannot read %s (%s); skipping\n"
        % (onnx_path, type(exc).__name__))
    sys.exit(0)

match = re.search(rb"\{[0-9]+: '[^']+'(, [0-9]+: '[^']+')*\}", raw)
if match is None:
    sys.stderr.write(
        "WARN staged-classes.yaml: no names dict found in %s; skipping\n"
        % onnx_path)
    sys.exit(0)
try:
    names_dict = ast.literal_eval(match.group(0).decode("utf-8", "replace"))
except (ValueError, SyntaxError) as exc:
    sys.stderr.write(
        "WARN staged-classes.yaml: cannot parse names dict in %s (%s); skipping\n"
        % (onnx_path, type(exc).__name__))
    sys.exit(0)
if not isinstance(names_dict, dict) or not names_dict:
    sys.stderr.write(
        "WARN staged-classes.yaml: parsed names is not a non-empty dict in %s; skipping\n"
        % onnx_path)
    sys.exit(0)

nc = len(names_dict)
names_list = [names_dict[i] for i in range(nc)]

# Resolve + clamp the default counting class to [0, nc). Non-fatal: a bad
# value logs a WARN and is clamped (the engine already compiled — must NOT
# abort the build; mirrors build_model.yml's range guard but non-fatal).
try:
    default_counting_class = int(
        os.environ.get("TRAINING_DEFAULT_COUNTING_CLASS", "1"))
except (TypeError, ValueError):
    sys.stderr.write(
        "WARN staged-classes.yaml: TRAINING_DEFAULT_COUNTING_CLASS unparseable; "
        "defaulting to 1\n")
    default_counting_class = 1
if default_counting_class < 0 or default_counting_class >= nc:
    clamped = max(0, min(nc - 1, default_counting_class))
    sys.stderr.write(
        "WARN staged-classes.yaml: TRAINING_DEFAULT_COUNTING_CLASS=%d out of "
        "range [0, %d); clamped to %d\n"
        % (default_counting_class, nc, clamped))
    default_counting_class = clamped

# Hand-write a minimal YAML (no PyYAML dependency). names is a YAML list.
lines = []
lines.append("model_name: %s" % model_file)
lines.append("model_version: %s" % model_file)
lines.append("nc: %d" % nc)
lines.append("names:")
for name in names_list:
    # Quote to be safe against names containing ':' or leading '-'.
    escaped = str(name).replace("'", "''")
    lines.append("  - '%s'" % escaped)
lines.append("default_counting_class: %d" % default_counting_class)
lines.append("")
body = "\n".join(lines)

# Atomic write: temp + os.replace. Never raises past here on the happy path.
try:
    with open(tmp_path, "w") as fh:
        fh.write(body)
    os.replace(tmp_path, staged_path)
except OSError as exc:
    sys.stderr.write(
        "WARN staged-classes.yaml: cannot write %s (%s); skipping\n"
        % (staged_path, type(exc).__name__))
    # Clean up the temp file if it lingers.
    try:
        os.remove(tmp_path)
    except OSError:
        pass
    sys.exit(0)

print("STAGED %s written (nc=%d)" % (staged_path, nc))
sys.exit(0)
PYEOF

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