"""
BL-93 unit tests for ``state.resolve_input_config`` (stdlib only).

``resolve_input_config`` validates the per-model input keys
(``input_source`` / ``input_url`` / ``input_device`` / ``input_width`` /
``input_height``) from the flat runtime-settings dict and returns a
fully-populated dict, falling back to the env-derived ``Settings`` defaults
when absent/invalid. It must **never raise** (fail-open → env fallback).

These tests mirror the existing ``tests/test_resolve_*.py`` / BL-68 style:
  * a minimal fake ``Settings`` (stdlib only — no python-dotenv);
  * heavy Jetson-only deps (``trackers``) stubbed in ``sys.modules`` so
    ``app/src/state.py`` imports in a plain-CPython CI environment;
  * the real ``state.resolve_input_config`` is exercised unmodified.
"""

import os
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Stub heavy Jetson-only modules so state.py is importable without GPU deps.
# state.py only needs trackers.utils.iou (IoU/GIoU/DIoU/CIoU/BIoU); the rest
# of its imports (json, logging, os, tempfile, threading, settings,
# utils.shared_state) are light stdlib / pure-python.
# ---------------------------------------------------------------------------
_STUBS = {
    "trackers": types.ModuleType("trackers"),
    "trackers.utils": types.ModuleType("trackers.utils"),
    "trackers.utils.iou": types.ModuleType("trackers.utils.iou"),
}
for _name in ("IoU", "GIoU", "DIoU", "CIoU", "BIoU"):
    setattr(_STUBS["trackers.utils.iou"], _name, type(_name, (), {}))
for _n, _m in _STUBS.items():
    sys.modules.setdefault(_n, _m)

# Make app/src importable (settings, state, utils live there).
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_SRC = os.path.join(os.path.dirname(_HERE), "app", "src")
if _APP_SRC not in sys.path:
    sys.path.insert(0, _APP_SRC)

import state as state_mod  # noqa: E402  (import after stubs + path setup)


# ---------------------------------------------------------------------------
# Minimal fake Settings (stdlib only — avoids depending on python-dotenv).
# ---------------------------------------------------------------------------
class FakeSettings:
    """Exposes only the input-related attributes resolve_input_config reads."""

    def __init__(self, **overrides):
        self.INPUT_SOURCE = "CAMERA"
        self.VIDEO_PATH = "/dev/video0"
        self.INPUT_WIDTH = 640
        self.INPUT_HEIGHT = 480
        self.FPS_OUTPUT = 30
        for k, v in overrides.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# resolve_input_config
# ---------------------------------------------------------------------------
def test_valid_camera_config():
    """A fully-specified valid CAMERA config is returned as-is (uppercased)."""
    rt = {
        "input_source": "camera",
        "input_device": "/dev/video1",
        "input_width": 1280,
        "input_height": 720,
    }
    out = state_mod.resolve_input_config(rt, FakeSettings())
    assert out["input_source"] == "CAMERA"
    assert out["input_device"] == "/dev/video1"
    assert out["input_width"] == 1280
    assert out["input_height"] == 720
    # input_url is irrelevant for CAMERA → None (no env fallback for non-STREAM).
    assert out["input_url"] is None


def test_valid_stream_config():
    """A valid STREAM config requires input_url (used as the RTSP source)."""
    rt = {
        "input_source": "stream",
        "input_url": "rtsp://drone:8554/live",
        "input_width": 1280,
        "input_height": 720,
    }
    out = state_mod.resolve_input_config(rt, FakeSettings())
    assert out["input_source"] == "STREAM"
    assert out["input_url"] == "rtsp://drone:8554/live"
    assert out["input_width"] == 1280
    assert out["input_height"] == 720
    # input_device irrelevant for STREAM → None.
    assert out["input_device"] is None


def test_valid_file_config():
    """FILE config: neither input_url nor input_device required."""
    rt = {"input_source": "FILE"}
    out = state_mod.resolve_input_config(rt, FakeSettings())
    assert out["input_source"] == "FILE"
    assert out["input_url"] is None
    assert out["input_device"] is None


def test_missing_keys_env_fallback():
    """An empty rt dict falls back entirely to env-derived Settings."""
    out = state_mod.resolve_input_config({}, FakeSettings())
    assert out == {
        "input_source": "CAMERA",
        "input_url": None,
        "input_device": "/dev/video0",
        "input_width": 640,
        "input_height": 480,
    }


def test_missing_keys_env_fallback_stream():
    """When env baseline is STREAM, the URL fallback comes from VIDEO_PATH."""
    out = state_mod.resolve_input_config(
        {}, FakeSettings(INPUT_SOURCE="STREAM", VIDEO_PATH="rtsp://env/live"))
    assert out["input_source"] == "STREAM"
    assert out["input_url"] == "rtsp://env/live"
    assert out["input_device"] is None


def test_invalid_input_source_falls_back_to_env():
    """An out-of-set input_source value falls back to env INPUT_SOURCE."""
    out = state_mod.resolve_input_config(
        {"input_source": "WIFI"}, FakeSettings(INPUT_SOURCE="CAMERA"))
    assert out["input_source"] == "CAMERA"


def test_nonstring_input_source_falls_back_to_env():
    """A non-string input_source (int/bool/None) falls back to env."""
    for bad in (123, True, False):
        out = state_mod.resolve_input_config(
            {"input_source": bad}, FakeSettings(INPUT_SOURCE="FILE"))
        assert out["input_source"] == "FILE"


def test_invalid_input_width_bool_falls_back():
    """bool is a subclass of int but must be rejected for input_width."""
    out = state_mod.resolve_input_config(
        {"input_width": True}, FakeSettings(INPUT_WIDTH=640))
    assert out["input_width"] == 640


def test_invalid_input_width_zero_negative_falls_back():
    """Non-positive input_width falls back to env."""
    for bad in (0, -1, -100):
        out = state_mod.resolve_input_config(
            {"input_width": bad}, FakeSettings(INPUT_WIDTH=640))
        assert out["input_width"] == 640


def test_invalid_input_height_bool_falls_back():
    """bool must be rejected for input_height too."""
    out = state_mod.resolve_input_config(
        {"input_height": False}, FakeSettings(INPUT_HEIGHT=480))
    assert out["input_height"] == 480


def test_invalid_input_height_zero_negative_falls_back():
    """Non-positive input_height falls back to env."""
    for bad in (0, -1):
        out = state_mod.resolve_input_config(
            {"input_height": bad}, FakeSettings(INPUT_HEIGHT=480))
        assert out["input_height"] == 480


def test_stream_without_input_url_falls_back_to_video_path():
    """STREAM with no/empty input_url falls back to env VIDEO_PATH."""
    for rt in ({"input_source": "STREAM"},
               {"input_source": "STREAM", "input_url": ""},
               {"input_source": "STREAM", "input_url": "   "}):
        out = state_mod.resolve_input_config(
            rt, FakeSettings(VIDEO_PATH="rtsp://fallback/live"))
        assert out["input_source"] == "STREAM"
        assert out["input_url"] == "rtsp://fallback/live"


def test_stream_nonstring_input_url_falls_back():
    """STREAM with a non-string input_url falls back to env VIDEO_PATH."""
    out = state_mod.resolve_input_config(
        {"input_source": "STREAM", "input_url": 123},
        FakeSettings(VIDEO_PATH="rtsp://fallback/live"))
    assert out["input_url"] == "rtsp://fallback/live"


def test_camera_without_input_device_falls_back_to_video_path():
    """CAMERA with no/empty input_device falls back to env VIDEO_PATH."""
    for rt in ({"input_source": "CAMERA"},
               {"input_source": "CAMERA", "input_device": ""},
               {"input_source": "CAMERA", "input_device": "  "}):
        out = state_mod.resolve_input_config(
            rt, FakeSettings(VIDEO_PATH="/dev/video9"))
        assert out["input_source"] == "CAMERA"
        assert out["input_device"] == "/dev/video9"


def test_camera_nonstring_input_device_falls_back():
    """CAMERA with a non-string input_device falls back to env VIDEO_PATH."""
    out = state_mod.resolve_input_config(
        {"input_source": "CAMERA", "input_device": 99},
        FakeSettings(VIDEO_PATH="/dev/video9"))
    assert out["input_device"] == "/dev/video9"


def test_non_dict_rt_env_fallback():
    """A non-dict rt (e.g. None from a corrupt file) falls back to env."""
    out = state_mod.resolve_input_config(None, FakeSettings())
    assert out["input_source"] == "CAMERA"
    assert out["input_width"] == 640
    assert out["input_height"] == 480


def test_never_raises():
    """resolve_input_config must never raise — fail-open is the contract."""
    # Combine every invalid shape; expect a fully-populated dict back.
    rt = {
        "input_source": 1.5,
        "input_url": None,
        "input_device": False,
        "input_width": "big",
        "input_height": -3,
    }
    out = state_mod.resolve_input_config(rt, FakeSettings())
    assert set(out.keys()) == {
        "input_source", "input_url", "input_device",
        "input_width", "input_height",
    }
    assert out["input_source"] == "CAMERA"
    assert out["input_width"] == 640
    assert out["input_height"] == 480