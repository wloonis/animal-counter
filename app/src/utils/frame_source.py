"""
FrameSource module for the pig counting application.

This module provides a unified interface for frame sources (camera or video file).
"""

import cv2


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
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            # pipeline = (
            #     "v4l2src device=/dev/video0 ! "
            #     "video/x-raw, width=640, height=480, framerate=30/1 ! "
            #     "nvvidconv ! "
            #     "video/x-raw, format=BGRx ! "
            #     "videoconvert ! "
            #     "video/x-raw, format=BGR ! appsink drop=true"
            # )
            # self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
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
