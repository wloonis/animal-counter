# Pig Counting Application

## Overview

This application performs real-time pig counting using TensorRT for inference and Norfair for tracking. It is designed to run on Jetson Orin Nano devices with JetPack 6.1 and Ubuntu 22.04.

## Features

- **Real-time Inference:** Uses TensorRT for optimized YOLOv7 inference.
- **Object Tracking:** Implements Norfair for tracking objects across frames.
- **Counting Logic:** Counts objects crossing a vertical line.
- **Unified Input Handling:** Supports both camera and video file inputs.
- **Configuration Management:** Uses `.env` for configurable parameters.
- **Structured Logging:** Implements logging with levels (DEBUG, INFO, WARNING, ERROR).

## Project Structure

```
.
├── app/
│   └── src/                     # Source code
│       ├── config/              # Configuration management
│       ├── inference/           # TensorRT inference module
│       ├── tracking/            # Norfair tracking module
│       ├── counting/            # Counting logic module
│       ├── rendering/           # Visualization module
│       ├── utils/               # Utility functions
│       └── main.py              # Main application entry point
├── config/                      # Configuration files
│   └── .env                     # Environment variables
├── img/                        # Images
├── model/                      # TensorRT Model
├── tests/                      # Unit and integration tests
├── docs/                       # Documentation
└── README.md                   # Project overview
```

## Installation

### Prerequisites

- Python 3.10+
- JetPack 6.1 (for Jetson Orin Nano)
- Ubuntu 22.04
- TensorRT 10.3+
- CUDA 11.4+

### Dependencies

Install the required dependencies:

```bash
pip install numpy opencv-python norfair python-dotenv tensorrt pytest
```

## Configuration

Create a `.env` file in the `app` directory with the following variables:

```env
# Inference Parameters
CONF_THRESH=0.5
IOU_THRESHOLD=0.45

# Input Source
INPUT_SOURCE=CAMERA
VIDEO_PATH=/dev/video0

# Output Resolution
OUTPUT_WIDTH=640
OUTPUT_HEIGHT=480

# FPS Settings
FPS_OUTPUT=30

# Visualization Options
DRAW_BOX=False

# Logging Level
LOG_LEVEL=INFO
```

## Usage

### Running the Application

To start the application with the default camera input:

```bash
python app/src/main.py
```

To specify a video file input:

```bash
python app/src/main.py --input FILE --file /path/to/video.mp4
```

To enable bounding box visualization:

```bash
python app/src/main.py --drawbox true
```

### Command Line Arguments

- `--input`: Input source (`CAMERA` or `FILE`).
- `--file`: Path to video file (required if `--input FILE`).
- `--drawbox`: Enable bounding box visualization (`true` or `false`).

## Testing

Run the unit tests to ensure all modules are working correctly:

```bash
pytest tests/ -v
```

## Documentation

- **OpenCV Video I/O:** [OpenCV Video Capture](https://docs.opencv.org/master/dd/d43/tutorial_py_video_display.html)
- **Norfair Tracking Library:** [Norfair Documentation](https://tryolabs.github.io/norfair/)
- **TensorRT Python API:** [TensorRT API](https://docs.nvidia.com/deeplearning/tensorrt/api/python_api/index.html)
- **Python Logging Best Practices:** [Python Logging](https://docs.python.org/3/howto/logging.html)
- **python-dotenv:** [python-dotenv Documentation](https://pypi.org/project/python-dotenv/)

## Architecture

The application follows a modular architecture with separation of concerns:

1. **Configuration:** Manages environment variables and settings.
2. **Inference:** Handles TensorRT-based object detection.
3. **Tracking:** Manages object tracking using Norfair.
4. **Counting:** Implements counting logic based on object movement.
5. **Rendering:** Visualizes tracking and counting results.
6. **Utilities:** Provides helper functions for frame handling and timing.

## Contributing

Contributions are welcome! Please follow the project's coding conventions and submit pull requests for review.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
