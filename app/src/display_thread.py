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
Display thread for the pig counting application.

Moved verbatim from `main.py` (`class DisplayThread(threading.Thread)`,
main.py:225-619). It owns the recording/learning/auto-stop lifecycle (BL-62
stop detection, BL-69/70/71 recording start/finalize, learning toggle,
auto-stop) and the per-frame draw/counting orchestration.

The thread reads the process-wide `shared_state`/`logger` singletons from the
`state` leaf module and `settings` from the `settings` module (same objects
`main.py` used as module globals — no behavior change). No logic changes: the
method bodies are copied byte-for-byte; only French comments are translated
to English (BL-29 Task 7).
"""

import threading
import cv2
import time
import datetime
import logging
import os
import numpy as np
from queue import Queue

from core.tracking import Tracking
from core.counting import Counting
from ui.rendering import Rendering
from utils.timer_fps import TimerFps
from supervision import Detections

from state import shared_state, logger, settings

# BL-76: Shared-file IPC sentinel written by the companion (POST /api/power).
# The counting app consumes it (sets arret_requested) only if its mtime is
# newer than the app process start time, to avoid a stale pre-boot sentinel
# triggering an immediate poweroff loop after a crash/reboot. BL-79 split:
# control files live in /conf (hostPath /data/orin/conf), separate from data
# files in /files (hostPath /data/orin/files).
POWER_SENTINEL_PATH = "/conf/.arret_requested"

class DisplayThread(threading.Thread):
    """
    Thread for handling display and counting.

    Attributes:
        frame_queue (Queue): Queue for frame processing.
        yolo (Inference): YOLO TensorRT model.
        sort_tracker (Tracker): Norfair tracker.
        tracking (Tracking): Tracking module.
        counting (Counting): Counting module.
        rendering (Rendering): Rendering module.
        frame_counter (int): Current frame counter.
        timer (TimerFps): Timer for FPS calculation.
        video_writer (cv2.VideoWriter): Video writer for recording.
        filename (str): Output video filename.
    """

    def __init__(self, frame_queue: Queue, sort_tracker, tracking: Tracking, counting: Counting, rendering: Rendering, stop_event, input_type="CAMERA"):
        """
        Initialize the display thread.

        Args:
            frame_queue (Queue): Queue for frame processing.
            yolo (Inference): YOLO TensorRT model.
            sort_tracker (Tracker): Norfair tracker.
            tracking (Tracking): Tracking module.
            counting (Counting): Counting module.
            rendering (Rendering): Rendering module.
            input_type (str): Type of input (CAMERA or FILE).
        """
        super().__init__()
        self.frame_queue = frame_queue
        self.sort_tracker = sort_tracker
        self.tracking = tracking
        self.counting = counting
        self.rendering = rendering
        self.input_type = input_type
        self.frame_counter = 0
        self.timer = TimerFps()
        self.video_writer = None
        self.filename = None
        # BL-69: recording wall-clock window (1st pig -> release), exposed as
        # the video duration in /api/history (distinct from session duration).
        self.record_start_time = None
        self.record_duration = None
        # BL-70 (#74): per-video delta snapshot — captured at recording start,
        # consumed in _finalize_recording to put the per-video count (not the
        # global cumulative counter) in the clip filename.
        self.record_start_count = None
        # BL-71: recording START timestamp stem (YYYYMMDD-HHMMSS), captured
        # once at recording start and reused at finalize so the tmp filename,
        # the tocompress/counting output, and the video_id all share the same
        # {ts} (the running row and the ended entry must match).
        self.record_start_ts = None
        self.window_name = "Counter"
        self.x_offset = self.y_offset = 30
        self.stop_event = stop_event

    def _finalize_recording(self):
        """Release the video writer and rename tmp-counting to tocompress-counting.

        Idempotent: safe to call multiple times (in-loop, post-loop, stop()).
        The guard (writer is None / not isOpened / not recording) ensures no
        double-release or double-rename.
        """
        if self.video_writer is None or not self.video_writer.isOpened() or not shared_state.recording:
            return
        self.video_writer.release()
        self.video_writer = None
        # Capture the recording (video) duration before resetting state.
        if self.record_start_time is not None:
            self.record_duration = time.monotonic() - self.record_start_time
        # BL-70 (issue #74): the filename carries the per-video delta (pigs
        # counted *during this recording*) instead of the global cumulative
        # counter_to_right. The snapshot was taken at recording start, before
        # the triggering frame's counting.count() ran, so the triggering pig is
        # not yet counted in the zero-point. delta = end - start. Defensive
        # guard: if the snapshot is missing (e.g. finalize from a path that
        # skipped recording-start), fall back to 0 so the filename stays well-formed.
        if self.record_start_count is not None:
            delta = shared_state.counter_to_right - self.record_start_count
        else:
            delta = 0
        # BL-71: reuse the START timestamp (captured at recording start) so the
        # output filename + video_id match the tmp filename's {ts}. The running
        # row derives its id from the tmp filename; the ended entry derives its
        # id from here - they must match. The stop time is NOT used.
        ts_stem = self.record_start_ts or time.strftime('%Y%m%d-%H%M%S')
        output_path = os.path.join(settings.OUTPUT_VIDEO_PATH, f"tocompress-counting-{ts_stem}-#{delta}.mp4")
        try:
            os.rename(self.filename, output_path)
        except OSError as e:
            logger.warning(f"Failed to rename {self.filename} -> {output_path}: {e}")
            return
        if shared_state.status == 1:
            shared_state.status = 0
        shared_state.recording = False
        shared_state.reset = False
        # BL-70: clear the per-recording snapshot so a stale zero-point can never
        # leak into the next recording (mirrors record_start_time lifecycle).
        self.record_start_count = None
        self.record_start_ts = None
        # BL-71: emit a per-video `video` JSONL line so the recorded video
        # becomes a first-class entity in the counting-history. Best-effort: a
        # history write failure must never break recording finalization.
        try:
            history = getattr(shared_state, "history_writer", None)
            if history is not None:
                video_id = f"counting-{ts_stem}"
                session_id = getattr(history, "session_id", None)
                # Store the FINAL compressed name (counting-...) in the JSONL,
                # not the transient tocompress- prefix (the cron rewrites
                # tocompress- -> counting- on disk; the API must show the
                # definitive name immediately).
                final_filename = os.path.basename(output_path).replace("tocompress-", "", 1)
                history.video(
                    video_id=video_id,
                    filename=final_filename,
                    duration=self.record_duration,
                    count_delta=delta,
                    session_id=session_id,
                )
        except Exception as e:
            logger.warning(f"Failed to emit video history line: {e}")
        logger.info(f"------->Record Stop; Value Status: {shared_state.status}: Store:{output_path}")

    def _write_snapshot(self, img):
        """BL-88: write a raw-frame JPEG snapshot to SNAPSHOT_PATH (atomic).

        Encodes `img` (the raw counting-resolution frame, before any overlay)
        to JPEG at SNAPSHOT_JPEG_QUALITY, writes the bytes to a `.tmp` file,
        then atomically `os.replace`s it onto SNAPSHOT_PATH. The companion's
        `GET /api/snapshot` (BL-88, PR #19) serves the renamed file to the
        Android mask-zone editor; the atomic rename guarantees the companion
        never observes a half-written JPEG. Best-effort: any encode/write
        failure is logged at WARNING and swallowed — never raised — so the
        display loop and counting are unaffected.
        """
        try:
            ok, buf = cv2.imencode(
                '.jpg', img,
                [cv2.IMWRITE_JPEG_QUALITY, settings.SNAPSHOT_JPEG_QUALITY]
            )
            if not ok:
                logger.warning("Snapshot encode failed (cv2.imencode returned False)")
                return
            tmp_path = settings.SNAPSHOT_PATH + ".tmp"
            with open(tmp_path, 'wb') as f:
                f.write(buf.tobytes())
            os.replace(tmp_path, settings.SNAPSHOT_PATH)
        except Exception as e:
            logger.warning(f"Snapshot write failed: {e}")

    def mouse_click(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONUP:
            self.rendering.handle_click(x, y, shared_state)

    def has_pig_high_score(self, class_ids, scores, threshold=settings.PIG_CONFIDENCE_THRESHOLD_START_VIDEO):
        # BL-78: a "high-score" detection is one whose class is in the
        # configured counting_class_ids set (legacy: class_id == 1 = pigs).
        thresh = threshold
        keep = list(shared_state.counting_class_ids)
        for i in range(len(class_ids)):
            if class_ids[i] in keep and scores[i] >= thresh:
                return True
        return False

    def run(self):
        """Run the display thread."""

        if self.input_type == "CAMERA":
            cv2.namedWindow(self.window_name, cv2.WND_PROP_FULLSCREEN)
            cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            cv2.setMouseCallback(self.window_name, self.mouse_click)

        counter = 0
        avg_t = 0.0
        sum_t = 0.0

        last_capture_time = time.time()
        # BL-88: snapshot writer — wall-clock timestamp of the last snapshot
        # write. Initialized to 0.0 so the first frame triggers an immediate
        # write (the interval gate `(now - last) >= interval` is true at t0).
        last_snapshot_time = 0.0

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("DisplayThread started")

        while not self.stop_event.is_set():
            time_start = time.time()

            # BL-76: Poll the shared-file power sentinel written by the
            # companion (POST /api/power). Consume it (best-effort) and flip
            # arret_requested ONLY if the sentinel mtime is newer than this
            # process start time. A stale pre-boot sentinel (leftover from a
            # prior crash) is removed silently without triggering a poweroff
            # (anti poweroff-loop guard). The rest of the BL-62 shutdown
            # sequence below is unchanged.
            try:
                if os.path.exists(POWER_SENTINEL_PATH):
                    sentinel_mtime = os.path.getmtime(POWER_SENTINEL_PATH)
                    if sentinel_mtime > shared_state.app_start_time:
                        try:
                            os.remove(POWER_SENTINEL_PATH)
                        except OSError:
                            pass
                        shared_state.arret_requested = True
                        logger.info("Power sentinel consumed — arret requested")
                    else:
                        # Stale pre-boot sentinel — discard without action.
                        try:
                            os.remove(POWER_SENTINEL_PATH)
                        except OSError:
                            pass
            except OSError:
                pass

            # BL-62: Clean shutdown — detect the stop request and launch the
            # shutdown sequence: (1) status=0/auto/learning off, (2)
            # _finalize_recording (flush moov atom + rename tmp->tocompress,
            # CRITICAL before poweroff), (3) stop_event.set(), (4)
            # poweroff_requested=True.
            if shared_state.arret_requested:
                shared_state.status = 0
                shared_state.auto_mode = False
                shared_state.learning_mode = False
                self._finalize_recording()
                shared_state.stop_event.set()
                shared_state.poweroff_requested = True
                break

            # BL-86: idle checkpoint for in-process hot-reload of runtime
            # settings (no pod restart). The RuntimeSettingsWatcher thread
            # (state.py) polls the mtime of /conf/runtime-settings.json and,
            # on a change, validates the file and stores the pending payload on
            # shared_state under reload_lock + sets reload_pending. This is the
            # SINGLE applier — DisplayThread.run() applies the pending settings
            # ONLY at an idle window (reload_pending AND not recording). This
            # thread owns the Counting/Rendering instances (constructor args),
            # so applying setters here avoids a mid-frame setter race. Nothing
            # ever applies mid-recording (hard constraint). The pending payload
            # was already validated by the watcher, so the guards here only
            # mirror the boot block's presence/type checks defensively.
            if shared_state.reload_pending and not shared_state.recording:
                with shared_state.reload_lock:
                    pending = shared_state.pending_settings
                    shared_state.pending_settings = None
                    shared_state.reload_pending = False
                if pending:
                    changed = []
                    # Toggles: write shared_state (read per-frame by
                    # tracking/rendering). Only apply if present/bool.
                    for key in ("draw_tracking", "box_tracking",
                                "centroid_tracking", "draw_mask_zones"):
                        if isinstance(pending.get(key), bool):
                            setattr(shared_state, key, pending[key])
                            changed.append(key)
                    # Line offset + orientation + configurable +1 direction
                    # (BL-86 idle hot-reload / BL-92): hot-swap on both the
                    # Counting and Rendering instances. Counting.update_line
                    # re-derives PLUS_DIR/MINUS_DIR from the (possibly new)
                    # orientation and +1 direction so labels don't go stale on
                    # a mid-life swap. Fall back to the current values for
                    # whichever key is absent in the pending payload (a
                    # toggle-only or line-only change must not clobber the
                    # others).
                    _off = pending.get("offset_counting_line")
                    _orient = pending.get("counting_line_orientation")
                    _dir_mode = pending.get("counting_direction_mode")
                    _dir = pending.get("counting_direction")
                    if (_off is not None or _orient is not None
                            or _dir_mode is not None or _dir is not None):
                        cur_off = self.counting.offset_counting_line
                        cur_orient = self.counting.counting_line_orientation
                        new_off = _off if isinstance(_off, int) and \
                            not isinstance(_off, bool) else cur_off
                        new_orient = _orient if isinstance(_orient, str) \
                            else cur_orient
                        # BL-92: validate counting_direction_mode / direction
                        # against the (possibly new) orientation. Reject+WARN
                        # -> keep the current value (do not crash).
                        new_mode = self.counting.counting_direction_mode
                        if isinstance(_dir_mode, str):
                            _m = _dir_mode.strip().lower()
                            if _m in ("auto", "manual"):
                                new_mode = _m
                            else:
                                logger.warning(
                                    "runtime settings: "
                                    "counting_direction_mode %r invalid "
                                    "(expected auto|manual); keeping %r",
                                    _dir_mode, new_mode)
                        new_dir = self.counting.counting_direction
                        if isinstance(_dir, str):
                            _d = _dir.strip().lower()
                            _allowed = ({"left", "right"} if new_orient
                                        == "vertical" else {"up", "down"})
                            if _d in _allowed:
                                new_dir = _d
                            else:
                                logger.warning(
                                    "runtime settings: counting_direction "
                                    "%r inconsistent with orientation %r "
                                    "(expected one of %s); keeping %r",
                                    _dir, new_orient, sorted(_allowed),
                                    new_dir)
                        # BL-92: a +1 DIRECTION change (effective PLUS_DIR)
                        # resets the counters (fresh-session semantics, like
                        # counting_class_ids): a flip invalidates already-
                        # counted crossings. A mode-only change (auto<->manual)
                        # with no effective +1 change does NOT reset. Compare
                        # the resolved PLUS_DIR before vs after update_line.
                        old_plus = self.counting.PLUS_DIR
                        self.counting.update_line(
                            new_off, new_orient,
                            direction_mode=new_mode, direction=new_dir)
                        self.rendering.update_line(new_off, new_orient)
                        new_plus = self.counting.PLUS_DIR
                        if new_plus != old_plus:
                            # Zero the global counter and per-class sub-counts
                            # (rebuild from the active counting_class_ids set,
                            # mirroring the counting_class_ids reset below).
                            shared_state.counter_to_right = 0
                            shared_state.sub_counts = {
                                cid: 0
                                for cid in shared_state.counting_class_ids}
                            # Reset the Counting instance's area state: a +1
                            # flip leaves tracks on the wrong abstract side,
                            # so clear the side lists. update_line already
                            # reset the warm-up accumulators (_dir_locked /
                            # _dir_crossing_tally / _raw_side / run-start).
                            self.counting.area_in_list = []
                            self.counting.area_out_list = []
                            changed.append("counting_line(dir-reset)")
                        else:
                            changed.append("counting_line")
                    # counting_class_ids: a class-set CHANGE resets the
                    # counters to 0 (fresh-session semantics, matches boot).
                    # A line-only / toggle-only change does NOT reset. Compare
                    # as sets so an unchanged ordering doesn't spuriously zero.
                    _ids = pending.get("counting_class_ids")
                    if isinstance(_ids, list):
                        cur_ids = list(shared_state.counting_class_ids)
                        if set(int(c) for c in _ids) != set(cur_ids):
                            new_ids = [int(c) for c in _ids]
                            shared_state.counting_class_ids = new_ids
                            self.counting.counting_class_ids = list(new_ids)
                            shared_state.sub_counts = {
                                cid: 0 for cid in new_ids}
                            shared_state.counter_to_right = 0
                            changed.append("counting_class_ids(reset)")
                    # BL-87: mask_zones apply — NO counter reset (a mask
                    # change alters WHERE we count, not WHAT we count,
                    # analogous to the line offset/orientation apply above,
                    # not the counting_class_ids reset). Empty list is a
                    # valid "clear mask" value (isinstance(list) accepts it).
                    _mz = pending.get("mask_zones")
                    if isinstance(_mz, list):
                        shared_state.mask_zones = _mz
                        changed.append("mask_zones")
                    if changed:
                        logger.info("runtime settings applied (idle): %s",
                                    ", ".join(changed))
                else:
                    # reload_pending was set but pending was None — nothing
                    # to apply (e.g. an empty file). Log at DEBUG to avoid noise.
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("runtime settings reload pending but "
                                     "empty; cleared without applying")
            elif shared_state.reload_pending and shared_state.recording:
                # Held until the next idle window. Log at INFO so the operator
                # knows the change is queued (not lost).
                logger.info("runtime settings held (recording in progress); "
                            "applied at next idle window")

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Value Recording: {shared_state.recording}; Value Status: {shared_state.status}; Video Writer: {self.video_writer}; delay reinit: {shared_state.delay_reinit}")

            # Stop video writer
            # If recording is in progress
            # And we asked to stop the video
            # Or we switched to learning mode
            # Or counting was reset
            # Or in automatic mode and no animals detected anymore
            if self.video_writer is not None and self.video_writer.isOpened() and shared_state.recording and ((
                shared_state.status == 0 or shared_state.learning_mode or shared_state.reset or
                (shared_state.status in [1,3] and
                (time.monotonic() - shared_state.delay_reinit) > shared_state.delay_last_class)
            )):
                self._finalize_recording()
                if self.input_type == "FILE":
                    logger.info(f"------->MODE TEST. STOP.")
                    self.stop_event.set()
                    break

            try:
                self.results = self.frame_queue.get(timeout=1)
            except:
                continue

            # Always retrieve img FIRST
            if len(self.results) > 1:
                img, boxes_pp, output, use_time, origin_h, origin_w, frame_counter, r_scale, tx1, ty1, y_offset, input_h, input_w = self.results
            else:
                img = self.results[0]

            # BL-88: write a raw-frame JPEG snapshot (atomic tmp+rename) at
            # most once per SNAPSHOT_INTERVAL_SECONDS, gated on a wall-clock
            # timestamp. The snapshot is captured here (top of loop, right
            # after `img` is pulled from the queue) so it is the RAW counting-
            # resolution frame, BEFORE any tracking.draw_counter /
            # rendering.display_counter / video_writer.write call mutates it
            # in place. This is display infrastructure only — no
            # counting/tracking/rendering logic is touched. Best-effort: a
            # failure inside _write_snapshot is logged WARNING and swallowed,
            # never raised (must not break the display loop).
            if settings.SNAPSHOT_ENABLED and (time.time() - last_snapshot_time) >= settings.SNAPSHOT_INTERVAL_SECONDS:
                self._write_snapshot(img)
                last_snapshot_time = time.time()

            # Recording without tracking
            if not shared_state.draw_tracking and shared_state.status in [1,3] and shared_state.recording and self.video_writer is not None:
                self.video_writer.write(img)

            # =========================
            # LEARNING MODE FIXED
            # =========================
            if shared_state.learning_mode and shared_state.status in [1,3]:

                if time.time() - shared_state.learning_start_time > shared_state.max_learning_duration:
                    shared_state.learning_mode = False
                    shared_state.status = 0
                    shared_state.learning_start_time = None
                    shared_state.image_counter = 0
                    logger.info("Learning Mode ended. Returning to normal mode.")

                if time.time() - last_capture_time >= settings.CAPTURE_INTERVAL:
                    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                    image_path = os.path.join(settings.DATASET_DIR, f"{timestamp}.jpg")

                    cv2.imwrite(image_path, img)
                    last_capture_time = time.time()

                    shared_state.image_counter += 1
                    logger.info(f"Image {shared_state.image_counter} captured: {image_path}")

            # =========================
            # NORMAL PROCESSING
            # =========================
            if shared_state.status in [1, 2, 3] and len(self.results) > 1:

                self.frame_counter += 1

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Received {frame_counter}...")

                # PAUSE
                if shared_state.status == 2:
                    img = self.rendering.display_counter(
                        img,
                        shared_state.counter_to_right,
                        shared_state,
                        self.input_type
                    )

                    if self.input_type == "CAMERA":
                        img = self.rendering.draw_ui(img, shared_state, self.input_type)
                        cv2.imshow(self.window_name, img)
                        cv2.waitKey(1)

                    continue

                # Postprocess
                #boxes_pp = self.yolo.post_process(output, origin_h, origin_w)

                detections = []

                if len(boxes_pp) > 0:
                    boxes_scaled = []

                    for b in boxes_pp[:, :4]:
                        box = self.tracking.undo_letterbox(
                            b,
                            origin_h,
                            origin_w,
                            input_h,
                            input_w
                        )

                        box[1] += y_offset
                        box[3] += y_offset

                        boxes_scaled.append(box)

                    boxes_scaled = np.array(boxes_scaled)

                    detections = Detections(
                        xyxy=boxes_scaled,
                        confidence=boxes_pp[:, 4],
                        class_id=boxes_pp[:, 5].astype(int)
                    )
                else:
                    detections = Detections(
                        xyxy=np.empty((0, 4)),
                        confidence=np.empty((0,)),
                        class_id=np.empty((0,))
                    )

                tracked = self.sort_tracker.update(detections)

                result_boxes = tracked.xyxy
                result_trackid = tracked.tracker_id
                result_classid = tracked.class_id
                result_scores = tracked.confidence

                valid_indices = result_trackid != -1

                result_boxes = result_boxes[valid_indices]
                result_trackid = result_trackid[valid_indices]
                result_classid = result_classid[valid_indices]
                result_scores = result_scores[valid_indices]

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Score: {result_scores} TrackID: {result_trackid}")

                # Init video writer
                if not shared_state.recording and not shared_state.learning_mode and self.video_writer is None and (
                        shared_state.status==1 or
                        (shared_state.status==3 and self.has_pig_high_score(result_classid, result_scores))
                    ):

                    shared_state.recording = True
                    start_ts = time.strftime('%Y%m%d-%H%M%S')
                    output_path = os.path.join(settings.OUTPUT_VIDEO_PATH, f"tmp-counting-{start_ts}.mp4")
                    os.makedirs(settings.OUTPUT_VIDEO_PATH, exist_ok=True)
                    self.filename = output_path
                    self.record_start_ts = start_ts
                    self.record_start_time = time.monotonic()
                    self.record_start_count = shared_state.counter_to_right
                    logger.info(f"Record started: {self.filename}")

                    self.video_writer = cv2.VideoWriter(
                        self.filename,
                        cv2.VideoWriter_fourcc(*'mp4v'),
                        30,
                        (settings.OUTPUT_WIDTH, settings.OUTPUT_HEIGHT)
                    )

                # We reset the delay only if the detected animal's score is very good
                # BL-78: keep recording alive while a counted-class detection
                # (membership in counting_class_ids) exceeds the start threshold.
                continue_recording = np.isin(result_classid, list(shared_state.counting_class_ids)) & (result_scores > settings.PIG_CONFIDENCE_THRESHOLD_START_VIDEO)

                if continue_recording.any():
                #if 0 in result_classid and result_scores > settings.PIG_CONFIDENCE_THRESHOLD_START_VIDEO :
                    shared_state.delay_reinit = time.monotonic()

                # COUNT FIX
                shared_state.counter_to_right = self.counting.count(
                    image_raw=img,
                    result_boxes=result_boxes,
                    result_trackid=result_trackid,
                    result_classid=result_classid,
                    result_scores=result_scores,
                    counting_class_ids=shared_state.counting_class_ids,
                    counter_to_right=shared_state.counter_to_right
                )

                # Draw
                self.tracking.draw_counter(
                    image=img,
                    result_boxes=result_boxes,
                    result_scores=result_scores,
                    result_classid=result_classid,
                    result_trackid=result_trackid,
                    frame_counter=frame_counter,
                    categories=shared_state.class_names
                )

                img = self.rendering.display_counter(
                    img,
                    shared_state.counter_to_right,
                    shared_state,
                    self.input_type
                )

                # Write video
                if shared_state.draw_tracking and shared_state.status in [1,3] and shared_state.recording and self.video_writer is not None:
                    self.video_writer.write(img)

            else:
                img = self.rendering.display_counter(
                    img,
                    shared_state.counter_to_right,
                    shared_state,
                    self.input_type
                )

            # Display
            if self.input_type == "CAMERA":
                img = cv2.resize(img, (settings.OUTPUT_SCREEN_WIDTH, settings.OUTPUT_SCREEN_HEIGHT))
                img = self.rendering.draw_ui(img, shared_state, self.input_type)
                cv2.imshow(self.window_name, img)

                cv2.waitKey(1)

            self.frame_queue.task_done()

        # Safety-net: finalize recording on any loop exit path
        # (race-lost where stop_event pre-empted the in-loop rename,
        # or any other exit). The idempotent guard inside _finalize_recording
        # makes this a no-op if the writer was already finalized or is None.
        self._finalize_recording()