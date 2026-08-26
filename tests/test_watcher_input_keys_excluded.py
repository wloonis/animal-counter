"""
BL-93 guard: the hot-reload watcher must NOT pick up input keys.

``RuntimeSettingsWatcher._build_pending`` only processes the hot-reload
counting/visual keys (draw_tracking, box_tracking, centroid_tracking,
draw_mask_zones, offset_counting_line, counting_line_orientation,
counting_class_ids, mask_zones). The BL-93 input keys
(input_source/input_url/input_device/input_width/input_height) +
``output_fps`` are STARTUP-ONLY — a camera↔drone switch = pod restart,
never a hot-swap. This test asserts ``_build_pending`` never returns them,
even when present in ``runtime-settings.json``.

No real watcher thread is started — ``_build_pending`` is called directly
on an instance with a stubbed ``load_runtime_settings``.
"""

import os
import sys
import threading
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
# Minimal fake SharedState (what the watcher reads on the instance).
# ---------------------------------------------------------------------------
class _FakeSharedState:
    def __init__(self):
        self.class_names = ["pig", "sheep"]
        self.default_counting_class = "pig"


def _make_watcher():
    stop = threading.Event()
    w = state_mod.RuntimeSettingsWatcher(_FakeSharedState(), stop)
    return w


# The input keys that must NEVER appear in the hot-reload pending payload.
_INPUT_KEYS = (
    "input_source", "input_url", "input_device",
    "input_width", "input_height", "output_fps",
)


def test_build_pending_excludes_input_keys(monkeypatch):
    """Even when runtime-settings.json carries the BL-93 input keys + a full
    set of valid hot-reload keys, _build_pending returns ONLY the hot-reload
    keys — the input keys are dropped (startup-only by design)."""
    rt_with_everything = {
        # hot-reload keys (must be picked up)
        "draw_tracking": True,
        "box_tracking": False,
        "centroid_tracking": True,
        "draw_mask_zones": False,
        "offset_counting_line": 12,
        "counting_line_orientation": "vertical",
        "counting_class_ids": [0],
        "mask_zones": [],
        # BL-93 startup-only input keys (must be DROPPED)
        "input_source": "STREAM",
        "input_url": "rtsp://drone:8554/live",
        "input_device": "/dev/video0",
        "input_width": 1280,
        "input_height": 720,
        "output_fps": 15,
    }
    monkeypatch.setattr(state_mod, "load_runtime_settings",
                        lambda: dict(rt_with_everything))
    w = _make_watcher()
    pending = w._build_pending()
    assert pending is not None, "expected a non-empty payload (hot-reload keys present)"
    # None of the BL-93 input keys may leak into the hot-reload payload.
    for k in _INPUT_KEYS:
        assert k not in pending, f"input key {k!r} must NOT be hot-reloaded"
    # And the expected hot-reload keys ARE present.
    assert "draw_tracking" in pending
    assert "box_tracking" in pending
    assert "offset_counting_line" in pending


def test_build_pending_input_only_keys_yield_hot_payload_none(monkeypatch):
    """A runtime-settings.json with ONLY the BL-93 input keys (no hot-reload
    toggles) still produces a non-None payload (counting_class_ids always
    resolves), but that payload contains zero input keys."""
    monkeypatch.setattr(state_mod, "load_runtime_settings", lambda: {
        "input_source": "CAMERA",
        "input_device": "/dev/video0",
        "input_width": 640,
        "input_height": 480,
        "output_fps": 30,
    })
    w = _make_watcher()
    pending = w._build_pending()
    # counting_class_ids always resolves (never empty) → payload is a dict.
    assert isinstance(pending, dict)
    for k in _INPUT_KEYS:
        assert k not in pending