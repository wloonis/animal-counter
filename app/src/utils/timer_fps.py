"""
TimerFps module for the pig counting application.

This module provides a timer class to calculate and display FPS.
"""

import time


class TimerFps:
    """
    Timer class to calculate and display FPS.
    
    Attributes:
        sum_time (float): Sum of frame processing times.
        avg_time (float): Average frame processing time.
        time_before (float): Previous frame timestamp.
    """
    
    def __init__(self):
        """Initialize the timer."""
        self.sum_time = 0.0
        self.avg_time = 0.0
        self.time_before = None
    
    def update(self, frame_counter):
        """
        Update the timer with the current frame processing time.
        
        Args:
            frame_counter (int): Current frame counter.
            
        Returns:
            tuple: Current time, average time, and FPS.
        """
        time_now = time.time()
        current_time = 0.0
        fps = 0.0
        if self.time_before is not None:
            current_time = time_now - self.time_before
            self.sum_time += current_time
            self.avg_time = self.sum_time / frame_counter
            fps = 1 / (self.avg_time)
        self.time_before = time_now
        return current_time, self.avg_time, fps
