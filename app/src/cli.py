"""
CLI entry point for the pig counting application.

Moved verbatim from `main.py`'s `if __name__ == "__main__"` block (main.py:731-840).
It registers the SIGTERM/SIGINT handler, parses the three CLI args (`-m`/`-f`/`-d`),
calls `start()` (in `main.py`), and then either:

- **validate mode** (`RESULT_JSON_PATH` set): waits for the InferThread to drain
  the whole video, drains `frame_queue`, stops + joins the DisplayThread, and
  writes the result JSON via `write_result_json`.
- **serve mode** (`RESULT_JSON_PATH` unset): waits for `stop_event` (Arrêt button
  or SIGTERM), calls `stop()`, and — if `poweroff_requested` — powers off the
  Jetson via `nsenter ... systemctl poweroff` (BL-62).

The `except Exception` path writes an error result JSON in validate mode.

`start()`/`stop()` live in `main.py`, and `main.py` imports this module, so the
`main → cli → main` circular dependency is broken by importing `start`/`stop`
**inside** `cli.main()` (function-local import): loading `main.py` never triggers
loading `cli`'s `start`/`stop` references until `cli.main()` actually runs.

Reads the process-wide `shared_state`/`logger`/`settings` singletons from the
`state` leaf module (same objects `main.py` used as module globals — no behavior
change). French comments from the original block are translated to English
(BL-29 Task 7); logic is unchanged.
"""

import sys
import os
import time
import signal
import subprocess
import logging
from argparse import ArgumentParser

import cv2

from state import shared_state, logger, settings
from validate import write_result_json


def main():
    """CLI entry point. Parses args, runs start(), and serves/validates."""

    # Function-local import: start()/stop() live in main.py, and main.py imports
    # cli at module load time. Importing them here (instead of at module top)
    # breaks the main → cli → main circular dependency — loading main.py never
    # reaches this line until cli.main() actually runs.
    from main import start, stop

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
        # for stop_event (stop button or SIGTERM), then stop() + poweroff (BL-62).
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
            # BL-62: CAMERA/serve mode — wait for a clean stop request (stop
            # button or SIGTERM), then stop() + power off the Jetson.
            while not shared_state.stop_event.is_set():
                time.sleep(0.5)
            stop()
            if shared_state.poweroff_requested:
                # Power off the Jetson cleanly via the host systemd (hostPID:
                # true in the K3s manifest allows nsenter -t 1 to reach systemd).
                # The recording is already finalized
                # (DisplayThread._finalize_recording is called before
                # stop_event.set()), so the moov atom is on disk.
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