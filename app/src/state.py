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
Leaf module holding the process-wide singletons used by the pig counting
application: the `Settings` instance, the `SharedState` instance (with its
draw_* field setup), the module `logger` (+ `logging.basicConfig`), and the
`_IOU_METRICS` map.

Every split module (`infer_thread`, `display_thread`, `cli`, `main`) imports
these singletons from here so they all bind to the *same* object instances
(no circular imports — this module imports nothing from the split modules).
"""

import json
import logging
import os

from settings import Settings
from utils.shared_state import SharedState
# OC-SORT tracker (lib `trackers`). Tuned to resist ID switches near the
# counting line: longer lost_track_buffer + low high_conf_det_threshold so the
# OCR second-chance association can re-bind a briefly-occluded pig to its
# original ID instead of spawning a new one.
from trackers.utils.iou import IoU, GIoU, DIoU, CIoU, BIoU

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

# Map the COUNTING_TRACKER_IOU setting (string) to a BaseIoU instance for
# OCSORTTracker(iou=...). trackers>=2.5.0 expects an IoU instance, not a string.
_IOU_METRICS = {"iou": IoU, "giou": GIoU, "diou": DIoU, "ciou": CIoU, "biou": BIoU}

# BL-76: shared file used by the Jetson companion to push runtime toggles
# (hot-reloaded at the start of each recording by main.py). BL-79 split:
# config/control files live in /conf (hostPath /data/orin/conf), separate
# from data files in /files (hostPath /data/orin/files, e.g.
# counting-history.jsonl, BL-68). Both hostPaths are mounted RW in the pod.
RUNTIME_SETTINGS_PATH = "/conf/runtime-settings.json"


def load_runtime_settings():
    """Best-effort read of the shared runtime-settings.json file.

    Returns a dict (possibly empty) deserialized from RUNTIME_SETTINGS_PATH.
    Any read/parse error is logged at WARNING level and yields `{}` — the
    caller is expected to fall back on os.getenv / existing defaults for the
    missing keys. Never raises.
    """
    try:
        with open(RUNTIME_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
        logger.warning("runtime-settings.json is not a JSON object: %r", data)
        return {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("runtime-settings.json unreadable (%s): %s",
                        type(exc).__name__, exc)
        return {}