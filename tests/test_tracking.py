"""
Unit tests for the tracking module.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock
from core.tracking import Tracking


def test_tracking_initialization():
    """Test Tracking initialization."""
    tracking = Tracking()
    assert tracking.detections == {}
    assert tracking.trails == {}
    assert tracking.count_drawings == []
    assert tracking.area_in_list == []
    assert tracking.area_out_list == []


def test_tracking_undo_letterbox():
    """Test undo_letterbox method."""
    tracking = Tracking()
    box = [100, 100, 200, 200]
    origin_h, origin_w = 480, 640
    input_h, input_w = 640, 640
    
    result = tracking.undo_letterbox(box, origin_h, origin_w, input_h, input_w)
    assert isinstance(result, list)
    assert len(result) == 4


def test_tracking_count():
    """Test count method."""
    tracking = Tracking()
    
    # Create mock data
    image_raw = np.zeros((480, 640, 3), dtype=np.uint8)
    result_boxes = np.array([[100, 100, 200, 200], [300, 300, 400, 400]])
    result_trackid = np.array([1, 2])
    result_classid = np.array([0, 0])
    
    count = tracking.count(image_raw, result_boxes, result_trackid, result_classid)
    assert isinstance(count, int)


def test_tracking_calculate_center():
    """Test calculate_center method."""
    tracking = Tracking()
    bbox = [100, 100, 200, 200]
    
    center = tracking.calculate_center(bbox)
    assert center == (150, 150)
