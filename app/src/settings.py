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
        
        # Visualization Options
        self.DRAW_TRACKING = os.getenv("DRAW_TRACKING", "True").lower() == "true"
        self.CENTROID_TRACKING = os.getenv("CENTROID_TRACKING", "True").lower() == "true"
        self.BOX_TRACKING = os.getenv("BOX_TRACKING", "True").lower() == "true"
        
        ### MODIFICATION: Pig Detection Threshold - Start
        # Minimum confidence threshold to consider an object as a pig
        self.PIG_CONFIDENCE_THRESHOLD = float(os.getenv("PIG_CONFIDENCE_THRESHOLD", 0.7))
        self.PIG_CONFIDENCE_THRESHOLD_START_VIDEO = float(os.getenv("PIG_CONFIDENCE_THRESHOLD_START_VIDEO", 0.8))
        ### MODIFICATION: Pig Detection Threshold - End
        
        # Output Video Path
        self.OUTPUT_VIDEO_PATH = os.getenv("OUTPUT_VIDEO_PATH", "/app/output")
        
        # Logging Level
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
        ### MODIFICATION: Learning Mode - Start
        # Learning Mode Configuration
        self.DATASET_DIR = os.getenv("DATASET_DIR", "./dataset")
        self.CAPTURE_INTERVAL = int(os.getenv("CAPTURE_INTERVAL", 5))
        self.MAX_LEARNING_DURATION = int(os.getenv("MAX_LEARNING_DURATION", 600))
        ### MODIFICATION: Learning Mode - End

        self.MAX_VIDEO_DURATION = int(os.getenv("MAX_VIDEO_DURATION", 3600))
        