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
        # BL-58: per-track-id color cache. Maps track_id -> stable BGR tuple so
        # the same id always gets the same colour, making ID switches on the same
        # pig visible as an abrupt colour change of its bounding box.
        self._color_cache = {}
    

    def _track_color(self, track_id):
        """
        Return a stable, well-contrasted BGR colour for a given track id.

        Primary purpose (BL-58): visually detect ID jumps / ID switches on the
        same pig. A pig that keeps its id keeps one box colour; if OC-SORT
        re-IDs it mid-crossing the box colour changes abruptly - an at-a-glance
        cue for ID-switch defects.

        The hue is derived from a hash of the id spread across the full 0-179
        OpenCV hue range so adjacent ids get visibly different colours. Results
        are cached so the same id always maps to the same colour.
        """
        tid = int(track_id)
        if tid in self._color_cache:
            return self._color_cache[tid]
        # Spread ids across the full hue range (0-179 in OpenCV's HSV).
        # Using a large multiplier + modulo avoids sequential ids landing on
        # adjacent (nearly identical) hues.
        hue = (tid * 47) % 180
        sat = 200   # vivid but not pure (good contrast on varied backgrounds)
        val = 220   # bright
        # cv2.cvtColor expects uint8 HSV; single pixel.
        hsv_pixel = np.uint8([[[hue, sat, val]]])
        bgr = cv2.cvtColor(hsv_pixel, cv2.COLOR_HSV2BGR)[0][0]
        color = (int(bgr[0]), int(bgr[1]), int(bgr[2]))
        self._color_cache[tid] = color
        return color

    @staticmethod
    def _luminance(color):
        """Relative luminance of a BGR colour (0-255)."""
        b, g, r = color[0], color[1], color[2]
        return 0.299 * r + 0.587 * g + 0.114 * b

    def _label_text_color(self, bg_color):
        """Choose black or white text for best contrast on bg_color."""
        return (0, 0, 0) if self._luminance(bg_color) > 140 else (255, 255, 255)

    def plot_one_box(self, x, img, color=None, label=None, line_thickness=None):
        """
        Plot one bounding box on the image (BL-58 readability refactor).

        Improvements over the previous version:
          - thicker box outline (configurable via settings, default 2 vs 1)
          - label drawn with a fixed readable fontScale (default 0.6 vs tl/3=0.33)
          - semi-opaque background behind the label (alpha blend) instead of a
            solid fill in the box colour
          - black text outline under the foreground text for contrast on any
            background
          - text colour chosen by luminance of the box colour
          - a few px of padding around the label
          - label placed above the box, or below it if too close to the top of
            the frame

        Args:
            x (list): Bounding box coordinates [x1, y1, x2, y2].
            img (numpy.ndarray): Image to plot on.
            color (list, optional): BGR color for the bounding box.
            label (str, optional): Label text for the bounding box.
            line_thickness (int, optional): Thickness of the bounding box line.
                Defaults to the shared_state draw setting (2).
        """
        # Resolve render settings (fall back to sensible defaults if shared_state
        # is unavailable, e.g. in unit tests).
        ss = self.shared_state
        default_tl = getattr(ss, "draw_box_line_thickness", 2) if ss else 2
        font_scale = getattr(ss, "draw_label_font_scale", 0.6) if ss else 0.6
        tf = getattr(ss, "draw_label_thickness", 2) if ss else 2

        tl = line_thickness or default_tl
        color = color or [np.random.randint(0, 255) for _ in range(3)]
        color = [int(c) for c in color]
        c1, c2 = (int(x[0]), int(x[1])), (int(x[2]), int(x[3]))
        cv2.rectangle(img, c1, c2, color, thickness=tl, lineType=cv2.LINE_AA)

        if label:
            font = cv2.FONT_HERSHEY_SIMPLEX
            (tw, th), _ = cv2.getTextSize(label, font, fontScale=font_scale,
                                          thickness=tf)
            pad = 4  # px padding around the label text
            bg_w = tw + 2 * pad
            bg_h = th + 2 * pad

            img_h = img.shape[0]
            # Default: label sits above the box. If it would go off the top of the
            # frame, place it just below the box top instead.
            if c1[1] - bg_h - 2 >= 0:
                bg_x1 = c1[0]
                bg_y1 = c1[1] - bg_h - 2
            else:
                bg_x1 = c1[0]
                bg_y1 = c1[1] + 2
            bg_x2 = bg_x1 + bg_w
            bg_y2 = bg_y1 + bg_h

            # Clip to frame bounds to avoid drawing outside the image.
            bg_x1c = max(bg_x1, 0)
            bg_y1c = max(bg_y1, 0)
            bg_x2c = min(bg_x2, img.shape[1])
            bg_y2c = min(bg_y2, img_h)

            # Semi-opaque background: blend a dark rectangle (alpha ~0.6) over
            # the label region only (cheap - bounded to the label box).
            overlay = img.copy()
            cv2.rectangle(overlay, (bg_x1c, bg_y1c), (bg_x2c, bg_y2c),
                          (0, 0, 0), -1, cv2.LINE_AA)
            alpha = 0.6
            cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, dst=img)

            # The label sits on a semi-opaque DARK background (the black overlay
            # blended above), NOT on the box colour. Choosing the text colour
            # from the box colour made the text BLACK on bright track colours
            # (val=220) -> dark/illegible ID+score (BL-58 follow-up). Base the
            # text colour on the actual dark label background so the foreground
            # is always bright (white) with the black outline for crisp edges.
            txt_color = self._label_text_color((0, 0, 0))
            text_org = (bg_x1 + pad, bg_y1 + pad + th)

            # Black outline (draw the text shifted in 4 directions) for a crisp
            # edge on any background, then the foreground text on top.
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                cv2.putText(img, label, (text_org[0] + dx, text_org[1] + dy),
                            font, font_scale, (0, 0, 0), thickness=tf,
                            lineType=cv2.LINE_AA)
            cv2.putText(img, label, text_org, font, font_scale, txt_color,
                        thickness=tf, lineType=cv2.LINE_AA)
    
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
            # Draw bounding box with the new label format: ID first, score second.
            if self.shared_state.box_tracking:
                label = "ID:{} {:.2f}".format(int(track_id), float(result_scores[j]))
                self.plot_one_box(box, image, color, label,
                                  line_thickness=self.shared_state.draw_box_line_thickness)

            # Always display the current centroid (regardless of centroid_tracking):
            # filled, larger, and coloured to match the track id for visibility.
            center = (c_x, c_y)
            radius = self.shared_state.draw_centroid_radius
            cv2.circle(image, center, radius, color, thickness=-1, lineType=cv2.LINE_AA)

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
    