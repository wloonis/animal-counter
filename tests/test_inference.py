"""
Unit tests for the inference module.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from core.inference import Inference


def test_yolo_trt_initialization():
    """Test YOLO TensorRT initialization."""
    with patch('builtins.open', create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = b'mock_engine'
        with patch('tensorrt.Runtime') as mock_runtime:
            mock_engine = MagicMock()
            mock_runtime.return_value.deserialize_cuda_engine.return_value = mock_engine
            mock_engine.num_io_tensors = 2
            mock_engine.get_tensor_name.side_effect = ['input', 'output']
            mock_engine.get_tensor_shape.side_effect = [[1, 3, 640, 640], [1, 84, 8400]]
            mock_engine.get_tensor_dtype.side_effect = [0, 0]
            mock_engine.get_tensor_mode.side_effect = [0, 1]
            
            yolo = Inference('mock_engine_path')
            assert yolo.input_w == 640
            assert yolo.input_h == 640


def test_yolo_trt_preprocess_image():
    """Test YOLO TensorRT image preprocessing."""
    with patch('builtins.open', create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = b'mock_engine'
        with patch('tensorrt.Runtime') as mock_runtime:
            mock_engine = MagicMock()
            mock_runtime.return_value.deserialize_cuda_engine.return_value = mock_engine
            mock_engine.num_io_tensors = 2
            mock_engine.get_tensor_name.side_effect = ['input', 'output']
            mock_engine.get_tensor_shape.side_effect = [[1, 3, 640, 640], [1, 84, 8400]]
            mock_engine.get_tensor_dtype.side_effect = [0, 0]
            mock_engine.get_tensor_mode.side_effect = [0, 1]
            
            yolo = Inference('mock_engine_path')
            
            # Create a mock image
            mock_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
            
            # Call preprocess_image
            processed_image, image_raw, h, w = yolo.preprocess_image(mock_image)
            
            # Assertions
            assert processed_image.shape == (1, 3, 640, 640)
            assert image_raw.shape == (480, 640, 3)
            assert h == 480
            assert w == 640


def test_yolo_trt_post_process():
    """Test YOLO TensorRT post-processing."""
    with patch('builtins.open', create=True) as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = b'mock_engine'
        with patch('tensorrt.Runtime') as mock_runtime:
            mock_engine = MagicMock()
            mock_runtime.return_value.deserialize_cuda_engine.return_value = mock_engine
            mock_engine.num_io_tensors = 2
            mock_engine.get_tensor_name.side_effect = ['input', 'output']
            mock_engine.get_tensor_shape.side_effect = [[1, 3, 640, 640], [1, 84, 8400]]
            mock_engine.get_tensor_dtype.side_effect = [0, 0]
            mock_engine.get_tensor_mode.side_effect = [0, 1]
            
            yolo = Inference('mock_engine_path')
            
            # Create mock output
            mock_output = np.random.rand(1, 84, 8400)
            
            # Call post_process
            result = yolo.post_process(mock_output, 480, 640)
            
            # Assertions
            assert isinstance(result, np.ndarray)
