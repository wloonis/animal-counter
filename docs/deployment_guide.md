# Deployment Guide

## Overview

This guide provides instructions for deploying the pig counting application on Jetson Orin Nano devices with JetPack 6.1 and Ubuntu 22.04.

## Prerequisites

### Hardware
- Jetson Orin Nano
- Camera module (for camera input)

### Software
- JetPack 6.1
- Ubuntu 22.04
- Python 3.10+
- TensorRT 10.3+
- CUDA 11.4+

## Installation

### Step 1: Install Dependencies

Install the required dependencies:

```bash
sudo apt update
sudo apt install python3-pip
pip install numpy opencv-python norfair python-dotenv tensorrt pytest
```

### Step 2: Clone the Repository

Clone the repository to your Jetson Orin Nano:

```bash
git clone <repository-url>
cd pig-counting-application
```

### Step 3: Configure Environment Variables

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

### Step 4: Download TensorRT Model

Place your TensorRT model file in the `app/model` directory. Ensure the model is compatible with TensorRT 10.3+.

## Running the Application

### Camera Input

To start the application with the default camera input:

```bash
python app/src/main.py
```

### Video File Input

To specify a video file input:

```bash
python app/src/main.py --input FILE --file /path/to/video.mp4
```

### Bounding Box Visualization

To enable bounding box visualization:

```bash
python app/src/main.py --drawbox true
```

## Testing

Run the unit tests to ensure all modules are working correctly:

```bash
pytest tests/ -v
```

## Troubleshooting

### Camera Not Detected

Ensure the camera module is properly connected and detected by the system:

```bash
ls /dev/video*
```

### TensorRT Errors

Ensure TensorRT is properly installed and the model is compatible with the installed version of TensorRT.

### Missing Dependencies

Ensure all dependencies are installed:

```bash
pip list
```

## Support

For support, please contact the project maintainers or open an issue in the repository.
