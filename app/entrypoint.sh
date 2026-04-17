#!/bin/bash
set -e

if [ ! -f ./model/my_model.engine ]; then
  echo "Génération du moteur TensorRT..."
  /usr/src/tensorrt/bin/trtexec \
    --onnx=./model/my_model.onnx \
    --saveEngine=./model/my_model.engine
else
  echo "Engine déjà existant"
fi

exec python3 src/main.py