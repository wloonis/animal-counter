"""
BL-93 unit tests for ``state.resolve_output_fps`` (stdlib only).

``resolve_output_fps`` returns ``models.<active>.output_fps`` (positive
int, reject bool) when present and valid, else ``settings.FPS_OUTPUT``
(env=30). It must **never raise** (fail-open → env fallback).

Mirrors ``tests/test_resolve_input_config.py`` style.
"""

import os
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Stub heavy Jetson-only modules so state.py is importable without GPU deps.
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

# Make app/src importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_SRC = os.path.join(os.path.dirname(_HERE), "app", "src")
if _APP_SRC not in sys.path:
    sys.path.insert(0, _APP_SRC)

import state as state_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal fake Settings.
# ---------------------------------------------------------------------------
class FakeSettings:
    def __init__(self, **overrides):
        self.FPS_OUTPUT = 30
        for k, v in overrides.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# resolve_output_fps
# ---------------------------------------------------------------------------
def test_per_model_value_used():
    """A valid positive-int output_fps is returned as-is."""
    out = state_mod.resolve_output_fps({"output_fps": 15}, FakeSettings())
    assert out == 15


def test_absent_falls_back_to_fps_output():
    """When output_fps is missing, env FPS_OUTPUT is used."""
    out = state_mod.resolve_output_fps({}, FakeSettings(FPS_OUTPUT=30))
    assert out == 30


def test_absent_default_fps_output():
    """Default FakeSettings has FPS_OUTPUT=30."""
    out = state_mod.resolve_output_fps({}, FakeSettings())
    assert out == 30


def test_bool_rejected():
    """bool is a subclass of int but must be rejected → env fallback."""
    out = state_mod.resolve_output_fps(
        {"output_fps": True}, FakeSettings(FPS_OUTPUT=30))
    assert out == 30


def test_zero_rejected():
    out = state_mod.resolve_output_fps(
        {"output_fps": 0}, FakeSettings(FPS_OUTPUT=30))
    assert out == 30


def test_negative_rejected():
    out = state_mod.resolve_output_fps(
        {"output_fps": -5}, FakeSettings(FPS_OUTPUT=30))
    assert out == 30


def test_non_int_rejected():
    """A float/string output_fps falls back to env."""
    for bad in (15.0, "15", None, [15]):
        out = state_mod.resolve_output_fps(
            {"output_fps": bad}, FakeSettings(FPS_OUTPUT=30))
        assert out == 30


def test_non_dict_rt_falls_back():
    out = state_mod.resolve_output_fps(None, FakeSettings(FPS_OUTPUT=30))
    assert out == 30


def test_never_raises():
    out = state_mod.resolve_output_fps(
        {"output_fps": object()}, FakeSettings(FPS_OUTPUT=30))
    assert out == 30