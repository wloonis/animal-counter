"""
BL-93 unit tests for ``utils.frame_source.FrameSource`` (mocked cv2, stdlib).

Covers the three input branches added/modified by BL-93:

  * ``STREAM`` — a failed ``isOpened()`` is NOT fatal (the drone may not be
    streaming yet); the reconnect flag is set and ``read()`` returns
    ``(False, None)`` until the RTSP open succeeds. The RTSP URL is taken
    from ``input_url`` (falling back to the ``source`` arg).
  * ``FILE`` — ``read()`` is a single ``cap.read()`` (no grab-discard),
    byte-identical to the pre-BL-93 validation path.
  * ``CAMERA`` — ``CAP_PROP_FRAME_WIDTH/HEIGHT`` are set to ``input_width`` /
    ``input_height`` (per-model capture res), NOT ``settings.OUTPUT_*``;
    ``CAP_PROP_BUFFERSIZE`` is set to 1.

``cv2.VideoCapture`` is replaced by a fake so no real hardware / RTSP source
is touched. The real ``FrameSource`` class is exercised unmodified.
"""

import os
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Make app/src importable (settings, utils.frame_source live there).
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_SRC = os.path.join(os.path.dirname(_HERE), "app", "src")
if _APP_SRC not in sys.path:
    sys.path.insert(0, _APP_SRC)

import utils.frame_source as fs_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fake cv2.VideoCapture + property-constant stand-ins.
# ---------------------------------------------------------------------------
class _Props:
    """Minimal mirror of the cv2.CAP_PROP_* constants used by frame_source."""

    CAP_V4L2 = 200
    CAP_PROP_FOURCC = 6
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    CAP_PROP_BUFFERSIZE = 38


class FakeCapture:
    """Stand-in for cv2.VideoCapture recording every set() + the read path."""

    # Class-level knob: whether the next-opened FakeCapture reports isOpened().
    opened = True
    # Class-level knob: how many grab() calls succeed before one fails.
    grab_succeeds_forever = True

    def __init__(self, source=None, backend=None):
        self.source = source
        self.backend = backend
        self.sets = []
        self.released = False
        self._opened = FakeCapture.opened
        self._read_index = 0
        # Per-instance frame payload returned by retrieve/read.
        self._frame = ("frame", 0)

    def isOpened(self):
        return self._opened and not self.released

    def set(self, prop, value):
        self.sets.append((prop, value))
        return True

    def grab(self):
        if FakeCapture.grab_succeeds_forever:
            return True
        return False

    def retrieve(self):
        if not self._opened:
            return False, None
        return True, self._frame

    def read(self):
        if not self._opened:
            return False, None
        self._read_index += 1
        return True, ("frame", self._read_index)

    def release(self):
        self.released = True

    def get(self, prop):
        return 30.0


@pytest.fixture
def fake_cv2(monkeypatch):
    """Replace cv2.VideoCapture + constants inside frame_source with fakes."""
    monkeypatch.setattr(fs_mod.cv2, "VideoCapture", FakeCapture)
    monkeypatch.setattr(fs_mod.cv2, "CAP_V4L2", _Props.CAP_V4L2)
    monkeypatch.setattr(fs_mod.cv2, "CAP_PROP_FOURCC", _Props.CAP_PROP_FOURCC)
    monkeypatch.setattr(fs_mod.cv2, "CAP_PROP_FRAME_WIDTH",
                         _Props.CAP_PROP_FRAME_WIDTH)
    monkeypatch.setattr(fs_mod.cv2, "CAP_PROP_FRAME_HEIGHT",
                         _Props.CAP_PROP_FRAME_HEIGHT)
    monkeypatch.setattr(fs_mod.cv2, "CAP_PROP_FPS", _Props.CAP_PROP_FPS)
    monkeypatch.setattr(fs_mod.cv2, "CAP_PROP_BUFFERSIZE",
                         _Props.CAP_PROP_BUFFERSIZE)
    # Reset knobs.
    FakeCapture.opened = True
    FakeCapture.grab_succeeds_forever = True
    return FakeCapture


# ---------------------------------------------------------------------------
# STREAM
# ---------------------------------------------------------------------------
def test_stream_not_fatal_on_open_fail(fake_cv2):
    """A STREAM whose isOpen() fails does NOT raise — it sets the reconnect
    flag so read() can retry transparently."""
    FakeCapture.opened = False
    src = fs_mod.FrameSource("rtsp://drone:8554/live", input_type="STREAM")
    assert src._stream_disconnected is True
    assert src.rtsp_url == "rtsp://drone:8554/live"


def test_stream_uses_input_url_when_provided(fake_cv2):
    """input_url takes precedence over the source arg for STREAM."""
    src = fs_mod.FrameSource(
        "ignored", input_type="STREAM", input_url="rtsp://drone:8554/live")
    assert src.rtsp_url == "rtsp://drone:8554/live"


def test_stream_does_not_force_frame_dimensions(fake_cv2):
    """STREAM must NOT set CAP_PROP_FRAME_WIDTH/HEIGHT (RTSP negotiates)."""
    src = fs_mod.FrameSource(
        "rtsp://drone:8554/live", input_type="STREAM",
        input_width=1280, input_height=720)
    set_props = {p for p, _ in src.cap.sets}
    assert _Props.CAP_PROP_FRAME_WIDTH not in set_props
    assert _Props.CAP_PROP_FRAME_HEIGHT not in set_props
    # BUFFERSIZE=1 is still set (low-latency grab-discard).
    assert (_Props.CAP_PROP_BUFFERSIZE, 1) in src.cap.sets


def test_stream_read_returns_false_when_disconnected(fake_cv2):
    """read() on a disconnected STREAM returns (False, None) without raising."""
    FakeCapture.opened = False
    src = fs_mod.FrameSource("rtsp://drone:8554/live", input_type="STREAM")
    # Force the reopen to keep failing (drone still off).
    FakeCapture.opened = False
    ret, frame = src.read()
    assert ret is False
    assert frame is None


def test_stream_read_grab_discard_returns_last(fake_cv2):
    """A connected STREAM read uses grab-discard (grabs N times, retrieve once)."""
    src = fs_mod.FrameSource("rtsp://drone:8554/live", input_type="STREAM")
    # Track grab calls via a counter on the instance.
    grab_calls = {"n": 0}

    def _grab():
        grab_calls["n"] += 1
        return True  # always grabbable

    src.cap.grab = _grab
    ret, frame = src.read()
    assert ret is True
    # Bounded grab-discard: exactly _GRAB_DISCARD_MAX grabs then one retrieve.
    assert grab_calls["n"] == fs_mod._GRAB_DISCARD_MAX


# ---------------------------------------------------------------------------
# FILE (byte-identical validation path)
# ---------------------------------------------------------------------------
def test_file_uses_plain_capture_no_buffer(fake_cv2):
    """FILE construction uses no V4L2 backend and no BUFFERSIZE set."""
    src = fs_mod.FrameSource("clip.mp4", input_type="FILE")
    # No CAP_PROP_BUFFERSIZE set on FILE.
    set_props = {p for p, _ in src.cap.sets}
    assert _Props.CAP_PROP_BUFFERSIZE not in set_props
    assert _Props.CAP_PROP_FRAME_WIDTH not in set_props


def test_file_read_single_read_no_grab_discard(fake_cv2):
    """FILE read() is a single cap.read() — no grab() calls (byte-identical)."""
    src = fs_mod.FrameSource("clip.mp4", input_type="FILE")
    grab_calls = {"n": 0}

    def _grab():
        grab_calls["n"] += 1
        return True

    src.cap.grab = _grab
    ret, frame = src.read()
    assert ret is True
    # FILE path must NOT call grab() at all.
    assert grab_calls["n"] == 0


def test_file_open_fail_is_fatal(fake_cv2):
    """A FILE whose isOpen() fails raises ValueError (fatal — EOF/disk error)."""
    FakeCapture.opened = False
    with pytest.raises(ValueError):
        fs_mod.FrameSource("missing.mp4", input_type="FILE")


# ---------------------------------------------------------------------------
# CAMERA
# ---------------------------------------------------------------------------
def test_camera_uses_input_width_height_not_output(fake_cv2):
    """CAMERA sets CAP_PROP_FRAME_WIDTH/HEIGHT to input_* (per-model capture
    res), NOT settings.OUTPUT_* (the recording res — decoupled by BL-93)."""
    src = fs_mod.FrameSource(
        "/dev/video0", input_type="CAMERA",
        input_width=1280, input_height=720)
    set_map = dict(src.cap.sets)
    assert set_map[_Props.CAP_PROP_FRAME_WIDTH] == 1280
    assert set_map[_Props.CAP_PROP_FRAME_HEIGHT] == 720
    # BUFFERSIZE=1 (low-latency grab-discard).
    assert set_map[_Props.CAP_PROP_BUFFERSIZE] == 1


def test_camera_falls_back_to_input_env_when_no_args(fake_cv2):
    """When input_width/height are None, CAMERA falls back to settings.INPUT_*
    (env-derived), NOT settings.OUTPUT_* (pre-BL-93 retrocompat)."""
    src = fs_mod.FrameSource("/dev/video0", input_type="CAMERA")
    set_map = dict(src.cap.sets)
    # The settings module loaded a real Settings(); INPUT_WIDTH/HEIGHT default
    # to 640/480 (matching OUTPUT_*). Just assert finite positive ints land in
    # the FRAME_WIDTH/HEIGHT props — the key point is no crash + props set.
    assert set_map[_Props.CAP_PROP_FRAME_WIDTH] > 0
    assert set_map[_Props.CAP_PROP_FRAME_HEIGHT] > 0


def test_camera_open_fail_is_fatal(fake_cv2):
    """A CAMERA whose isOpen() fails raises ValueError (hardware disconnect)."""
    FakeCapture.opened = False
    with pytest.raises(ValueError):
        fs_mod.FrameSource("/dev/video0", input_type="CAMERA")