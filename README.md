# Animal Counter Application

## Overview

The JetPack installed is the 6.2.2

## Features

* The Real-Time Inference is optimised with YOLO26
* New feature with the Learning mode allowing to record videos or images to improve learning.
* Full automated installation with Ansible for deployment on a Jetson Orin.
* Tooling for training a model based on a training dataset (labelled images). The training is done using yolo26
* User interface to upload videos with FileBrowser
* Offline operation and activation of a HotSpot to connect to the Jetson

## Installation

### Setting up local environment

To prepare your local environment, you need to install Ansible:

```bash
./scripts/install_ansible.sh
```

### Installing on Jetson Orin

To install the application on a Jetson Orin:

```bash
./scripts/prepare_jetson.sh
```

### Training a new model

To train and install a new model:

```bash
./scripts/training_model.sh
```

#### Required Environment Variables

The training script requires the following environment variables:

| Variable | Description | Default | Required |
|---------|-------------|---------|---------|
| `TRAINING_PROJECT_DIR` | Path to the training project directory | - | Yes |
| `LOCAL_APP_PATH` | Path to the local app directory | - | Yes |
| `APP_PATH` | Path to the app on the target device | `/data/orin/git/animal-counting/app` | No |
| `TRAINING_DATA_PATH` | Path to the training data directory | - | Yes |
| `TRAINING_MODEL` | Model name or configuration | - | Yes |
| `TRAINING_EPOCHS` | Number of training epochs | - | Yes |
| `TRAINING_IMGSZ` | Training image size | - | Yes |
| `TRAINING_DEVICE` | Training device (gpu/cpu) | `gpu` | No |

## Project Structure

```
.
├── app/
│   └── src/                     # Source code
│       ├── config/              # Configuration management
│       ├── inference/           # TensorRT inference module
│       ├── tracking/            # Trackers tracking module
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
pip install numpy opencv-python trackers python-dotenv tensorrt pytest
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
- **Trackers Library:** [Trackers Documentation](https://github.com/JonC3900/Trackers)
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
