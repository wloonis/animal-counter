# hello-plannotator
"""
Main application entry point for the pig counting application.

This module initializes and runs the pig counting application with TensorRT inference
and Norfair tracking.
"""

import threading
import cv2
import time
import datetime
import logging
import sys
import os
import signal
import json
import subprocess
import numpy as np
from queue import Queue
from argparse import ArgumentParser

from threading import Event
from settings import Settings
from core.inference import Inference
from core.tracking import Tracking
from core.counting import Counting
from ui.rendering import Rendering
from utils.frame_source import FrameSource
from utils.shared_state import SharedState
from utils.timer_fps import TimerFps
# OC-SORT tracker (lib `trackers`). Tuned to resist ID switches near the
# counting line: longer lost_track_buffer + low high_conf_det_threshold so the
# OCR second-chance association can re-bind a briefly-occluded pig to its
# original ID instead of spawning a new one.
from trackers import OCSORTTracker
from trackers.utils.iou import IoU, GIoU, DIoU, CIoU, BIoU

# Map the COUNTING_TRACKER_IOU setting (string) to a BaseIoU instance for
# OCSORTTracker(iou=...). trackers>=2.5.0 expects an IoU instance, not a string.
_IOU_METRICS = {"iou": IoU, "giou": GIoU, "diou": DIoU, "ciou": CIoU, "biou": BIoU}
from supervision import Detections
# BL-68: append-only JSONL counting-session history (serve mode only).
# Stdlib-only writer + dedicated heartbeat/compaction thread.
from core.history import HistoryWriter, HistoryThread


# Load settings
settings = Settings()

# Configure logging
logging.basicConfig(format='%(levelname)s:%(message)s', level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

# Shared state
shared_state = SharedState()
shared_state.draw_tracking = settings.DRAW_TRACKING
shared_state.centroid_tracking = settings.CENTROID_TRACKING
shared_state.box_tracking = settings.BOX_TRACKING
# BL-58 bounding-box render tuning (visual only - no counting/tracking impact)
shared_state.draw_box_line_thickness = settings.DRAW_BOX_LINE_THICKNESS
shared_state.draw_label_font_scale = settings.DRAW_LABEL_FONT_SCALE
shared_state.draw_label_thickness = settings.DRAW_LABEL_THICKNESS
shared_state.draw_centroid_radius = settings.DRAW_CENTROID_RADIUS

# Stop cleanly
def stop():
    logger.info("Stopping threads...")

    shared_state.stop_event.set()

    # BL-68: finalize the history session (serve mode) before joining
    # threads, so the session_end line is fsync'd to /files even if a
    # later join times out or the process is killed during poweroff.
    # Idempotent (end_session guards on _stopped). Best-effort: never
    # raises into the shutdown path. The SIGTERM handler calls stop(),
    # so this also covers SIGTERM.
    hw = getattr(shared_state, "history_writer", None)
    if hw is not None:
        try:
            hw.end_session("clean")
        except Exception as e:
            logger.warning(f"history: end_session failed: {e!r}")
    ht = getattr(shared_state, "history_thread", None)
    if ht is not None and ht.is_alive():
        try:
            ht.stop_event.set()
            ht.join(timeout=2)
        except Exception as e:
            logger.warning(f"history: thread join failed: {e!r}")

    # Finalize the mp4 before joining display_thread: on a K3s SIGTERM the
    # 5s join may time out and the thread can be killed mid-write, leaving
    # the file without a moov atom (unreadable). _finalize_recording releases
    # the writer (flushing the moov atom) AND renames tmp-counting to
    # tocompress-counting, even if the join times out. The idempotent guard
    # inside _finalize_recording makes this a no-op if the loop already
    # finalized (writer is None).
    if shared_state.display_thread is not None:
        shared_state.display_thread._finalize_recording()

    if shared_state.infer_thread and shared_state.infer_thread.is_alive():
        shared_state.infer_thread.join(timeout=5)

    if shared_state.display_thread and shared_state.display_thread.is_alive():
        shared_state.display_thread.join(timeout=5)

    cv2.destroyAllWindows()

    logger.info("Stopped cleanly")

class InferThread(threading.Thread):
    """
    Thread for handling inference on frames.
    
    Attributes:
        frame_queue (Queue): Queue for frame processing.
        max_queue_size (int): Maximum size of the frame queue.
        yolo (Inference): YOLO TensorRT model.
        video_path (str): Path to video source.
        frame_counter (int): Current frame counter.
        timer (TimerFps): Timer for FPS calculation.
    """
    
class InferThread(threading.Thread):

    def __init__(
        self,
        frame_queue: Queue,
        max_queue_size,
        engine_file_path,
        video_path,
        stop_event,
        input_type="CAMERA"
    ):
        super().__init__()

        self.frame_queue = frame_queue
        self.max_queue_size = max_queue_size

        self.engine_file_path = engine_file_path

        self.yolo = None

        self.video_path = video_path
        self.input_type = input_type
        self.frame_counter = 0
        self.timer = TimerFps()
        self.stop_event = stop_event
            
    def run(self):
        """Run the inference thread."""

        self.yolo = Inference(self.engine_file_path)

        frame_source = FrameSource(self.video_path, self.input_type)
        settings = Settings()

        try:
            while not self.stop_event.is_set():
                self.frame_counter += 1
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Capturing: {self.frame_counter}...")
                ret, image_raw = frame_source.read()
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Captured: {self.frame_counter}...")

                if not ret:
                    shared_state.status = 0
                    logger.info(f"------->No Frame; Value Status: {shared_state.status}")
                    break

                TOP_IGNORE = settings.TOP_IGNORE
                BOTTOM_IGNORE = settings.BOTTOM_IGNORE

                h, w = image_raw.shape[:2]

                frame_roi = image_raw[TOP_IGNORE:h-BOTTOM_IGNORE, :]
                y_offset = TOP_IGNORE

                if shared_state.status in [1,3]:
                    time_start = time.time()
                    output, use_time, origin_h, origin_w, preproc_time, r_scale, tx1, ty1 = self.yolo.infer(frame_roi)
                    time_end = time.time()
                    
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Duration InfThread: {(time_end-time_start)*1000:.2f}ms, avg: {((time_end-time_start)*1000)/self.frame_counter:.2f}ms, use time: {use_time*1000:.2f}ms, preproc: {preproc_time*1000:.2f}ms")

                    boxes_pp = self.yolo.post_process(
                        output,
                        origin_h,
                        origin_w
                    )

                    results = [image_raw, boxes_pp, output, use_time, origin_h, origin_w, self.frame_counter, r_scale, tx1, ty1, y_offset, self.yolo.input_h, self.yolo.input_w]
                    
                    try:
                        self.frame_queue.put(results, timeout=1)
                    except:
                        continue
                    
                    current_time, avg_time, avg_fps = self.timer.update(self.frame_counter)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Time InferThread: {current_time*1000:.2f}ms | avg: {avg_time*1000:.2f}ms | avg fps: {avg_fps:.2f}")
                else:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("Direct to frame_queue")
                    self.frame_queue.put([image_raw])

        finally:
            logger.info("InferThread cleanup started")

            self.stop_event.set()

            time.sleep(0.5)

            if self.yolo is not None:
                self.yolo.destroy()

            frame_source.release()

            logger.info("InferThread cleanup done")            
#        frame_source.release()


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
        output_path = os.path.join(settings.OUTPUT_VIDEO_PATH, f"tocompress-counting-{time.strftime('%Y%m%d-%H%M%S')}-#{delta}.mp4")
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
        logger.info(f"------->Record Stop; Value Status: {shared_state.status}: Store:{output_path}")

    def mouse_click(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONUP:
            self.rendering.handle_click(x, y, shared_state)
            
    def has_pig_high_score(self, class_ids, scores, threshold=settings.PIG_CONFIDENCE_THRESHOLD_START_VIDEO):
        # class_id == 1 correspond aux cochons
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

            # BL-62: Arrêt propre — détecte la demande d'arrêt et lance la séquence
            # d'extinction: (1) status=0/auto/learning off, (2) _finalize_recording
            # (flush moov atom + rename tmp->tocompress, CRITIQUE avant poweroff),
            # (3) stop_event.set(), (4) poweroff_requested=True.
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
            # Si l'enregistrement et en cours
            # Et que l'on a demandé de stopper la vidéo
            # Ou que l'on est passé en mode learning
            # Ou que le comptage a été réinitialisé
            # Ou que l'on est en mode automatique et que l'on a plus détecté d'animaux
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

            # Toujours récupérer img AVANT tout
            if len(self.results) > 1:
                img, boxes_pp, output, use_time, origin_h, origin_w, frame_counter, r_scale, tx1, ty1, y_offset, input_h, input_w = self.results
            else:
                img = self.results[0]

            # Recording without tracking
            if not shared_state.draw_tracking and shared_state.status in [1,3] and shared_state.recording and self.video_writer is not None:
                self.video_writer.write(img)

            # =========================
            # LEARNING MODE FIXÉ
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
                    output_path = os.path.join(settings.OUTPUT_VIDEO_PATH, f"tmp-counting-{time.strftime('%Y%m%d-%H%M%S')}.mp4")
                    os.makedirs(settings.OUTPUT_VIDEO_PATH, exist_ok=True)
                    self.filename = output_path
                    self.record_start_time = time.monotonic()
                    self.record_start_count = shared_state.counter_to_right
                    logger.info(f"Record started: {self.filename}")

                    self.video_writer = cv2.VideoWriter(
                        self.filename,
                        cv2.VideoWriter_fourcc(*'mp4v'),
                        30,
                        (settings.OUTPUT_WIDTH, settings.OUTPUT_HEIGHT)
                    )

                # On réinitialise le delay uniquement si le score du cochon détecté est très bon
                # class_id == 1 correspond aux cochons
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

def start(input_source, video_path):
    """
    Start the pig counting application.
    
    Args:
        input_source (str): Input source (CAMERA or FILE).
        video_path (str): Path to video file.
    """
    logger.info("Started!")
    
    if shared_state.recording:
        return "Counting already started\nStop It if you want to start again."
    
    try:
        shared_state.recording = False
        
        if shared_state.infer_thread is None or (shared_state.infer_thread and not shared_state.infer_thread.is_alive()):
            engine_file_path = "./model/my_model.engine"
            
            shared_state.stop_event.clear()        
            
            byte_tracker = OCSORTTracker(
                lost_track_buffer=settings.TRACKER_LOST_TRACK_BUFFER,
                frame_rate=settings.TRACKER_FRAME_RATE,
                minimum_consecutive_frames=settings.TRACKER_MIN_CONSECUTIVE_FRAMES,
                minimum_iou_threshold=settings.TRACKER_MIN_IOU_THRESHOLD,
                direction_consistency_weight=settings.TRACKER_DIRECTION_CONSISTENCY_WEIGHT,
                high_conf_det_threshold=settings.TRACKER_HIGH_CONF_THRESHOLD,
                delta_t=settings.TRACKER_DELTA_T,
                iou=_IOU_METRICS.get(settings.COUNTING_TRACKER_IOU.lower(), IoU)(),
            )            

            tracking = Tracking(draw_box=shared_state.draw_tracking, shared_state=shared_state)
            counting = Counting(shared_state=shared_state, pig_confidence_threshold=settings.PIG_CONFIDENCE_THRESHOLD, offset_counting_line=settings.OFFSET_PERCENT_COUNTING_LINE, lost_buffer_frames=settings.COUNTING_LOST_BUFFER_FRAMES, reassoc_line_band=settings.COUNTING_REASSOC_LINE_BAND, reassoc_max_dist_x=settings.COUNTING_REASSOC_MAX_DIST_X, reassoc_max_dist_y=settings.COUNTING_REASSOC_MAX_DIST_Y, hysteresis_px=settings.COUNTING_HYSTERESIS_PX, mirror_guard=settings.COUNTING_MIRROR_GUARD, mirror_max_age=settings.COUNTING_MIRROR_MAX_AGE, mirror_line_band=settings.COUNTING_MIRROR_LINE_BAND, mirror_new_band=settings.COUNTING_MIRROR_NEW_BAND, mirror_max_dist_y=settings.COUNTING_MIRROR_MAX_DIST_Y, resurrection_threshold=settings.COUNTING_RESURRECTION_THRESHOLD, resurrection_min_jump=settings.COUNTING_RESURRECTION_MIN_JUMP, guard_max_age=settings.COUNTING_GUARD_MAX_AGE, reid_window=settings.COUNTING_REID_WINDOW, reid_min_age=settings.COUNTING_REID_MIN_AGE)
            rendering = Rendering(draw_box=shared_state.draw_tracking, offset_counting_line=settings.OFFSET_PERCENT_COUNTING_LINE)
            
            max_queue_size = 3
            shared_state.frame_queue = Queue(maxsize=max_queue_size)
            
            shared_state.infer_thread = InferThread(
                frame_queue=shared_state.frame_queue,
                max_queue_size=max_queue_size,
                engine_file_path=engine_file_path,
                video_path=video_path,
                stop_event=shared_state.stop_event,
                input_type=input_source
            )
            shared_state.display_thread = DisplayThread(frame_queue=shared_state.frame_queue, sort_tracker=byte_tracker, tracking=tracking, counting=counting, rendering=rendering, stop_event=shared_state.stop_event, input_type=input_source)

            # BL-68: wire the history recorder (serve mode only — when
            # RESULT_JSON_PATH is unset, consistent with the existing
            # write_result_json branch). History is best-effort and must
            # never break counting: every step is wrapped in try/except.
            if not os.getenv("RESULT_JSON_PATH", "") and getattr(shared_state, "history_writer", None) is None:
                try:
                    hw = HistoryWriter(
                        path=settings.HISTORY_FILE,
                        settings=settings,
                        shared_state=shared_state,
                        counting=counting,
                        mode="serve",
                    )
                    shared_state.history_writer = hw
                    # Read-only subscriber: counting._emit_event → JSONL event line.
                    # Purely additive to the existing control flow.
                    counting._event_subscribers.append(hw.emit_event)
                    # Power-loss recovery + session_start + startup line.
                    hw.start_session(start_reason="boot")
                    # Dedicated thread: heartbeat loop + 1x/day compaction
                    # (serialized in one thread, never per-frame I/O).
                    shared_state.history_thread = HistoryThread(
                        writer=hw, stop_event=shared_state.stop_event
                    )
                    shared_state.history_thread.start()
                    logger.info(f"history: recorder started → {settings.HISTORY_FILE}")
                except Exception as e:
                    logger.warning(f"history: failed to start recorder: {e!r}")

            shared_state.infer_thread.start()
            shared_state.display_thread.start()
    except Exception as e:
        if logger.isEnabledFor(logging.ERROR):
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Exception: {repr(e)}")
            raise


def write_result_json(result_path, video_path, shared_state, start_time, error=None):
    """Write structured result JSON after processing completes.

    Called only when RESULT_JSON_PATH env var is set (mode validate).
    In normal serve mode, this function is never called.
    """
    end_time = time.time()
    result = {
        "count": int(shared_state.counter_to_right),
        "video_file": os.path.basename(video_path),
        "timestamp": datetime.datetime.now().isoformat(),
        "duration_seconds": round(end_time - start_time, 2),
        "frames_processed": shared_state.infer_thread.frame_counter if shared_state.infer_thread else 0,
        "status": "error" if error else "completed",
        "error": str(error) if error else None
    }
    result_dir = os.path.dirname(result_path)
    if result_dir:
        os.makedirs(result_dir, exist_ok=True)
    with open(result_path, 'w') as f:
        json.dump(result, f, indent=2)
    logger.info(f"Result JSON written to {result_path}: {json.dumps(result)}")


if __name__ == "__main__":
    # Load settings
    settings = Settings()
    
    def handle_sigterm(signum, frame):
        logger.info("SIGTERM received")
        stop()

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)
    
    # Initialize input source and video path from settings
    input_source = settings.INPUT_SOURCE
    video = settings.VIDEO_PATH
    
    logger.info(f"All ARGs: {str(sys.argv[1:])}")
    logger.info(cv2.getBuildInformation())
    
    try:
        parser = ArgumentParser()
        
        parser.add_argument('-m', '--input',
                            action='store',
                            required=False,
                            choices=['CAMERA', 'FILE'],
                            help="Mode input [CAMERA, FILE]")
        
        parser.add_argument('-f', '--file',
                            action='store',
                            required=False,
                            help="Complete path to video")
        
        parser.add_argument('-d', '--drawtracking',
                            action='store',
                            required=False,
                            help="Draw box")
        
        args = parser.parse_args()
        if args.input:
            input_source = args.input
            if input_source == "FILE":
                if args.file:
                    video = args.file
                    shared_state.status = 1
                else:
                    raise Exception('Please, fill file video path')
        if args.drawtracking:
            shared_state.draw_tracking = args.drawtracking.lower() == "true"
            shared_state.centroid_tracking = True
            shared_state.box_tracking = True
        
        start_time = time.time()
        start(input_source, video)
        logger.info("Inference Started")

        # Mode validate only: wait for threads to finish and write result JSON.
        # In normal serve mode (RESULT_JSON_PATH not set), the main thread waits
        # for stop_event (bouton Arrêt or SIGTERM), then stop() + poweroff (BL-62).
        result_json_path = os.getenv("RESULT_JSON_PATH", "")
        if result_json_path:
            # 1) Wait for the InferThread to finish reading the WHOLE video (it
            #    breaks on "No Frame"). No short timeout: a long video takes
            #    longer to read than 300s, and a premature join-timeout would let
            #    us write the result JSON while frames are still being produced ->
            #    the last pigs crossing the line would be missed (under-count).
            if shared_state.infer_thread and shared_state.infer_thread.is_alive():
                shared_state.infer_thread.join()
            # 2) Wait for the DisplayThread to drain & process EVERY enqueued
            #    frame. The last crossings happen here, AFTER the InferThread ran
            #    out of frames. frame_queue.join() blocks until every put() item
            #    has been task_done()'d by the DisplayThread, so the final count
            #    is fully reflected before we serialize it.
            if shared_state.frame_queue is not None:
                try:
                    shared_state.frame_queue.join()
                except Exception:
                    pass
            # 3) Stop the DisplayThread (otherwise it loops forever on the now
            #    empty queue via get(timeout=1)) and join it, then write the result.
            shared_state.stop_event.set()
            if shared_state.display_thread and shared_state.display_thread.is_alive():
                shared_state.display_thread.join(timeout=60)
            write_result_json(result_json_path, video, shared_state, start_time)
        else:
            # BL-62: CAMERA/serve mode — attend une demande d'arrêt propre (bouton
            # Arrêt ou SIGTERM), puis stop() + poweroff du Jetson.
            while not shared_state.stop_event.is_set():
                time.sleep(0.5)
            stop()
            if shared_state.poweroff_requested:
                # Éteint le Jetson proprement via le systemd hôte (hostPID: true
                # dans le manifeste K3s permet nsenter -t 1 vers systemd).
                # L'enregistrement est déjà finalisé (DisplayThread._finalize_recording
                # appelé avant stop_event.set()), donc le moov atom est sur disque.
                logger.info("Poweroff requested — shutting down Jetson...")
                subprocess.run(
                    ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "--",
                     "sh", "-c", "sync; systemctl poweroff"],
                    check=False
                )
    except Exception as e:
        logger.error(f"Exception: {repr(e)}")
        # In validate mode, write error result JSON before exiting
        result_json_path = os.getenv("RESULT_JSON_PATH", "")
        if result_json_path:
            try:
                write_result_json(result_json_path, video, shared_state, start_time, error=e)
            except Exception:
                pass
        raise
