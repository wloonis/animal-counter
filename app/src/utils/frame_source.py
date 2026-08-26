# SPDX-License-Identifier: GPL-3.0-or-later
# animal-counter — pig counter on Jetson Orin Nano (OC-SORT + anti-ID-switch guards).
# Copyright (C) 2026  LOONIS Wennaël
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
FrameSource module for the pig counting application.

This module provides a unified interface for frame sources (CAMERA, STREAM, or
FILE).

BL-93 input/output decoupling:
  - CAMERA: ``CAP_PROP_FRAME_WIDTH/HEIGHT`` are set to ``input_width`` /
    ``input_height`` (per-model capture resolution), NOT ``settings.OUTPUT_*``
    (the recording resolution stays ``OUTPUT_*`` via the DisplayThread writer
    + the PR #129 resize — decoupled). A ``CAP_PROP_BUFFERSIZE=1`` hint +
    bounded grab-discard keeps InferThread on the latest frame.
  - STREAM (new): RTSP drone source (``cv2.VideoCapture(rtsp_url)``, no V4L2).
    ``CAP_PROP_BUFFERSIZE=1`` + bounded grab-discard; width/height are NOT
    forced (RTSP negotiates native 720p). A reconnect-on-fail flag lets the
    drone be off at startup / drop mid-stream — ``read()`` returns
    ``(False, None)`` and transparently reattempts the RTSP open so InferThread
    can idle + resume without a pod restart.
  - FILE: unchanged (plain ``cv2.VideoCapture(source)``, no buffer, no
    discard — byte-identical validation path).
"""

import time

import cv2
from settings import Settings

# Load settings
settings = Settings()

# Bounded grab-discard cap for CAMERA + STREAM. Grabs at most N frames per
# ``read()`` call (keeping only the last), so InferThread always processes the
# latest available frame without an unbounded grab loop starving the queue.
# FILE is excluded entirely (validation must process every frame sequentially).
_GRAB_DISCARD_MAX = 5

# Brief backoff between RTSP reconnect attempts (seconds). Avoids a tight
# reconnect loop burning CPU while the drone is off.
_STREAM_RECONNECT_BACKOFF = 1.0


class FrameSource:
    """
    Unified interface for frame sources (CAMERA, STREAM, or FILE).

    Attributes:
        cap (cv2.VideoCapture): OpenCV video capture object.
        source (str): Source path (camera device, RTSP url, or video file).
        input_type (str): Type of input (CAMERA, STREAM, or FILE).
    """

    def __init__(self, source, input_type="CAMERA", input_width=None,
                 input_height=None, input_url=None):
        """
        Initialize the frame source.

        Args:
            source (str): Source path (camera device, RTSP url, or video file).
            input_type (str): Type of input (CAMERA, STREAM, or FILE).
            input_width (int, optional): Capture width for CAMERA
                (per-model ``input_width``; falls back to
                ``settings.INPUT_WIDTH`` then ``settings.OUTPUT_WIDTH`` for
                retrocompat). Ignored for STREAM/FILE.
            input_height (int, optional): Capture height for CAMERA
                (per-model ``input_height``; falls back to
                ``settings.INPUT_HEIGHT`` then ``settings.OUTPUT_HEIGHT``).
                Ignored for STREAM/FILE.
            input_url (str, optional): RTSP URL for STREAM. When ``None`` and
                ``input_type=="STREAM"``, the ``source`` arg is used as the
                RTSP URL (back-compat with the ``FrameSource(source, type)``
                two-arg call signature).
        """
        self.source = source
        self.input_type = input_type

        # CAMERA capture resolution: per-model input_* (decoupled from the
        # recording OUTPUT_* resolution). Fallback chain: arg → env INPUT_* →
        # env OUTPUT_* (pre-BL-93 behavior, byte-identical retrocompat).
        cap_width = input_width if input_width is not None \
            else getattr(settings, "INPUT_WIDTH", settings.OUTPUT_WIDTH)
        cap_height = input_height if input_height is not None \
            else getattr(settings, "INPUT_HEIGHT", settings.OUTPUT_HEIGHT)

        # STREAM reconnect state. ``self._stream_disconnected`` is set when the
        # RTSP open fails (drone not streaming yet) OR a later read fails (drone
        # dropped mid-stream); ``read()`` then reattempts the RTSP open and
        # returns ``(False, None)`` until it succeeds. CAMERA/FILE keep this
        # flag False (their open failures raise, matching pre-BL-93 behavior).
        self._stream_disconnected = False
        # The RTSP URL to (re)open on reconnect. For STREAM, prefer input_url,
        # else fall back to the source arg (two-arg call signature).
        self.rtsp_url = None

        if input_type == "CAMERA":
            self.cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'mp4v'))
            # BL-93: capture res is the per-model input_* (NOT OUTPUT_*).
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, cap_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cap_height)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            # Low-latency grab-discard buffer (CAMERA only — FILE excluded).
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        elif input_type == "STREAM":
            self.rtsp_url = input_url if input_url is not None else source
            self.cap = cv2.VideoCapture(self.rtsp_url)
            # Low-latency grab-discard buffer. Do NOT force FRAME_WIDTH/HEIGHT
            # — RTSP negotiates the native stream resolution (e.g. 720p).
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        else:
            # FILE: plain VideoCapture, no buffer hint, no grab-discard
            # (byte-identical validation path — every frame processed).
            self.cap = cv2.VideoCapture(source)

        # CAMERA/FILE: a failed open is fatal (raise, pre-BL-93 behavior).
        # STREAM: a failed open is NOT fatal — the drone may not be streaming
        # yet; set the reconnect flag so read() retries transparently.
        if input_type == "STREAM":
            if not self.cap.isOpened():
                # Drone may not be streaming yet — set the reconnect flag so
                # read() retries transparently (no fatal raise). InferThread
                # idles on the (False, None) returns until the drone starts.
                self._stream_disconnected = True
        else:
            if not self.cap.isOpened():
                raise ValueError(f"Error opening video source: {source}")

    def _reopen_stream(self):
        """Reopen the RTSP stream (STREAM reconnect, best-effort)."""
        try:
            self.cap.release()
        except Exception:
            pass
        try:
            self.cap = cv2.VideoCapture(self.rtsp_url)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if self.cap.isOpened():
                self._stream_disconnected = False
                return True
        except Exception:
            pass
        return False

    def read(self):
        """
        Read a frame from the source.

        For CAMERA + STREAM: bounded grab-discard — loops ``self.cap.grab()``
        up to ``_GRAB_DISCARD_MAX`` times while it returns True, then
        ``retrieve()``s the last grabbed frame. Drops stale frames so InferThread
        always processes the latest. For FILE: a single ``self.cap.read()``
        (byte-identical, no drops).

        For STREAM: when a grab/read fails (drone off), reattempts the RTSP
        open and returns ``(False, None)`` while disconnected so InferThread
        idles; when the drone restarts the reconnect succeeds and frames
        resume (transparent — InferThread keeps calling read()).

        Returns:
            tuple: Ret (bool), frame (numpy.ndarray or None).
        """
        # STREAM reconnect: if the previous open (or a prior read) failed,
        # reattemp the RTSP open before trying to read. Return (False, None)
        # while still disconnected (InferThread idles + backoff).
        if self.input_type == "STREAM" and self._stream_disconnected:
            if not self._reopen_stream():
                time.sleep(_STREAM_RECONNECT_BACKOFF)
                return False, None

        if self.input_type in ("CAMERA", "STREAM"):
            # Bounded grab-discard: grab up to N frames, keep only the last.
            grabbed = False
            for _ in range(_GRAB_DISCARD_MAX):
                if not self.cap.grab():
                    break
                grabbed = True
            if not grabbed:
                # No frame grabbed. CAMERA → fatal signal (ret=False, InferThread
                # breaks — hardware disconnect). STREAM → mark disconnected,
                # reconnect next read().
                if self.input_type == "STREAM":
                    self._stream_disconnected = True
                    time.sleep(_STREAM_RECONNECT_BACKOFF)
                return False, None
            ret, frame = self.cap.retrieve()
            if not ret:
                # retrieve() failed after a successful grab — treat like a
                # read failure (STREAM → reconnect path; CAMERA → fatal).
                if self.input_type == "STREAM":
                    self._stream_disconnected = True
                    time.sleep(_STREAM_RECONNECT_BACKOFF)
                return False, None
            return ret, frame

        # FILE: single read(), no grab-discard (byte-identical validation).
        ret, frame = self.cap.read()
        return ret, frame

    def release(self):
        """Release the video capture object."""
        self.cap.release()

    def get_fps(self):
        """
        Get the FPS of the video source.

        Returns:
            float: FPS of the video source.
        """
        return self.cap.get(cv2.CAP_PROP_FPS)