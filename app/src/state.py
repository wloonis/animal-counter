"""
Leaf module holding the process-wide singletons used by the pig counting
application: the `Settings` instance, the `SharedState` instance (with its
draw_* field setup), the module `logger` (+ `logging.basicConfig`), and the
`_IOU_METRICS` map.

Every split module (`infer_thread`, `display_thread`, `cli`, `main`) imports
these singletons from here so they all bind to the *same* object instances
(no circular imports — this module imports nothing from the split modules).
"""

import logging

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