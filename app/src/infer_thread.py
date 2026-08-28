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
Inference thread for the pig counting application.

Moved verbatim from `main.py` (the real `class InferThread(threading.Thread)`,
main.py:124-224). The dead empty stub class that previously shadowed it at
main.py:111-123 is dropped.

The thread reads frames from a `FrameSource`, runs YOLO TensorRT inference via
`Inference`, and pushes result batches onto `frame_queue` for the
`DisplayThread` to consume. It reads the process-wide `shared_state`/`logger`
singletons from the `state` leaf module (same objects `main.py` used as module
globals — no behavior change).
"""

import threading
import time
import logging
from queue import Queue

from settings import Settings
from core.inference import Inference
from utils.frame_source import FrameSource
from utils.timer_fps import TimerFps

from state import shared_state, logger


class InferThread(threading.Thread):

    def __init__(
        self,
        frame_queue: Queue,
        max_queue_size,
        engine_file_path,
        video_path,
        stop_event,
        input_type="CAMERA",
        input_width=None,
        input_height=None,
        input_url=None
    ):
        super().__init__()

        self.frame_queue = frame_queue
        self.max_queue_size = max_queue_size

        self.engine_file_path = engine_file_path

        self.yolo = None

        self.video_path = video_path
        self.input_type = input_type
        self.input_width = input_width
        self.input_height = input_height
        self.input_url = input_url
        self.frame_counter = 0
        self.timer = TimerFps()
        self.stop_event = stop_event

    def run(self):
        """Run the inference thread."""

        self.yolo = Inference(self.engine_file_path)

        frame_source = FrameSource(
            self.video_path,
            self.input_type,
            input_width=self.input_width,
            input_height=self.input_height,
            input_url=self.input_url,
        )
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
                    if self.input_type == "STREAM":
                        shared_state.status = 0
                        logger.info(
                            f"------->No Frame (STREAM idle — reconnecting); "
                            f"Value Status: {shared_state.status}"
                        )
                        time.sleep(1)
                        continue
                    shared_state.status = 0
                    logger.info(f"------->No Frame; Value Status: {shared_state.status}")
                    break

                if shared_state.status in [1,3]:
                    time_start = time.time()
                    output, use_time, origin_h, origin_w, preproc_time, r_scale, tx1, ty1 = self.yolo.infer(image_raw)
                    time_end = time.time()

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Duration InfThread: {(time_end-time_start)*1000:.2f}ms, avg: {((time_end-time_start)*1000)/self.frame_counter:.2f}ms, use time: {use_time*1000:.2f}ms, preproc: {preproc_time*1000:.2f}ms")

                    boxes_pp = self.yolo.post_process(
                        output,
                        origin_h,
                        origin_w,
                        counting_class_ids=shared_state.counting_class_ids,
                        mask_zones=shared_state.mask_zones,
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