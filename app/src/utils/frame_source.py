"""
FrameSource module for the pig counting application.

This module provides a unified interface for frame sources (camera or video file).
"""

import cv2
from settings import Settings

# Load settings
settings = Settings()

class FrameSource:
    """
    Unified interface for frame sources (camera or video file).
    
    Attributes:
        cap (cv2.VideoCapture): OpenCV video capture object.
        source (str): Source path (camera or video file).
        input_type (str): Type of input (CAMERA or FILE).
    """
    
    def __init__(self, source, input_type="CAMERA"):
        """
        Initialize the frame source.
        
        Args:
            source (str): Source path (camera or video file).
            input_type (str): Type of input (CAMERA or FILE).
        """
        self.source = source
        self.input_type = input_type
        
        if input_type == "CAMERA":
            self.cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'mp4v'))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.OUTPUT_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.OUTPUT_HEIGHT)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
        else:
            self.cap = cv2.VideoCapture(source)
        
        if not self.cap.isOpened():
            raise ValueError(f"Error opening video source: {source}")
    
    def read(self):
        """
        Read a frame from the source.
        
        Returns:
            tuple: Ret (bool), frame (numpy.ndarray).
        """
        ret, frame = self.cap.read()
        return ret, frame
    
    def release(self):
        """Release the video capture object."""
        self.cap.release()
    
    def get_fps(self):
        """
        Get the FPS of the video source.
        
        Returns:
            float: FPS of the video source.
        """
        return self.cap.get(cv2.CAP_PROP_FPS)
