"""
BL-70 (issue #74) unit test for ``DisplayThread._finalize_recording``.

The video clip filename must carry the **per-video delta** (pigs counted
*during* that recording) instead of the global cumulative
``counter_to_right``. This is verified by driving the real
``_finalize_recording`` method on a real ``DisplayThread`` instance and
checking the renamed file's ``#{delta}`` token for three cases:

  * positive delta (start 5 -> end 12 -> ``#7``)
  * zero delta     (start 5 -> end  5 -> ``#0``)
  * negative delta (start 5 -> end  4 -> ``#-1``)

It also asserts the global ``counter_to_right`` is **not** mutated by
finalize (the delta is computed read-only; the global counter and its
reset logic are untouched — BL-70 out of scope).

The Jetson-only GPU/TensorRT deps (``pycuda``, ``tensorrt``, ``torch``,
``trackers``, ``supervision``, ``core.inference``) are stubbed in
``sys.modules`` so ``app/src/main.py`` imports in a plain-CPython CI
environment; only stdlib + ``numpy``/``cv2`` (already required by the
counting tests) are pulled in for real. ``DisplayThread`` and its
``_finalize_recording`` method are exercised unmodified — this is the
real production finalize path, not a reimplementation.
"""

import glob
import os
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Stub heavy Jetson-only modules so main.py is importable without GPU deps.
# We register stubs BEFORE importing main.py. core.inference / trackers /
# supervision / pycuda / tensorrt are the only heavy top-level imports in
# main.py; everything else (numpy, cv2, settings, core.counting,
# core.tracking, core.history, ui.rendering, utils.*) is light and real.
# ---------------------------------------------------------------------------

_STUBS = {
    "pycuda": types.ModuleType("pycuda"),
    "pycuda.driver": types.ModuleType("pycuda.driver"),
    "tensorrt": types.ModuleType("tensorrt"),
    "trackers": types.ModuleType("trackers"),
    "trackers.utils": types.ModuleType("trackers.utils"),
    "trackers.utils.iou": types.ModuleType("trackers.utils.iou"),
    "supervision": types.ModuleType("supervision"),
    "core.inference": types.ModuleType("core.inference"),
}
# trackers exposes OCSORTTracker; trackers.utils.iou exposes the IoU metrics.
_STUBS["trackers"].OCSORTTracker = type("OCSORTTracker", (), {})
for _name in ("IoU", "GIoU", "DIoU", "CIoU", "BIoU"):
    setattr(_STUBS["trackers.utils.iou"], _name, type(_name, (), {}))
# supervision exposes Detections.
_STUBS["supervision"].Detections = type("Detections", (), {})
# core.inference exposes Inference.
_STUBS["core.inference"].Inference = type("Inference", (), {})
for _n, _m in _STUBS.items():
    sys.modules.setdefault(_n, _m)

# Make app/src importable (settings, core, ui, utils live there).
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_SRC = os.path.join(os.path.dirname(_HERE), "app", "src")
if _APP_SRC not in sys.path:
    sys.path.insert(0, _APP_SRC)

import main as main_mod  # noqa: E402  (import after stubs + path setup)


# ---------------------------------------------------------------------------
# Fakes.
# ---------------------------------------------------------------------------

class _FakeVideoWriter:
    """Stand-in for cv2.VideoWriter — isOpened() True, release() no-op."""

    def __init__(self):
        self.released = False

    def isOpened(self):
        return not self.released

    def release(self):
        self.released = True


def _make_display_thread():
    """Build a DisplayThread without starting it (no GPU / cv2 window)."""
    dt = main_mod.DisplayThread.__new__(main_mod.DisplayThread)
    # __new__ skips __init__; set only the attributes _finalize_recording
    # touches, mirroring DisplayThread.__init__'s field set.
    dt.video_writer = None
    dt.filename = None
    dt.record_start_time = None
    dt.record_duration = None
    dt.record_start_count = None
    return dt


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------

@pytest.fixture
def finalize_env(tmp_path):
    """Set up an isolated recording env on the module-level shared_state."""
    ss = main_mod.shared_state
    # Snapshot so we can restore (shared_state is a module singleton).
    saved = {
        "recording": ss.recording,
        "counter_to_right": ss.counter_to_right,
        "status": ss.status,
        "reset": ss.reset,
    }
    saved_output = main_mod.settings.OUTPUT_VIDEO_PATH

    out_dir = tmp_path
    main_mod.settings.OUTPUT_VIDEO_PATH = str(out_dir)
    ss.recording = True
    ss.status = 1
    ss.reset = False

    yield ss, out_dir

    # Restore.
    ss.recording = saved["recording"]
    ss.counter_to_right = saved["counter_to_right"]
    ss.status = saved["status"]
    ss.reset = saved["reset"]
    main_mod.settings.OUTPUT_VIDEO_PATH = saved_output


def _start_clip(finalize_env, start_count):
    """Create a DisplayThread mid-recording with a tmp clip on disk."""
    ss, out_dir = finalize_env
    ss.counter_to_right = start_count  # global counter at recording start
    dt = _make_display_thread()
    dt.record_start_count = start_count
    dt.video_writer = _FakeVideoWriter()
    # The tmp file (pre-rename) must live in the same filesystem as the
    # output dir so os.rename works.
    tmp_clip = os.path.join(out_dir, "tmp-counting-clip.mp4")
    with open(tmp_clip, "wb") as fh:
        fh.write(b"\x00\x00\x00\x18 ftyp")  # tiny placeholder bytes
    dt.filename = tmp_clip
    return dt


# ---------------------------------------------------------------------------
# Tests: per-video delta in the renamed filename.
# ---------------------------------------------------------------------------

def test_positive_delta_in_filename(finalize_env):
    """start 5 -> end 12: clip filename carries #7."""
    ss, out_dir = finalize_env
    dt = _start_clip(finalize_env, start_count=5)
    ss.counter_to_right = 12  # 7 line crossings during the recording

    dt._finalize_recording()

    matches = glob.glob(os.path.join(out_dir, "tocompress-counting-*-#7.mp4"))
    assert len(matches) == 1, f"expected one #7 clip, got {matches}"
    # The tmp file was renamed away.
    assert not os.path.exists(dt.filename)
    # Global counter untouched by finalize.
    assert ss.counter_to_right == 12
    # Snapshot cleared (no leak into next recording).
    assert dt.record_start_count is None


def test_zero_delta_in_filename(finalize_env):
    """start 5 -> end 5: clip filename carries #0."""
    ss, out_dir = finalize_env
    dt = _start_clip(finalize_env, start_count=5)
    ss.counter_to_right = 5  # no crossings during the recording

    dt._finalize_recording()

    matches = glob.glob(os.path.join(out_dir, "tocompress-counting-*-#0.mp4"))
    assert len(matches) == 1, f"expected one #0 clip, got {matches}"
    assert ss.counter_to_right == 5
    assert dt.record_start_count is None


def test_negative_delta_in_filename(finalize_env):
    """start 5 -> end 4 (a LEFT crossing decremented the global counter):
    clip filename carries #-1 (raw delta, no clamping)."""
    ss, out_dir = finalize_env
    dt = _start_clip(finalize_env, start_count=5)
    ss.counter_to_right = 4  # one left-boundary crossing during the recording

    dt._finalize_recording()

    matches = glob.glob(os.path.join(out_dir, "tocompress-counting-*-#-1.mp4"))
    assert len(matches) == 1, f"expected one #-1 clip, got {matches}"
    assert ss.counter_to_right == 4
    assert dt.record_start_count is None


def test_missing_snapshot_falls_back_to_zero(finalize_env):
    """If record_start_count is None (finalize from a path that skipped
    recording-start), the filename stays well-formed with #0 and the
    global counter is still untouched."""
    ss, out_dir = finalize_env
    dt = _start_clip(finalize_env, start_count=5)
    dt.record_start_count = None  # simulate the missing-snapshot exit path
    ss.counter_to_right = 42  # arbitrary; must NOT appear in the filename

    dt._finalize_recording()

    matches = glob.glob(os.path.join(out_dir, "tocompress-counting-*-#0.mp4"))
    assert len(matches) == 1, f"expected one #0 clip (fallback), got {matches}"
    # The fallback must NOT leak the global cumulative value.
    bad = glob.glob(os.path.join(out_dir, "tocompress-counting-*-#42.mp4"))
    assert bad == []
    assert ss.counter_to_right == 42
    assert dt.record_start_count is None


def test_finalize_does_not_mutate_global_counter(finalize_env):
    """The delta is computed read-only from counter_to_right; finalize must
    never write to it (BL-70 out-of-scope: global counter/reset untouched)."""
    ss, out_dir = finalize_env
    dt = _start_clip(finalize_env, start_count=10)
    ss.counter_to_right = 25
    before = ss.counter_to_right

    dt._finalize_recording()

    assert ss.counter_to_right == before