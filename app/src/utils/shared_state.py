"""
SharedState module for the pig counting application.

This module provides a shared state object to replace global variables.
"""

import datetime
from queue import Queue
from threading import Event

class SharedState:
    """
    Shared state object to replace global variables.
    
    Attributes:
        status (int): Application status (0: Stopped, 1: Started, 2: Paused).
        recording (bool): Whether recording is in progress.
        counter_to_right (int): Count of objects moving to the right.
        frame_queue (Queue): Queue for frame processing.
        draw_tracking (bool): Whether to draw tracking.
        infer_thread (InferThread): Thread for inference.
        display_thread (DisplayThread): Thread for display and counting.
        delay_reinit (datetime): Delay for reinitialization.
    """
    
    def __init__(self):
        """Initialize the shared state."""
        self.status = 3
        self.recording = False
        self.counter_to_right = 0
        self.frame_queue = Queue(maxsize=10)
        self.draw_tracking = True
        self.centroid_tracking = True
        self.box_tracking = True
        self.infer_thread = None
        self.display_thread = None
        self.delay_reinit = datetime.datetime.now()
        self.delay_last_class = 180
        self.trails = {}
        ### MODIFICATION: Learning Mode - Start
        self.learning_mode = False
        self.learning_start_time = None
        self.max_learning_duration = 1200
        self.max_video_duration = 3600
        self.image_counter = 0  # Counter for captured images
        ### MODIFICATION: Learning Mode - End
        ### MODIFICATION: Auto Mode - Start
        self.auto_mode = True
        self.reset = False
        ### MODIFICATION: Learning Mode - End
        self.stop_event = Event()
