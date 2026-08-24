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

        # Input (capture) Resolution — BL-93 legacy env fallbacks. Used by
        #   state.resolve_input_config() ONLY when the active model's section in
        #   runtime-settings.json has no input_width/input_height (pre-BL-93
        #   deploys, byte-identical legacy behavior). Decoupled from OUTPUT_* (the
        #   writer stays at OUTPUT_* 640x480 with the PR #129 resize); the
        #   per-model resolver overrides these at startup when present.
        self.INPUT_WIDTH = int(os.getenv("INPUT_WIDTH", 640))
        self.INPUT_HEIGHT = int(os.getenv("INPUT_HEIGHT", 480))

        # Output Resolution
        self.OUTPUT_SCREEN_WIDTH = int(os.getenv("OUTPUT_SCREEN_WIDTH", 1024))
        self.OUTPUT_SCREEN_HEIGHT = int(os.getenv("OUTPUT_SCREEN_HEIGHT", 600))
        
        # FPS Settings
        self.FPS_OUTPUT = int(os.getenv("FPS_OUTPUT", 30))
        
        # Offset of the counting line in percent (now SIGNED — negative moves
        # the line toward the start edge). Loose sanity range only; the
        # AUTHORITATIVE bound is the line staying inside the image with a 200px
        # margin on both edges along the crossing axis, enforced by clamping the
        # computed position at use-time in counting.py/rendering.py (frame size
        # is only known at runtime). Default 0 = centered on a fresh deploy
        # (vertical line x = W/2; horizontal line y = H/2). Existing 0..100
        # values stay valid.
        self.OFFSET_PERCENT_COUNTING_LINE = int(os.getenv("OFFSET_PERCENT_COUNTING_LINE", 0))

        # Counting line orientation (BL-83): "vertical" (default = today's
        # behavior, line is a vertical X position, pigs cross right->left) or
        # "horizontal" (line is a horizontal Y position, pigs cross down->up).
        # The +1 convention is preserved for both orientations: +1 fires when
        # the crossing-axis position DECREASES past the line.
        #   vertical   : +1 = right->left = LEFT ; -1 = left->right = RIGHT
        #   horizontal : +1 = down->up   = UP    ; -1 = up->down   = DOWN
        # The crossing axis (perpendicular to the line) vs. along-line axis
        # mapping is: vertical cross=x/along=y ; horizontal cross=y/along=x.
        # Hot-reloaded per-recording from /conf/runtime-settings.json (same
        # "next recording" semantics as OFFSET_PERCENT_COUNTING_LINE).
        _orient = os.getenv("COUNTING_LINE_ORIENTATION", "vertical").strip().lower()
        if _orient not in ("vertical", "horizontal"):
            _orient = "vertical"
        self.COUNTING_LINE_ORIENTATION = _orient

        # BL-92 configurable +1 counting direction. Two GLOBAL keys (not
        # per-model): the +1 direction is tied to camera/video placement, not
        # the model.
        #   counting_direction_mode: "auto" (default) auto-detect the dominant
        #     raw-physical crossing direction per run via a warm-up (N=3
        #     crossings or T=10s) then lock; "manual" = operator-set +1.
        #   counting_direction: manual-only +1 direction, one of up|down|left|
        #     right. Validated at use-time vs the active
        #     COUNTING_LINE_ORIENTATION (horizontal -> up/down, vertical ->
        #     left/right); reject+WARN on mismatch -> fall back to None.
        # Both are hot-reloaded at idle (BL-86); a counting_direction change
        # resets the counter (like counting_class_ids). Default auto with a
        # None direction = byte-identical BL-83 behavior (vertical -> +1=LEFT,
        # horizontal -> +1=UP).
        _mode = os.getenv("COUNTING_DIRECTION_MODE", "auto").strip().lower()
        if _mode not in ("auto", "manual"):
            _mode = "auto"
        self.COUNTING_DIRECTION_MODE = _mode
        _dir = os.getenv("COUNTING_DIRECTION", None)
        if _dir is not None and _dir.strip():
            _dir = _dir.strip().lower()
            if _dir not in ("up", "down", "left", "right"):
                _dir = None
        else:
            _dir = None
        self.COUNTING_DIRECTION = _dir
        # Visualization Options
        self.DRAW_TRACKING = os.getenv("DRAW_TRACKING", "False").lower() == "true"
        self.CENTROID_TRACKING = os.getenv("CENTROID_TRACKING", "True").lower() == "true"
        self.BOX_TRACKING = os.getenv("BOX_TRACKING", "True").lower() == "true"
        # BL-87 detection-level exclusion zones: normalized axis-aligned rects
        # {x,y,w,h} in [0..1]. Detections whose centroid falls inside any rect
        # are dropped in post_process before OC-SORT (no track -> no count).
        # Default [] = no-op (byte-identical current behavior). Hot-reloaded at
        # idle via the BL-86 watcher (no pod restart). Independent of the other
        # draw_* toggles.
        self.MASK_ZONES = []
        self.DRAW_MASK_ZONES = os.getenv("DRAW_MASK_ZONES", "True").lower() == "true"

        ### Bounding-box render tuning (BL-58 visual readability) - Start
        # These control ONLY the on-screen drawing of boxes/labels/centroids.
        # They have zero effect on counting / tracking / OC-SORT logic.
        # Thickness of the bounding-box outline (was hardcoded 1 -> barely visible).
        self.DRAW_BOX_LINE_THICKNESS = int(os.getenv("DRAW_BOX_LINE_THICKNESS", 2))
        # Font scale for the track-id / score label (was tl/3 = 0.33 -> tiny).
        self.DRAW_LABEL_FONT_SCALE = float(os.getenv("DRAW_LABEL_FONT_SCALE", 0.6))
        # Thickness of the label text stroke (was max(tl-1,1) = 1).
        self.DRAW_LABEL_THICKNESS = int(os.getenv("DRAW_LABEL_THICKNESS", 2))
        # Radius of the centroid marker (was 1 -> nearly invisible).
        self.DRAW_CENTROID_RADIUS = int(os.getenv("DRAW_CENTROID_RADIUS", 3))
        ### Bounding-box render tuning (BL-58 visual readability) - End
        
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
        # iou: association similarity function passed to OCSORTTracker (trackers
        #   >= 2.5.0, pluggable via the iou= kwarg).
        #   "giou" = Generalized IoU. ACTIVATED by default to target the ID-switch
        #     problem: GIoU rewards geometric overlap AND penalizes non-overlapping
        #     boxes, which helps keep a pig's ID through partial occlusions at the
        #     counting line (our primary defect cause). Score range [-1, 1].
        #     NOTE: [-1,1] != [0,1] (standard IoU), so TRACKER_MIN_IOU_THRESHOLD
        #     (0.3) may need re-tuning on the GIoU scale; if validation regresses,
        #     lower it toward 0.2-0.3 and re-validate (see docs/04_configuration.md).
        #   "iou" = standard IoU. IDENTICAL to the pre-2.5.0 (2.4.0) association
        #     behavior; the safe revert target if GIoU regresses on this dataset.
        #   (Other variants: ciou/diou/eiou - not evaluated for this use case.)
        self.COUNTING_TRACKER_IOU = os.getenv("COUNTING_TRACKER_IOU", "giou")
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

        ### Counting history (BL-68) - Start
        # Append-only JSONL counting-session history written read-only from the
        # countingapp pod onto the hostPath /files, with an in-process history
        # thread (heartbeat + compaction) resilient to power cuts, bounded to
        # ~200 MB on the small SSD. History is serve-mode only (RESULT_JSON_PATH
        # unset); validate/test mode never writes history.
        # Path of the JSONL history file inside the pod. The pod mounts the
        #   hostPath /files (host: /data/orin/files) read-write, so the writer
        #   appends here; the companion host service reads the same file read-only
        #   at /data/orin/files/counting-history.jsonl.
        self.HISTORY_FILE = os.getenv("HISTORY_FILE", "/files/counting-history.jsonl")
        # Retention window for the 2-level compaction: sessions younger than this
        #   (in days) are kept raw (hot); older sessions (cold) are collapsed to a
        #   single summary line + significant events, dropping heartbeats.
        self.HISTORY_RETENTION_DAYS = int(os.getenv("HISTORY_RETENTION_DAYS", 30))
        # Hard size cap on the live JSONL. Compaction + rotation keep the file
        #   under this; 200 MB is the budget on the small SSD.
        self.HISTORY_MAX_BYTES = int(os.getenv("HISTORY_MAX_BYTES", 200 * 1024 * 1024))
        # Heartbeat interval (seconds) in the normal-disk case: the history thread
        #   appends a heartbeat line (count + last video segment) and fsyncs it.
        #   Adjusted up to 30s by the disk guard when free space drops below
        #   HISTORY_DISK_WARN_GB; writes are suspended below HISTORY_DISK_CRIT_GB.
        self.HISTORY_HEARTBEAT_S = int(os.getenv("HISTORY_HEARTBEAT_S", 5))
        # Disk guard thresholds (GB free on the /files volume). WARN -> heartbeat
        #   interval raised to 30s; CRIT -> writes suspended (counting continues) +
        #   a disk_warning event is emitted.
        self.HISTORY_DISK_WARN_GB = float(os.getenv("HISTORY_DISK_WARN_GB", 2))
        self.HISTORY_DISK_CRIT_GB = float(os.getenv("HISTORY_DISK_CRIT_GB", 0.5))
        # Rotation: when the live JSONL exceeds this size, the cold portion is
        #   gzip-archived to counting-history.<ts>.jsonl.gz to keep the live file
        #   small and cheap to scan.
        self.HISTORY_ROTATE_BYTES = int(os.getenv("HISTORY_ROTATE_BYTES", 10 * 1024 * 1024))
        # Maximum number of gz archives kept; the oldest is deleted beyond this.
        self.HISTORY_ARCHIVE_MAX = int(os.getenv("HISTORY_ARCHIVE_MAX", 20))
        ### Counting history (BL-68) - End

        ### Snapshot writer (BL-88) - Start
        # Display-infra boot params (NOT /conf runtime-settings — not hot-reloaded).
        #   The writer lives in display_thread.py and periodically writes a JPEG
        #   snapshot of the raw counting-resolution frame to SNAPSHOT_PATH so the
        #   companion GET /api/snapshot (BL-88, PR #19) can serve a live preview
        #   to the Android app's visual mask-zone editor. Default ON so the feature
        #   works out-of-the-box; toggle via env (pod restart).
        self.SNAPSHOT_ENABLED = os.getenv("SNAPSHOT_ENABLED", "true").lower() == "true"
        self.SNAPSHOT_INTERVAL_SECONDS = float(os.getenv("SNAPSHOT_INTERVAL_SECONDS", 5.0))
        self.SNAPSHOT_PATH = os.getenv("SNAPSHOT_PATH", "/files/snapshot.jpg")
        self.SNAPSHOT_JPEG_QUALITY = int(os.getenv("SNAPSHOT_JPEG_QUALITY", 85))
        ### Snapshot writer (BL-88) - End

        ### Model class catalog (BL-78) - Start
        # Env-backed FALLBACKS only — used when classes.yaml is absent (legacy
        # deployed models). At runtime, app/model/classes.yaml (captured at
        # build by build_model.yml) is the source of truth and overrides these
        # via state.load_classes_yaml(); main.py populates shared_state.class_names
        # / default_counting_class / model_version from it. The fallbacks below
        # reproduce the exact pre-BL-78 hardcoded behavior (['human','pig'], 1).
        _names_env = os.getenv("CLASS_NAMES", "human,pig")
        self.CLASS_NAMES = [s.strip() for s in _names_env.split(",") if s.strip()]
        if len(self.CLASS_NAMES) == 0:
            self.CLASS_NAMES = ["human", "pig"]
        self.DEFAULT_COUNTING_CLASS = int(os.getenv("DEFAULT_COUNTING_CLASS", 1))
        ### Model class catalog (BL-78) - End
        