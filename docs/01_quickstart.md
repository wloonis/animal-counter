# Animal Counter Application - Quick Start Guide

## Overview

The Animal Counter Application is a real-time animal counting system designed for edge deployment on Jetson Orin devices. It uses YOLO26 with TensorRT for high-performance inference, OCSORT tracker for accurate object tracking, and features a multi-threaded architecture separating inference and display tasks for optimal performance.

### Key Features

- **YOLO26 + TensorRT**: Optimized inference on Jetson Orin
- **OCSORT Tracker**: Advanced object tracking for precise counting
- **Multi-threaded Architecture**: Separate inference and display threads
- **K3s Kubernetes**: Containerized deployment
- **FileBrowser**: Web-based video management interface
- **Ansible Automation**: Automated deployment and configuration

---

## Prerequisites

### Hardware

| Component | Requirement |
|-----------|-------------|
| Device | Jetson Orin (Nano, NX, or AGX) |
| Camera | USB webcam or RTSP stream |
| Storage | SD card or NVMe with ≥32GB |

### Software

| Component | Minimum Version |
|-----------|------------------|
| JetPack | 6.1+ |
| Python | 3.10+ |
| TensorRT | 8.x (included with JetPack) |
| Docker | 24.x+ |
| Kubernetes (K3s) | v1.28+ |

---

## Quick Start Steps

### 1. Flash JetPack

```bash
sudo ./flash.sh jetson-orin-nano mmcblk0p1
```

### 2. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install TensorRT bindings
pip install tensorrt
```

### 3. Deploy with Ansible

```bash
ansible-playbook -i inventory deploy.yml
```

### 4. Deploy to K3s

```bash
kubectl apply -f k8s/
```

### 5. Access FileBrowser

Open browser: `http://<device-ip>:8080`

Default credentials: `admin:animalcounter`

---

## Running the Application

### Local Execution

```bash
python main.py --source /dev/video0 --model yolov8n.pt
```

### With Docker

```bash
docker run -it --runtime nvidia animal-counter:latest \
  --source rtsp://camera-ip:554/stream
```

### With Kubernetes

```bash
kubectl scale deployment animal-counter --replicas=2
```

### Monitor Logs

```bash
kubectl logs -f deployment/animal-counter
```

---

## Troubleshooting Tips

### Common Issues

| Issue | Solution |
|-------|----------|
| TensorRT not found | Ensure JetPack 6.1+ is installed |
| Low FPS | Check GPU utilization; reduce input resolution |
| Camera not detected | Verify `/dev/video0` exists |
| Tracking errors | Adjust confidence threshold `--conf 0.5` |
| K3s pod crash | Check `kubectl describe pod <name>` |

### Performance Tuning

- Reduce inference resolution: `--imgsz 640`
- Adjust confidence threshold: `--conf 0.3`
- Enable FP16: `--half`

### Health Check

```bash
# Check container status
docker ps

# Check GPU usage
tegrastats

# Check application logs
journalctl -u animal-counter -f
```

---

## Support

For issues and questions:
- Documentation: `/docs`
- Logs: `/var/log/animal-counter/`
- Email: support@animalcounter.local