"""
Unit tests for the counting module.
"""

import pytest
import numpy as np
from core.counting import Counting


def test_counting_initialization():
    """Test Counting initialization."""
    counting = Counting()
    assert counting.detections == {}
    assert counting.trails == {}
    assert counting.area_in_list == []
    assert counting.area_out_list == []


def test_counting_count():
    """Test count method."""
    counting = Counting()
    
    # Create mock data
    image_raw = np.zeros((480, 640, 3), dtype=np.uint8)
    result_boxes = np.array([[100, 100, 200, 200], [300, 300, 400, 400]])
    result_trackid = np.array([1, 2])
    result_classid = np.array([0, 0])
    
    counter_to_right = counting.count(image_raw, result_boxes, result_trackid, result_classid)
    assert isinstance(counter_to_right, int)
