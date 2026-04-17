"""
Counting module for the pig counting application.

This module handles the counting logic based on object crossing a vertical line.
"""

import numpy as np
import logging

logger = logging.getLogger(__name__)


class Counting:
    """
    Counting class to manage object counting logic.
    
    Attributes:
        detections (dict): Dictionary to store detection history.
        trails (dict): Dictionary to store tracking trails.
        area_in_list (list): List to store track IDs in the "in" area.
        area_out_list (list): List to store track IDs in the "out" area.
    """
    
    def __init__(self, shared_state=None, pig_confidence_threshold=0.7):
        """Initialize the counting object."""
        self.detections = {}
        self.trails = shared_state.trails if shared_state else {}
        self.area_in_list = []
        self.area_out_list = []
        self.shared_state = shared_state
        self.pig_confidence_threshold = pig_confidence_threshold
    
    def count(self, image_raw, result_boxes, result_trackid, result_classid, result_scores=None, counting_class=0, counter_to_right=0):
        """
        Count objects crossing a vertical line.
        
        Args:
            image_raw (numpy.ndarray): Original image.
            result_boxes (numpy.ndarray): Detected bounding boxes.
            result_trackid (numpy.ndarray): Track IDs.
            result_classid (numpy.ndarray): Class IDs.
            result_scores (numpy.ndarray, optional): Detection scores. Defaults to None.
            counting_class (int, optional): Class ID to count. Defaults to 0.
            counter_to_right (int, optional): Current count of objects to the right. Defaults to 0.
            
        Returns:
            int: Updated count of objects moving to the right.
        """
        img_height, img_width = image_raw.shape[:2]
        x = img_width // 2
        
        if len(result_boxes) > 0:
            center_x = (result_boxes[:, 0] + result_boxes[:, 2]) / 2
            center_y = (result_boxes[:, 1] + result_boxes[:, 3]) / 2
            current_status = np.column_stack((center_x, center_y, result_trackid, result_classid))
            
            # Add scores to current_status if provided
            if result_scores is not None:
                current_status = np.column_stack((current_status, result_scores))

            for element in current_status:
                track_id = element[2]
                class_id = element[3]
                
                # Skip if the confidence is below the threshold for pig detection
                if result_scores is not None and len(element) > 4 and class_id == 0 and element[4] < self.pig_confidence_threshold:
                    continue
                
                if track_id in self.detections:
                    last_x, last_y = self.detections[track_id][2], self.detections[track_id][3]
                    self.detections[track_id] = [last_x, last_y, element[0], element[1], self.detections[track_id][4]]
                    
                    if self.detections[track_id][2] > x and track_id in self.area_out_list:
                        counter_to_right -= 1
                        logger.info(f"[TRACK] ID={track_id} crossed RIGHT // Count {counter_to_right}")
                        if track_id not in self.area_in_list:
                            self.area_out_list.remove(track_id)
                            self.area_in_list.append(track_id)
                    elif self.detections[track_id][2] <= x and track_id in self.area_in_list:
                        counter_to_right += 1
                        logger.info(f"[TRACK] ID={track_id} crossed LEFT // Count {counter_to_right}")
                        if track_id not in self.area_out_list:
                            self.area_in_list.remove(track_id)
                            self.area_out_list.append(track_id)
                else:
                    last_x, last_y = None, None
                    self.detections[track_id] = [last_x, last_y, element[0], element[1], element[3]]
                    
                    if element[3] == counting_class and track_id not in self.area_in_list and element[0] > x:
                        self.area_in_list.append(track_id)
                    elif element[3] == counting_class and track_id not in self.area_out_list and element[0] <= x:
                        self.area_out_list.append(track_id)

            for element in current_status:
                track_id = element[2]
                cx, cy = element[0], element[1]

                if track_id not in self.trails:
                    self.trails[track_id] = []
                self.trails[track_id].append((int(cx), int(cy)))

                if len(self.trails[track_id]) > 30:
                    self.trails[track_id].pop(0)
        
        return counter_to_right
