"""
Unit tests for the rendering module.
"""

import pytest
import numpy as np
import cv2
from ui.rendering import Rendering


def test_rendering_initialization():
    """Test Rendering initialization."""
    rendering = Rendering(draw_box=True)
    assert rendering.draw_box == True


def test_rendering_calculate_center():
    """Test calculate_center method."""
    rendering = Rendering()
    bbox = [100, 100, 200, 200]
    
    center = rendering.calculate_center(bbox)
    assert center == (150, 150)


def test_rendering_display_counter():
    """Test display_counter method."""
    rendering = Rendering()
    
    # Create mock image
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    counter_to_right = 5
    
    result = rendering.display_counter(img, counter_to_right)
    assert result.shape == (480, 640, 3)
