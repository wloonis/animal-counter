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
    
    def plot_one_box(self, x, img, color=None, label=None, line_thickness=None):
        """
        Plot one bounding box on the image.
        
        Args:
            x (list): Bounding box coordinates [x1, y1, x2, y2].
            img (numpy.ndarray): Image to plot on.
            color (list, optional): Color for the bounding box. Defaults to random.
            label (str, optional): Label for the bounding box. Defaults to None.
            line_thickness (int, optional): Thickness of the bounding box line. Defaults to 1.
        """
        tl = line_thickness or 1
        color = color or [np.random.randint(0, 255) for _ in range(3)]
        c1, c2 = (int(x[0]), int(x[1])), (int(x[2]), int(x[3]))
        cv2.rectangle(img, c1, c2, color, thickness=tl, lineType=cv2.LINE_AA)
        if label:
            tf = max(tl - 1, 1)
            t_size = cv2.getTextSize(label, 0, fontScale=tl / 3, thickness=tf)[0]
            c2 = c1[0] + t_size[0], c1[1] - t_size[1] - 3
            cv2.rectangle(img, c1, c2, color, -1, cv2.LINE_AA)
            cv2.putText(
                img,
                label,
                (c1[0], c1[1] - 2),
                0,
                tl / 3,
                [225, 255, 255],
                thickness=tf,
                lineType=cv2.LINE_AA,
            )
    
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
            
            color = (0, 255, 0)
            # Draw boundaring box
            if self.shared_state.box_tracking:
                self.plot_one_box(box, image, color, "{}:{}:{:.2f}".format(categories[int(result_classid[j])], str(track_id), result_scores[j]), line_thickness=1)
            
            # Always display the current centroid (regardless of centroid_tracking)
            center = (c_x, c_y)
            color = (255, 255, 0)
            radius = 1
            cv2.circle(image, center, radius, color, thickness=1)

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
    