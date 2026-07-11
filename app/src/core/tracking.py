# Pig tracking module.
# Wraps the Norfair tracker to follow detected pigs across video frames and
# assign persistent track IDs for downstream counting and visualization.
"""
Tracking module for the pig counting application.

This module handles object tracking using the Norfair library.
"""

import numpy as np
import cv2
import logging

logger = logging.getLogger(__name__)


class Tracking:
    """
    Tracking class to manage object tracking and counting.
    
    Attributes:
        detections (dict): Dictionary to store detection history.
        trails (dict): Dictionary to store tracking trails.
        count_drawings (list): List to store count drawings.
        area_in_list (list): List to store track IDs in the "in" area.
        area_out_list (list): List to store track IDs in the "out" area.
    """
    
    def __init__(self, draw_box=False, shared_state=None):
        """Initialize the tracking object."""
        self.detections = {}
        self.trails = shared_state.trails if shared_state else {}
        self.count_drawings = []
        self.area_in_list = []
        self.area_out_list = []
        self.draw_tracking = draw_box
        self.shared_state = shared_state
        self.prev_positions = {}
        self.MAX_JUMP = 20  # à ajuster selon ta résolution
        self.active_ids = set()
        self.lost_tracks = {}
        self.MAX_LOST_FRAMES = 30      # ~1 seconde à 30 fps
        self.MAX_REASSOCIATE_DIST = 40 # à ajuster
        self.frame_counter = 0
        self._color_cache = {}
    
    def _track_color(self, track_id):
        """
        Deterministic HSV-hash → BGR color palette keyed by track_id.
        
        Returns a BGR tuple that is stable for a given track_id across all
        frames.  Avoids hues near pure green (35°–85° in OpenCV HSV, which
        corresponds to ~70°–170° standard) to ensure contrast on grass
        backgrounds.
        
        Args:
            track_id: Track identifier (int or hashable).
            
        Returns:
            tuple: BGR color tuple (int, int, int).
        """
        # Return cached color if already computed (perf: avoid cvtColor every frame)
        if track_id in self._color_cache:
            return self._color_cache[track_id]
        
        # Deterministic hash → hue value in OpenCV's 0-179 range.
        # Prime multiplier (47) gives good hue distribution across small
        # sequential track IDs (1, 2, 3, …) instead of clustering near 0°.
        raw = int(track_id)
        hue = (raw * 47) % 180
        
        # Avoid green band (35-85 in OpenCV HSV ≈ 70°-170° standard).
        # Shift hues in this band to the opposite side of the hue wheel
        # for grass contrast.
        if 35 <= hue <= 85:
            hue = (hue + 100) % 180
        
        # High saturation and mid-to-high value for vibrant, visible colors.
        saturation = 220
        value = 200
        
        # Convert HSV → BGR using cv2.cvtColor on a 1×1 numpy array.
        hsv_color = np.uint8([[[hue, saturation, value]]])
        bgr_color = cv2.cvtColor(hsv_color, cv2.COLOR_HSV2BGR)[0][0]
        
        result = (int(bgr_color[0]), int(bgr_color[1]), int(bgr_color[2]))
        self._color_cache[track_id] = result
        return result
    
    def plot_one_box(self, x, img, color=None, label_id=None, label_score=None, line_thickness=None):
        """
        Plot one bounding box on the image with an improved visual style.
        
        Draws:
        (a) A 1px dark outline rectangle behind the colored stroke for
            contrast on any background.
        (b) A colored anti-aliased rectangle at ``line_thickness``.
        (c) A dark semi-transparent rounded badge above the box (flipped
            below if near the frame top) sized to fit the label text.
        (d) ``label_id`` text (e.g. "#12") in a larger fontScale and
            thicker stroke (simulated bold).
        (e) ``label_score`` text (e.g. "0.87") smaller and thinner to the
            right of the ID.
        (f) A 1px shadow offset on text for contrast.
        
        All coordinates are clamped to frame bounds.
        
        Args:
            x (list): Bounding box coordinates [x1, y1, x2, y2].
            img (numpy.ndarray): Image to plot on.
            color (tuple, optional): BGR color for the bounding box. Defaults to random.
            label_id (str, optional): Track ID label (e.g. "#12"). Drawn larger/bold.
            label_score (str, optional): Match score label (e.g. "0.87"). Drawn smaller.
            line_thickness (int, optional): Thickness of the bounding box line. Defaults to 2.
        """
        tl = line_thickness or 2
        color = color or [np.random.randint(0, 255) for _ in range(3)]
        color = tuple(int(c) for c in color)
        
        c1, c2 = (int(x[0]), int(x[1])), (int(x[2]), int(x[3]))
        h, w = img.shape[:2]
        
        # (a) Dark outline for contrast on any background
        cv2.rectangle(img, c1, c2, (0, 0, 0), thickness=tl + 2, lineType=cv2.LINE_AA)
        # (b) Colored anti-aliased rectangle
        cv2.rectangle(img, c1, c2, color, thickness=tl, lineType=cv2.LINE_AA)
        
        if label_id or label_score:
            # Font settings
            font = cv2.FONT_HERSHEY_SIMPLEX
            id_scale = 0.55
            score_scale = 0.40
            id_thickness = max(tl, 2)
            score_thickness = 1
            
            # Measure text sizes
            id_text = label_id or ""
            score_text = label_score or ""
            id_size = cv2.getTextSize(id_text, font, id_scale, id_thickness)[0]
            score_size = cv2.getTextSize(score_text, font, score_scale, score_thickness)[0]
            
            # Gap between ID and score text
            gap = 8
            # Total text width
            total_w = id_size[0] + (gap + score_size[0] if score_text else 0)
            max_h = max(id_size[1], score_size[1] if score_text else 0)
            
            # Badge padding
            pad_x = 6
            pad_y = 4
            
            badge_w = total_w + 2 * pad_x
            badge_h = max_h + 2 * pad_y
            
            # Badge position: above the box by default
            badge_x1 = c1[0]
            badge_y1 = c1[1] - badge_h - 2
            
            # Flip below if badge would overflow the top of the frame
            if badge_y1 < 0:
                badge_y1 = c2[1] + 2
            
            badge_x2 = badge_x1 + badge_w
            badge_y2 = badge_y1 + badge_h
            
            # Clamp to frame bounds (shift position, keep dimensions)
            if badge_x2 > w:
                badge_x1 = max(0, w - badge_w)
                badge_x2 = badge_x1 + badge_w
            if badge_x1 < 0:
                badge_x1 = 0
                badge_x2 = min(badge_w, w)
            if badge_y2 > h:
                badge_y1 = max(0, h - badge_h)
                badge_y2 = badge_y1 + badge_h
            if badge_y1 < 0:
                badge_y1 = 0
                badge_y2 = min(badge_h, h)
            
            # (c) Dark semi-transparent badge via addWeighted on sub-ROI
            if badge_x2 > badge_x1 and badge_y2 > badge_y1:
                roi = img[badge_y1:badge_y2, badge_x1:badge_x2]
                if roi.size > 0:
                    dark_overlay = np.zeros_like(roi)
                    alpha = 0.65  # dark overlay opacity
                    blended = cv2.addWeighted(roi, 1.0 - alpha, dark_overlay, alpha, 0)
                    img[badge_y1:badge_y2, badge_x1:badge_x2] = blended
            
            # Text position inside the badge
            text_y = badge_y1 + pad_y + id_size[1]
            id_x = badge_x1 + pad_x
            
            # (f) Shadow offset for contrast
            shadow_offset = 1
            shadow_color = (0, 0, 0)
            text_color = (255, 255, 255)
            
            # (d) #ID text — larger, thicker (simulated bold)
            if id_text:
                cv2.putText(img, id_text, (id_x + shadow_offset, text_y + shadow_offset),
                            font, id_scale, shadow_color, id_thickness, cv2.LINE_AA)
                cv2.putText(img, id_text, (id_x, text_y),
                            font, id_scale, text_color, id_thickness, cv2.LINE_AA)
            
            # (e) Score text — smaller, thinner, to the right of ID
            if score_text:
                score_x = id_x + id_size[0] + gap
                score_y = text_y  # same baseline
                cv2.putText(img, score_text, (score_x + shadow_offset, score_y + shadow_offset),
                            font, score_scale, shadow_color, score_thickness, cv2.LINE_AA)
                cv2.putText(img, score_text, (score_x, score_y),
                            font, score_scale, text_color, score_thickness, cv2.LINE_AA)
    
    def undo_letterbox(self, box, origin_h, origin_w, input_h, input_w):
        x1, y1, x2, y2 = box
        r_w = input_w / origin_w
        r_h = input_h / origin_h

        if r_h > r_w:  # padding top/bottom
            scale = r_w
            pad_y = (input_h - scale * origin_h) / 2
            x1 /= scale
            x2 /= scale
            y1 = (y1 - pad_y) / scale
            y2 = (y2 - pad_y) / scale
        else:  # padding left/right
            scale = r_h
            pad_x = (input_w - scale * origin_w) / 2
            x1 = (x1 - pad_x) / scale
            x2 = (x2 - pad_x) / scale
            y1 /= scale
            y2 /= scale

        return [x1, y1, x2, y2]

    def draw_counter(self, image, result_boxes, result_scores, result_classid, result_trackid, frame_counter, categories=['pig']):
        """
        Draw counting results on the image.
        
        Args:
            image (numpy.ndarray): Image to draw on.
            result_boxes (numpy.ndarray): Detected bounding boxes.
            result_scores (numpy.ndarray): Detection scores.
            result_classid (numpy.ndarray): Class IDs.
            result_trackid (numpy.ndarray): Track IDs.
            frame_counter (int): Current frame counter.
            categories (list, optional): List of category names. Defaults to ['pig'].
        """
        for j in range(len(result_boxes)):
            track_id = result_trackid[j]

            box = result_boxes[j]
            c_x, c_y = self.calculate_center(bbox=box)
            
            color = self._track_color(track_id)
            # Draw boundaring box
            if self.shared_state.box_tracking:
                self.plot_one_box(
                    box, image, color,
                    label_id="#{}".format(str(track_id)),
                    label_score="{:.2f}".format(result_scores[j]),
                    line_thickness=2,
                )
            
            # Always display the current centroid (regardless of centroid_tracking)
            center = (c_x, c_y)
            color = (255, 255, 0)
            dot_color = self._track_color(track_id)
            radius = 3
            cv2.circle(image, center, radius, dot_color, thickness=-1)

            if self.shared_state.centroid_tracking:
                # historique des positions
                if track_id not in self.prev_positions:
                    self.prev_positions[track_id] = c_x
                    # continue

                prev_x = self.prev_positions[track_id]

                if abs(c_x - prev_x) <= self.MAX_JUMP:
                    self.prev_positions[track_id] = c_x
    
                # update position
                self.prev_positions[track_id] = c_x

                # Display trails only if centroid_tracking is True
                if track_id in self.trails and len(self.trails[track_id]) > 1:
                    for k in range(1, len(self.trails[track_id])):
                        cv2.line(image, self.trails[track_id][k-1], self.trails[track_id][k], color, 1)
    
    def calculate_center(self, bbox):
        """
        Calculate the center of a bounding box.
        
        Args:
            bbox (list): Bounding box coordinates [x1, y1, x2, y2].
            
        Returns:
            tuple: Center coordinates (x, y).
        """
        x1, y1, x2, y2 = bbox
        center_x = int((x1 + x2) / 2)
        center_y = int((y1 + y2) / 2)
        return center_x, center_y
