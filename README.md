# Animal Counter Application

## Overview

A real-time animal counting application using YOLO object detection with TensorRT inference, designed for deployment on NVIDIA Jetson Orin devices. The system automatically counts animals (primarily pigs) as they move through a designated area, with support for training new models and Kubernetes-based deployment.

**JetPack:** 6.2.2

## Features

### Core Capabilities
- **Real-Time Inference**: Optimized with YOLO26 and TensorRT for efficient GPU acceleration
- **Object Tracking**: OCSORT (Optimal Score Assignment) tracker for accurate multi-object tracking
- **Automatic Counting**: Counts animals moving in both directions with direction-aware logic
- **Video Recording**: Automatic video recording when animals are detected
- **Learning Mode**: Record images/videos for model training purposes

### System Features
- **Multi-threaded Architecture**: Separate inference and display threads for optimal performance
- **Hotspot Support**: Offline operation with built-in WiFi hotspot for direct connectivity
- **Full Automated Deployment**: Ansible-based installation for Jetson Orin
- **Kubernetes Deployment**: K3s manifest templates for containerized deployment
- **FileBrowser Integration**: Web-based file management for recorded videos
- **Cron Video Compression**: Automated video compression for storage optimization

## Architecture

```
animal-counter/
├── app/src/                     # Main application source
│   ├── core/                    # Core processing modules
│   │   ├── inference.py         # TensorRT inference engine
│   │   ├── tracking.py          # Object tracking logic
│   │   └── counting.py          # Counting algorithm
│   ├── ui/                      # User interface
│   │   └── rendering.py         # Visual output & UI drawing
│   ├── utils/                   # Utility modules
│   │   ├── frame_source.py      # Camera/video frame capture
│   │   ├── shared_state.py      # Shared state management
│   │   └── timer_fps.py         # FPS timing utilities
│   ├── settings.py              # Configuration management
│   └── main.py                  # Application entry point
├── ansible/                     # Ansible deployment playbooks
│   ├── playbooks/
│   │   ├── app/                 # Application deployment
│   │   ├── model/               # Model building
│   │   └── system/              # System configuration
│   └── k8s-deployment/          # K8s manifests
├── k3s/                         # K3s deployment templates
│   └── templates/               # Jinja2 templates for K8s resources
├── docs/                        # Documentation
├── tests/                       # Unit tests
└── dataset/                     # Training dataset storage
```

### Multi-Threaded Design

The application uses a producer-consumer pattern with two main threads:

1. **Inference Thread**: Captures frames, runs TensorRT inference, and posts results to a shared queue
2. **Display Thread**: Consumes inference results, performs tracking, counting, and renders output

This architecture ensures real-time processing without frame drops.

### Core Modules

| Module | Description |
|--------|-------------|
| `inference.py` | TensorRT model loading and inference with pre/post-processing |
| `tracking.py` | OCSORT tracker integration and bounding box handling |
| `counting.py` | Direction-aware counting based on object trajectory |
| `rendering.py` | Video overlay, UI elements, and display management |
| `frame_source.py` | Camera (V4L2) and video file input handling |
| `shared_state.py` | Thread-safe state management for inter-thread communication |

## Installation

### Prerequisites

- Python 3.10+
- JetPack 6.1+ (for Jetson Orin)
- Ubuntu 22.04
- TensorRT 10.3+
- CUDA 11.4+
- Ansible 2.14+

### Local Development Setup

```bash
# Install Ansible
./scripts/install_ansible.sh

# Install Python dependencies
pip install numpy opencv-python trackers python-dotenv tensorrt pytest
```

### Jetson Orin Deployment

#### Full Installation

```bash
# Prepare Jetson with all dependencies
./scripts/prepare_jetson.sh
```

#### Using Ansible Playbooks

```bash
# System preparation
ansible-playbook -i ansible/inventory/jetson ansible/playbooks/system/prepare_system.yml

# Install K3s
ansible-playbook -i ansible/inventory/jetson ansible/playbooks/system/install_k3s_with_docker_tasks.yml

# Deploy the application
ansible-playbook -i ansible/inventory/jetson ansible/playbooks/app/deploy_countingapp.yml

# Setup WiFi hotspot
ansible-playbook -i ansible/inventory/jetson ansible/playbooks/system/hotspot_setup.yml
```

#### Individual Playbooks

| Playbook | Description |
|----------|-------------|
| `system/prepare_system.yml` | Install system dependencies |
| `system/install_k3s_with_docker_tasks.yml` | Deploy K3s cluster |
| `system/hotspot_setup.yml` | Configure WiFi hotspot |
| `system/install_lxde.yml` | Install LXDE desktop |
| `app/deploy_countingapp.yml` | Deploy counting application |
| `app/deploy_app.yml` | Simple app deployment |
| `app/build_countingapp.yml` | Build counting app container |
| `model/build_model.yml` | Build TensorRT model |

### Building a New Model

```bash
# Train and deploy new model
./scripts/training_model.sh
```

Required environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `TRAINING_PROJECT_DIR` | Training project directory | - |
| `LOCAL_APP_PATH` | Local app directory | - |
| `APP_PATH` | Target app path | `/data/orin/git/animal-counting/app` |
| `TRAINING_DATA_PATH` | Training data directory | - |
| `TRAINING_MODEL` | Model name/config | - |
| `TRAINING_EPOCHS` | Number of epochs | - |
| `TRAINING_IMGSZ` | Input image size | - |
| `TRAINING_DEVICE` | Training device | `gpu` |

## Configuration

### Environment Variables

Create a `.env` file in the `app` directory:

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
OUTPUT_SCREEN_WIDTH=1024
OUTPUT_SCREEN_HEIGHT=600

# FPS Settings
FPS_OUTPUT=30

# Visualization
DRAW_TRACKING=True
CENTROID_TRACKING=True
BOX_TRACKING=True

# Detection Thresholds
PIG_CONFIDENCE_THRESHOLD=0.7
PIG_CONFIDENCE_THRESHOLD_START_VIDEO=0.8

# Learning Mode
DATASET_DIR=./dataset
CAPTURE_INTERVAL=5
MAX_LEARNING_DURATION=600

# Output
OUTPUT_VIDEO_PATH=/app/output

# Logging
LOG_LEVEL=INFO
```

### Kubernetes Deployment

The application supports K3s deployment with the following components:

- **Deployment**: Main counting application pod
- **Service**: ClusterIP service for internal communication
- **ConfigMap**: Application configuration
- **Secret**: Sensitive credentials
- **FileBrowser**: Web-based file management
- **CronJob**: Video compression scheduler

## Usage

### Running the Application

#### Camera Input (Default)
```bash
python app/src/main.py
```

#### Video File Input
```bash
python app/src/main.py --input FILE --file /path/to/video.mp4
```

#### With Bounding Box Visualization
```bash
python app/src/main.py --drawtracking true
```

### Command Line Arguments

| Argument | Short | Description | Values |
|----------|-------|-------------|--------|
| `--input` | `-m` | Input source | `CAMERA`, `FILE` |
| `--file` | `-f` | Video file path (required if --input FILE) | path |
| `--drawtracking` | `-d` | Enable bounding box visualization | `true`, `false` |

### Application Modes

The application operates in several modes controlled via shared state:

- **Status 0** (Stop): No processing, display only
- **Status 1** (Count): Active counting and recording
- **Status 2** (Pause): Pause counting, continue display
- **Status 3** (Auto): Automatic detection and recording

#### Mouse Controls (Fullscreen Mode)
- Click: Toggle between modes

### Learning Mode

When enabled, the application captures images at regular intervals for model training:
- Images saved to configured dataset directory
- Configurable capture interval and maximum duration
- Automatic termination after max duration

## Testing

```bash
# Run all unit tests
pytest tests/ -v

# Run specific test
pytest tests/test_inference.py -v
```

## Documentation

- [Quick Start Guide](docs/01_quickstart.md)
- [Bootstrap Details](docs/02_bootstrap_detail.md)
- [Multi-Jetson Setup](docs/03_multi_jetson.md)
- [Troubleshooting](docs/04_troubleshooting.md)
- [Reset Procedure](docs/05_reset_procedure.md)
- [Deployment Guide](docs/deployment_guide.md)

### External References

- [OpenCV Video I/O](https://docs.opencv.org/master/dd/d43/tutorial_py_video_display.html)
- [Trackers Library](https://github.com/JonC3900/Trackers)
- [TensorRT Python API](https://docs.nvidia.com/deeplearning/tensorrt/api/python_api/index.html)
- [Python Logging](https://docs.python.org/3/howto/logging.html)
- [python-dotenv](https://pypi.org/project/python-dotenv/)
- [OCSORT Tracker](https://github.com/NoahCrown/OCSORT)
- [Supervision Library](https://github.com/ultralytics/supervision)

## Technology Stack

| Component | Technology |
|-----------|------------|
| Object Detection | YOLO26 (YOLOv11) |
| Inference Engine | TensorRT |
| Tracker | OCSORT |
| Container Runtime | Docker/K3s |
| Deployment | Ansible |
| UI | OpenCV |
| Language | Python 3.10+ |

## Contributing

Contributions are welcome! Please follow the project's coding conventions and submit pull requests for review.

## License

MIT License - See [LICENSE](LICENSE) file for details.