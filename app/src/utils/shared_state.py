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
SharedState module for the pig counting application.

This module provides a shared state object to replace global variables.
"""

import os
import time
import datetime
import threading
from queue import Queue
from threading import Event

class SharedState:
    """
    Shared state object to replace global variables.
    
    Attributes:
        status (int): Application status (0: Stopped, 1: Started, 2: Paused).
        recording (bool): Whether recording is in progress.
        counter_to_right (int): Count of objects moving to the right.
        frame_queue (Queue): Queue for frame processing.
        draw_tracking (bool): Whether to draw tracking.
        infer_thread (InferThread): Thread for inference.
        display_thread (DisplayThread): Thread for display and counting.
        delay_reinit (float): monotonic timestamp of the last pig detection
            or user interaction (auto/play/reset); used by the recording
            idle-timeout check (immunized against wall-clock jumps on the
            RTC-less Jetson).
    """
    
    def __init__(self):
        """Initialize the shared state."""
        self.status = 3
        self.recording = False
        self.counter_to_right = 0
        self.frame_queue = Queue(maxsize=10)
        self.draw_tracking = True
        self.centroid_tracking = True
        self.box_tracking = True
        # BL-87: detection-level exclusion zones (normalized axis-aligned
        # rects {x,y,w,h} in [0..1]). Detections whose centroid falls inside
        # any rect are dropped in post_process BEFORE OC-SORT (no track → no
        # count). Empty list = no-op (byte-identical pre-BL-87 behavior).
        self.mask_zones = []
        # BL-87: independent overlay toggle (NOT gated on draw_tracking) so
        # the operator can see the mask rects even on raw/untracked frames.
        self.draw_mask_zones = True
        # BL-58 render tuning (purely visual; mirrored from Settings in main.py)
        self.draw_box_line_thickness = 2
        self.draw_label_font_scale = 0.6
        self.draw_label_thickness = 2
        self.draw_centroid_radius = 3
        self.infer_thread = None
        self.display_thread = None
        self.delay_reinit = time.monotonic()
        # No-detection timeout (s): single source of truth for recording stop
        # (DisplayThread) and cronvideo compression trim. Env-configurable so the
        # app and the cron pod (Ansible var) can share one configured value.
        self.delay_last_class = int(os.getenv("DELAY_LAST_CLASS", 180))
        self.trails = {}
        ### MODIFICATION: Learning Mode - Start
        self.learning_mode = False
        self.learning_start_time = None
        self.max_learning_duration = 1200
        self.max_video_duration = 3600
        self.image_counter = 0  # Counter for captured images
        ### MODIFICATION: Learning Mode - End
        ### MODIFICATION: Auto Mode - Start
        self.auto_mode = True
        self.reset = False
        ### MODIFICATION: Learning Mode - End
        self.stop_event = Event()
        # BL-62: Arrêt button — flags for graceful shutdown + poweroff
        self.arret_requested = False
        self.poweroff_requested = False
        # BL-76: wall-clock boot time of the process, used by the anti-stale
        # check of the .arret_requested sentinel in DisplayThread.run (the
        # sentinel only triggers a poweroff if its mtime is *newer* than this).
        self.app_start_time = time.time()
        # BL-68: counting-history recorder (serve mode only). Holds the
        # HistoryWriter instance so stop() and the BL-62 poweroff path can reach
        # it and emit a clean session_end. None in validate/test mode.
        self.history_writer = None
        self.history_session_id = None
        # BL-78: configurable counting classes (multi-species, model-driven).
        # Populated at startup from classes.yaml (state.load_classes_yaml);
        # counting_class_ids is re-resolved per recording in the main.py BL-76
        # hot-reload block. These __init__ defaults reproduce the exact
        # pre-BL-78 behavior when classes.yaml is absent (legacy deployed
        # models without it boot and count identically).
        self.class_names = ['human', 'pig']
        self.default_counting_class = 1
        self.model_version = None
        self.counting_class_ids = [1]
        # Per-species sub-counters {class_id: count}; reset per recording to
        # {cid: 0 for cid in counting_class_ids}. The global counter_to_right
        # is the sum of these (retro-compatible invariant).
        self.sub_counts = {}
        # BL-86: in-process hot-reload of runtime settings (idle-gated, no pod
        # restart). The RuntimeSettingsWatcher thread polls the mtime of
        # /conf/runtime-settings.json and, on a change, stores the validated
        # pending payload here + sets reload_pending. DisplayThread.run()
        # applies it at the first idle window (reload_pending AND not
        # recording) under reload_lock — the single applier, no setter race.
        self.pending_settings = None  # dict or None
        self.reload_pending = False
        self.reload_lock = threading.Lock()
        # BL-86: holder for the RuntimeSettingsWatcher instance, started after
        # the threads launch in main.start() and best-effort joined in stop().
        self.settings_watcher = None
