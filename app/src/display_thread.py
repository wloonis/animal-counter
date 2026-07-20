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

from settings import settings
from core.tracking import Tracking
from core.counting import Counting
from ui.rendering import Rendering
from utils.timer_fps import TimerFps
from supervision import Detections

from state import shared_state, logger


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

    def mouse_click(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONUP:
            self.rendering.handle_click(x, y, shared_state)

    def has_pig_high_score(self, class_ids, scores, threshold=settings.PIG_CONFIDENCE_THRESHOLD_START_VIDEO):
        # class_id == 1 corresponds to pigs
        thresh = threshold
        for i in range(len(class_ids)):
            if class_ids[i] == 1 and scores[i] >= thresh:
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

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("DisplayThread started")

        while not self.stop_event.is_set():
            time_start = time.time()

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

                # We reset the delay only if the detected pig's score is very good
                # class_id == 1 corresponds to pigs
                continue_recording = (result_classid == 1) & (result_scores > settings.PIG_CONFIDENCE_THRESHOLD_START_VIDEO)

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
                    counting_class=1,
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
                    categories=['human', 'pig']
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