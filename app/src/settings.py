"""
Configuration management module for the pig counting application.

This module loads environment variables from a .env file and provides
default values for missing variables.
"""

import os
from dotenv import load_dotenv


class Settings:
    """
    Settings class to manage environment variables.
    
    Attributes:
        CONF_THRESH (float): Confidence threshold for detections.
        IOU_THRESHOLD (float): IoU threshold for tracking.
        INPUT_SOURCE (str): Input source (CAMERA or FILE).
        VIDEO_PATH (str): Path to video file.
        OUTPUT_WIDTH (int): Output video width.
        OUTPUT_HEIGHT (int): Output video height.
        FPS_OUTPUT (int): Output video FPS.
        DRAW_BOX (bool): Whether to draw bounding boxes.
        LOG_LEVEL (str): Logging level.
    """
    
    def __init__(self):
        """Initialize settings by loading environment variables."""
        load_dotenv(dotenv_path="./.env")
        
        # Inference Parameters
        self.CONF_THRESH = float(os.getenv("CONF_THRESH", 0.5))
        self.IOU_THRESHOLD = float(os.getenv("IOU_THRESHOLD", 0.45))

        # Inference ROI: number of pixels ignored at the top/bottom of the frame
        # (the model only runs on the cropped vertical band)
        self.TOP_IGNORE = int(os.getenv("TOP_IGNORE", 100))
        self.BOTTOM_IGNORE = int(os.getenv("BOTTOM_IGNORE", 50))

        # Input Source
        self.INPUT_SOURCE = os.getenv("INPUT_SOURCE", "CAMERA")
        self.VIDEO_PATH = os.getenv("VIDEO_PATH", "/dev/video0")
        
        # Output Resolution
        self.OUTPUT_WIDTH = int(os.getenv("OUTPUT_WIDTH", 640))
        self.OUTPUT_HEIGHT = int(os.getenv("OUTPUT_HEIGHT", 480))

        # Output Resolution
        self.OUTPUT_SCREEN_WIDTH = int(os.getenv("OUTPUT_SCREEN_WIDTH", 1024))
        self.OUTPUT_SCREEN_HEIGHT = int(os.getenv("OUTPUT_SCREEN_HEIGHT", 600))
        
        # FPS Settings
        self.FPS_OUTPUT = int(os.getenv("FPS_OUTPUT", 30))
        
        # Offset of the counting line in percent
        self.OFFSET_PERCENT_COUNTING_LINE = int(os.getenv("OFFSET_PERCENT_COUNTING_LINE", 10))
        
        # Visualization Options
        self.DRAW_TRACKING = os.getenv("DRAW_TRACKING", "False").lower() == "true"
        self.CENTROID_TRACKING = os.getenv("CENTROID_TRACKING", "True").lower() == "true"
        self.BOX_TRACKING = os.getenv("BOX_TRACKING", "True").lower() == "true"
        
        ### MODIFICATION: Pig Detection Threshold - Start
        # Minimum confidence threshold to consider an object as a pig
        self.PIG_CONFIDENCE_THRESHOLD = float(os.getenv("PIG_CONFIDENCE_THRESHOLD", 0.6))
        self.PIG_CONFIDENCE_THRESHOLD_START_VIDEO = float(os.getenv("PIG_CONFIDENCE_THRESHOLD_START_VIDEO", 0.8))
        ### MODIFICATION: Pig Detection Threshold - End
        
        # Output Video Path
        self.OUTPUT_VIDEO_PATH = os.getenv("OUTPUT_VIDEO_PATH", "/app/output")
        
        # Logging Level
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        ### MODIFICATION: Learning Mode - Start
        # Learning Mode Configuration
        self.DATASET_DIR = os.getenv("DATASET_DIR", "./dataset")
        self.CAPTURE_INTERVAL = int(os.getenv("CAPTURE_INTERVAL", 1))
        self.MAX_LEARNING_DURATION = int(os.getenv("MAX_LEARNING_DURATION", 600))
        ### MODIFICATION: Learning Mode - End

        self.MAX_VIDEO_DURATION = int(os.getenv("MAX_VIDEO_DURATION", 3600))

        ### OC-SORT Tracker tuning (anti ID-switch near counting line) - Start
        # lost_track_buffer: frames a lost track is kept alive (scaled by frame_rate).
        #   Higher = survives longer occlusions at the counting line, BUT too high
        #   lets dead tracks be re-bound to wrong detections and trigger spurious
        #   crossings (over-counting). 20 ≈ 0.67s at 30fps.
        self.TRACKER_LOST_TRACK_BUFFER = int(os.getenv("TRACKER_LOST_TRACK_BUFFER", 20))
        # frame_rate used to scale the lost track buffer into a time-like value.
        self.TRACKER_FRAME_RATE = float(os.getenv("TRACKER_FRAME_RATE", 30.0))
        # minimum_consecutive_frames before a track gets a stable tracker_id.
        #   Higher filters ephemeral tracks (a human walking through, or noise)
        #   that would otherwise get a tracker_id and may cross the line, causing
        #   a false +/-1. 5 ~= 0.17s at 30fps: a real pig crossing the line stays
        #   visible far longer; 3 was too permissive. Raise if ghost tracks persist.
        self.TRACKER_MIN_CONSECUTIVE_FRAMES = int(os.getenv("TRACKER_MIN_CONSECUTIVE_FRAMES", 5))
        # minimum_iou_threshold for detection/track association. Too low creates
        #   wrong re-bindings (spurious crossings / over-counting).
        self.TRACKER_MIN_IOU_THRESHOLD = float(os.getenv("TRACKER_MIN_IOU_THRESHOLD", 0.3))
        # direction_consistency_weight (OCM term).
        self.TRACKER_DIRECTION_CONSISTENCY_WEIGHT = float(os.getenv("TRACKER_DIRECTION_CONSISTENCY_WEIGHT", 0.25))
        # high_conf_det_threshold: detections below this are dropped by the tracker
        #   BEFORE association. Too low feeds noisy/weak detections (conf 0.5-0.6) that
        #   spawn ghost tracks and trigger spurious crossings. 0.6 keeps only
        #   confident pigs; the OCR 2nd-chance still rescues occluded ones.
        self.TRACKER_HIGH_CONF_THRESHOLD = float(os.getenv("TRACKER_HIGH_CONF_THRESHOLD", 0.6))
        # delta_t: temporal window for velocity-direction estimation (OCM).
        self.TRACKER_DELTA_T = int(os.getenv("TRACKER_DELTA_T", 3))
        ### OC-SORT Tracker tuning - End

        ### Counting ID-switch recovery guard - Start
        # When a new track ID appears already past the counting line (left side,
        # right->left direction) AND a recently-lost track existed on the right
        # side near the line, the guard fuses them and triggers the +1 that the
        # ID switch would have missed.
        # LOST_BUFFER_FRAMES is the GLOBAL expiration age of lost_tracks (memory
        #   housekeeping). Keep it LONG (60 ~= 2s) so the guard can still fuse a
        #   lost "in" with a brand-new left-side ID even after a long occlusion at
        #   the line (critical for videos like #35 where many pigs are occluded
        #   >20 frames before the line). Lowering it under-counts.
        # The GUARD's own eligibility age is governed separately by
        #   COUNTING_GUARD_MAX_AGE (short) to avoid fusing with stale lost "in"
        #   tracks belonging to OTHER pigs (the #30 false +1). Decoupling the two
        #   lets #35 (needs long buffer) and #30 (needs short guard age) coexist.
        self.COUNTING_LOST_BUFFER_FRAMES = int(os.getenv("COUNTING_LOST_BUFFER_FRAMES", 60))
        # Lost track must be within this horizontal band of the counting line
        # (in pixels) to be eligible for fusion. Avoids fusing with far tracks.
        self.COUNTING_REASSOC_LINE_BAND = int(os.getenv("COUNTING_REASSOC_LINE_BAND", 200))
        # Max horizontal/vertical distance (pixels) between the new ID and the
        # lost track for fusion.
        self.COUNTING_REASSOC_MAX_DIST_X = int(os.getenv("COUNTING_REASSOC_MAX_DIST_X", 120))
        self.COUNTING_REASSOC_MAX_DIST_Y = int(os.getenv("COUNTING_REASSOC_MAX_DIST_Y", 80))
        # Guard max age: max age (frames) of a lost "in" track ELIGIBLE for the
        #   ID-switch guard fusion. Keep SHORT (15 ~= 0.5s) so a stale lost "in"
        #   belonging to a DIFFERENT pig (or to a pig that already crossed under
        #   another ID) is not fused with a brand-new left-side ID (the #30 / #11
        #   false +1). Distinct from LOST_BUFFER_FRAMES (global expiration).
        self.COUNTING_GUARD_MAX_AGE = int(os.getenv("COUNTING_GUARD_MAX_AGE", 15))
        # Resurrection (Pattern B): an already-known track ID reappearing FAR
        #   from its last position after a brief absence is a re-ID / erroneous
        #   re-association by OC-SORT (e.g. ID=10 lost on the right, then a
        #   detection on the left is re-attached to the same old ID). The
        #   position jump (right->left) would fire a false crossed LEFT (+1).
        #   Trigger on the POSITION JUMP (primary) + a small min absence age
        #   (secondary, to ignore single-frame jitter), and reset the area list
        #   by current position with no count change.
        #   RESURRECTION_MIN_JUMP: min horizontal distance (px) between last and
        #     current position to be a resurrection. A real pig crossing the
        #     line moves only ~1 pig-width (~50-100px) in one frame; a re-ID
        #     jump is hundreds of px. 150 is a safe split.
        #   RESURRECTION_THRESHOLD: min absence age (frames) to consider. Keep
        #     SMALL (5): the jump is the real signal, the age just filters jitter.
        self.COUNTING_RESURRECTION_MIN_JUMP = int(os.getenv("COUNTING_RESURRECTION_MIN_JUMP", 150))
        self.COUNTING_RESURRECTION_THRESHOLD = int(os.getenv("COUNTING_RESURRECTION_THRESHOLD", 5))
        # REID-SUPPRESS: detect a known ID (in area_in, not yet counted) that
        # reappears on the LEFT after an absence, while another ID that APPEARED
        # during its absence recently crossed LEFT - that other ID is a re-ID of
        # the same (already-counted) pig; suppress the +1 (the #35 double-count:
        # ID=10 lost, ID=15 appeared+crossed, ID=10 reappears on left). A
        # legitimate occluded crossing has no other ID appearing during the
        # absence, so it fires normally.
        #   REID_WINDOW: max age (frames) of a crossing to count as recent.
        #   REID_MIN_AGE: min absence (frames) for an ID to be suspicious.
        self.COUNTING_REID_WINDOW = int(os.getenv("COUNTING_REID_WINDOW", 15))
        self.COUNTING_REID_MIN_AGE = int(os.getenv("COUNTING_REID_MIN_AGE", 3))
        ### Counting ID-switch recovery guard - End

        ### Counting hysteresis + mirror guard - Start
        # Hysteresis dead-band (px) around the counting line. A crossing is only
        #   counted when the centroid passes the line by this many pixels.
        #   WARNING: a non-zero value can SWALLOW a legitimate crossed RIGHT
        #   (pig going left->right but staying in the band) and leave its later
        #   crossed LEFT uncompensated = over-count. Keep at 0 unless validated.
        self.COUNTING_HYSTERESIS_PX = int(os.getenv("COUNTING_HYSTERESIS_PX", 0))
        # Mirror guard mode: "off" | "log" | "enforce".
        #   log     - detect & log mirror candidates only (default, no count change)
        #   enforce - suppress the next crossed LEFT of the re-ID'd pig
        self.COUNTING_MIRROR_GUARD = os.getenv("COUNTING_MIRROR_GUARD", "log")
        # Max age (frames) of a lost "out" (left) track eligible for mirror fusion.
        self.COUNTING_MIRROR_MAX_AGE = int(os.getenv("COUNTING_MIRROR_MAX_AGE", 15))
        # Lost "out" track must be within this band (px) of the counting line.
        self.COUNTING_MIRROR_LINE_BAND = int(os.getenv("COUNTING_MIRROR_LINE_BAND", 100))
        # New right-side ID must be within this band (px) of the counting line.
        self.COUNTING_MIRROR_NEW_BAND = int(os.getenv("COUNTING_MIRROR_NEW_BAND", 120))
        # Max vertical distance (px) between the new ID and the lost track.
        self.COUNTING_MIRROR_MAX_DIST_Y = int(os.getenv("COUNTING_MIRROR_MAX_DIST_Y", 60))
        ### Counting hysteresis + mirror guard - End
        