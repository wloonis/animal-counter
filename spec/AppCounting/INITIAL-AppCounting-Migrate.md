FEATURE:
Refactor and improve a real-time pig counting application based on TensorRT and Norfair tracking (JETSON ORIN NANO And JetPack 6.1).

The application currently works well in production but requires improvements in:

* Code readability and maintainability (clean architecture, separation of concerns)
* Documentation (full English docstrings and comments)
* Configuration management via `.env`
* Input handling (camera vs video file)
* Video resolution normalization
* Logging strategy (levels, performance, consistency)

The goal is to transform the current prototype into a clean, production-ready, scalable codebase.

EXAMPLES:
The current implementation includes:

* A threaded pipeline (InferThread + DisplayThread)
* YOLOv7 TensorRT inference
* Norfair-based tracking
* Custom counting logic based on object crossing a vertical line

Example behaviors:

1. Camera mode:

   * Captures frames from `/dev/video0`
   * Applies real-time inference and tracking
   * Displays and records counting results

2. File mode:

   * Reads a video file
   * Processes frames sequentially
   * Outputs a processed video with overlays and counting

3. Tracking visualization:

   * Draws bounding boxes (optional)
   * Draws centroid trails
   * Displays object count crossing a defined axis

These examples highlight the need for:

* Better separation between inference, tracking, counting, and rendering
* Unified input handling (camera vs file)
* Configurable visualization options

DOCUMENTATION:
The following documentation sources should be referenced during refactoring:

* OpenCV Video I/O:
  https://docs.opencv.org/master/dd/d43/tutorial_py_video_display.html

* Norfair tracking library:
  https://tryolabs.github.io/norfair/

* TensorRT Python API:
  https://docs.nvidia.com/deeplearning/tensorrt/api/python_api/index.html

* Python logging best practices:
  https://docs.python.org/3/howto/logging.html

* dotenv usage in Python:
  https://pypi.org/project/python-dotenv/

* Clean Code principles:

  * Separation of concerns
  * Single Responsibility Principle (SRP)
  * Avoid global state
  * Explicit data structures over parallel arrays

OTHER CONSIDERATIONS:

1. Configuration Management:

* All configurable parameters must be moved to a `.env` file:

  * CONF_THRESH
  * IOU_THRESHOLD
  * INPUT_SOURCE (CAMERA / FILE)
  * VIDEO_PATH
  * OUTPUT_RESOLUTION (default: 640x480)
  * FPS_OUTPUT
  * DRAW_BOX
  * LOG_LEVEL

* Use `python-dotenv` to load environment variables

* Provide default values if not set

---

2. Input Handling (Camera vs File):

* Create a unified input interface:
  Example:
  class FrameSource:
  def read()

* Handle:

  * Camera (cv2.VideoCapture with device)
  * Video file (cv2.VideoCapture with path)

* Automatically detect FPS for file input:
  cap.get(cv2.CAP_PROP_FPS)

---

3. Resolution Handling:

* All frames must be resized to a configurable resolution:
  DEFAULT: 640x480

* Add parameter:
  OUTPUT_WIDTH=640
  OUTPUT_HEIGHT=480

* Apply:
  frame = cv2.resize(frame, (width, height))

* Ensure consistency between:

  * inference input
  * display
  * video writer

---

4. Logging Improvements:

* Replace all `print` and excessive `logger.info` calls

* Use levels properly:

  * DEBUG → internal state, shapes, timings
  * INFO → lifecycle events (start, stop, recording)
  * WARNING → unexpected but non-critical issues
  * ERROR → failures

* Avoid logging inside tight loops unless throttled:
  if frame_id % 30 == 0:

* Use structured logging:
  logger.debug("Detections count: %d", len(detections))

---

5. Code Refactoring:

* Remove all `global` variables → replace with shared state object

* Split responsibilities:

  * inference/
  * tracking/
  * counting/
  * rendering/

* Replace parallel arrays with objects:
  TrackedObject:
  bbox
  track_id
  class_id
  score

---

6. Threading & Performance:

* Ensure thread-safe communication via Queue
* Increase queue size to avoid bottlenecks
* Avoid blocking operations in threads

---

7. Video Writing:

* Ensure output FPS matches real processing FPS or input FPS
* Prevent slow-motion effect

---

8. Documentation:

* All functions must include English docstrings:
  """
  Description:
  Args:
  Returns:
  """

* Document tricky parts:

  * letterbox correction
  * tracking ID lifecycle
  * counting logic

---

9. Known Pitfalls (Important):

* Tracking ID instability (Norfair resets IDs)
* Frame drops due to slow inference
* Logging impacting performance
* Mismatch between inference FPS and output FPS
* Memory leak via uncleaned tracking trails

---

10. Future Improvements (optional but recommended):

* Kalman filter smoothing for trajectories
* Multi-zone counting
* GPU preprocessing pipeline
* REST API or UI integration
* Model abstraction (swap YOLO easily)
