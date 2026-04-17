"""
Inference module for the pig counting application.

This module handles TensorRT-based inference for object detection.
"""

import time
import numpy as np
import cv2
import pycuda.autoinit
import pycuda.driver as cuda
import tensorrt as trt
import logging

logger = logging.getLogger(__name__)


class Inference:
    """
    YOLO class that wraps TensorRT ops, preprocess, and postprocess ops.
    
    Attributes:
        ctx (cuda.Device): CUDA context.
        stream (cuda.Stream): CUDA stream.
        context (trt.IExecutionContext): TensorRT execution context.
        engine (trt.ICudaEngine): TensorRT engine.
        host_inputs (list): Host input buffers.
        cuda_inputs (list): CUDA input buffers.
        host_outputs (list): Host output buffers.
        cuda_outputs (list): CUDA output buffers.
        bindings (list): Buffer bindings.
        input_w (int): Input width.
        input_h (int): Input height.
        batch_size (int): Batch size.
    """
    
    def __init__(self, engine_file_path):
        """
        Initialize the YOLO TensorRT model.
        
        Args:
            engine_file_path (str): Path to the TensorRT engine file.
        """
        self.ctx = cuda.Device(0).make_context()
        self.stream = cuda.Stream()

        TRT_LOGGER = trt.Logger(trt.Logger.INFO)
        runtime = trt.Runtime(TRT_LOGGER)

        # Deserialize engine
        with open(engine_file_path, "rb") as f:
            engine = runtime.deserialize_cuda_engine(f.read())

        if engine is None:
            raise RuntimeError("Failed to load TensorRT engine")

        self.context = engine.create_execution_context()

        self.host_inputs = []
        self.cuda_inputs = []
        self.host_outputs = []
        self.cuda_outputs = []
        self.bindings = []

        self.input_w = None
        self.input_h = None

        # New API for TensorRT
        for i in range(engine.num_io_tensors):
            name = engine.get_tensor_name(i)
            shape = engine.get_tensor_shape(name)
            dtype = trt.nptype(engine.get_tensor_dtype(name))
            mode = engine.get_tensor_mode(name)

            logger.info(f"tensor: {name}, shape: {shape}, mode: {mode}")

            # Handle dynamic batch
            if shape[0] == -1:
                shape = (1, *shape[1:])
                self.context.set_input_shape(name, shape)

            size = trt.volume(shape)

            # Allocate buffers
            host_mem = cuda.pagelocked_empty(size, dtype)
            cuda_mem = cuda.mem_alloc(host_mem.nbytes)
            self.context.set_tensor_address(name, int(cuda_mem))

            self.bindings.append(int(cuda_mem))

            if mode == trt.TensorIOMode.INPUT:
                self.input_w = shape[-1]
                self.input_h = shape[-2]
                self.host_inputs.append(host_mem)
                self.cuda_inputs.append(cuda_mem)
            else:
                self.host_outputs.append(host_mem)
                self.cuda_outputs.append(cuda_mem)

        # Batch size
        input_name = engine.get_tensor_name(0)
        input_shape = self.context.get_tensor_shape(input_name)
        self.batch_size = input_shape[0]
        
        self.engine = engine

    def infer(self, image):
        self.ctx.push()
        start_pre = time.time()
        
        # récupère scale et padding aussi
        input_image, image_raw, origin_h, origin_w, r_scale, tx1, ty1 = self.preprocess_image(image)
        
        end_pre = time.time()
        start = time.time()

        np.copyto(self.host_inputs[0], input_image.ravel())
        cuda.memcpy_htod_async(self.cuda_inputs[0], self.host_inputs[0], self.stream)
        self.context.execute_async_v3(stream_handle=self.stream.handle)
        cuda.memcpy_dtoh_async(self.host_outputs[0], self.cuda_outputs[0], self.stream)
        self.stream.synchronize()
        self.ctx.pop()

        output = self.host_outputs[0]
        end = time.time()

        # retourne aussi r_scale et padding
        return output, end - start, origin_h, origin_w, end_pre - start_pre, r_scale, tx1, ty1

    def destroy(self):
        """Release resources."""
        self.ctx.pop()

    def preprocess_image(self, raw_bgr_image):
        image_raw = raw_bgr_image
        h, w, c = image_raw.shape
        image = cv2.cvtColor(image_raw, cv2.COLOR_BGR2RGB)

        r_w = self.input_w / w
        r_h = self.input_h / h

        if r_h > r_w:
            tw = self.input_w
            th = int(r_w * h)
            tx1 = tx2 = 0
            ty1 = int((self.input_h - th) / 2)
            ty2 = self.input_h - th - ty1
            r_scale = r_w
        else:
            tw = int(r_h * w)
            th = self.input_h
            tx1 = int((self.input_w - tw) / 2)
            tx2 = self.input_w - tw - tx1
            ty1 = ty2 = 0
            r_scale = r_h

        # Resize + padding
        image = cv2.resize(image, (tw, th))
        image = cv2.copyMakeBorder(image, ty1, ty2, tx1, tx2, cv2.BORDER_CONSTANT, None, (128,128,128))
        image = image.astype(np.float32) / 255.0
        image = np.transpose(image, [2,0,1])
        image = np.expand_dims(image, axis=0)

        return image, image_raw, h, w, r_scale, tx1, ty1

    def post_process(self, output, origin_h, origin_w):
        """
        Postprocess the output to get detections.
        
        Args:
            output (numpy.ndarray): Output from inference.
            origin_h (int): Original height.
            origin_w (int): Original width.
            
        Returns:
            numpy.ndarray: Processed detections.
        """
        num_values = 6
        pred = output.reshape(-1, num_values)

        boxes = pred[:, :4]
        scores = pred[:, 4]
        class_ids = pred[:, 5].astype(int)

        mask = scores >= 0.5  # CONF_THRESH
        boxes = boxes[mask]
        scores = scores[mask]
        class_ids = class_ids[mask]

        if len(boxes) == 0:
            return np.array([])

        return np.column_stack((boxes, scores, class_ids))
