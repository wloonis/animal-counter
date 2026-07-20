"""
Main entry point for the pig counting application.

BL-29 refactor: this file is now a thin orchestration layer. The inference
thread, display thread, result-JSON writer, CLI/serve loop, and the
process-wide singletons (`shared_state`/`logger`/`settings`/`_IOU_METRICS`)
have been split into leaf modules:

- `state.py`         — `shared_state`, `logger`, `settings`, `_IOU_METRICS`
- `infer_thread.py`  — `class InferThread`
- `display_thread.py`— `class DisplayThread`
- `validate.py`      — `write_result_json()`
- `cli.py`           — `cli.main()` (argparse + serve/validate loop + poweroff)

What remains here is `start()` / `stop()` (the orchestration glue that
instantiates the threads and wires the history recorder) and the
`if __name__ == "__main__"` guard delegating to `cli.main()`.

Re-exports: `DisplayThread`, `shared_state`, `settings`, `logger` are exposed
as module-level names so `tests/test_finalize_recording_filename.py`
(`import main as main_mod; main_mod.DisplayThread; main_mod.shared_state;
main_mod.settings; main_mod.settings.OUTPUT_VIDEO_PATH`) keeps working
unchanged.
"""

import os
import logging

import cv2
from queue import Queue

# OC-SORT tracker (lib `trackers`). Tuned to resist ID switches near the
# counting line: longer lost_track_buffer + low high_conf_det_threshold so the
# OCR second-chance association can re-bind a briefly-occluded pig to its
# original ID instead of spawning a new one.
from trackers import OCSORTTracker
from trackers.utils.iou import IoU

from core.tracking import Tracking
from core.counting import Counting
from ui.rendering import Rendering
# BL-68: append-only JSONL counting-session history (serve mode only).
# Stdlib-only writer + dedicated heartbeat/compaction thread.
from core.history import HistoryWriter, HistoryThread

# Process-wide singletons (leaf module — no circular imports).
from state import shared_state, settings, logger, _IOU_METRICS
# Split thread classes.
from infer_thread import InferThread
from display_thread import DisplayThread

import cli


def stop():
    logger.info("Stopping threads...")

    shared_state.stop_event.set()

    # Finalize the in-progress recording FIRST (before ending the history
    # session) so the per-video `video` JSONL line is written while the
    # HistoryWriter is still active (history.video() guards on _stopped).
    # _finalize_recording releases the mp4 writer (flushing the moov atom)
    # AND renames tmp-counting to tocompress-counting. Idempotent (no-op if
    # the loop already finalized). Best-effort: never raises into the
    # shutdown path. The SIGTERM handler calls stop(), so this covers SIGTERM.
    if shared_state.display_thread is not None:
        shared_state.display_thread._finalize_recording()

    # BL-68: finalize the history session (serve mode) before joining
    # threads, so the session_end line is fsync'd to /files even if a
    # later join times out or the process is killed during poweroff.
    # Idempotent (end_session guards on _stopped). Best-effort: never
    # raises into the shutdown path.
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

    if shared_state.infer_thread and shared_state.infer_thread.is_alive():
        shared_state.infer_thread.join(timeout=5)

    if shared_state.display_thread and shared_state.display_thread.is_alive():
        shared_state.display_thread.join(timeout=5)

    cv2.destroyAllWindows()

    logger.info("Stopped cleanly")


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


if __name__ == "__main__":
    cli.main()