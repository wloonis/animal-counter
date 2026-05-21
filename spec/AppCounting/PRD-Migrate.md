# Product Requirements Document: Pig Counting Application Migration

## Executive Summary

This PRD outlines the migration of a real-time pig counting application (./app/counting_app.py) from a prototype to a production-ready, scalable codebase. The application leverages TensorRT for inference and Norfair for tracking, running on Jetson Orin Nano devices with JetPack 6.1. The goal is to refactor the codebase to improve readability, maintainability, and scalability while ensuring robust performance in industrial environments.

**Core Value Proposition:**
- Transform a functional prototype into a clean, production-ready application.
- Enable zero-touch deployment and remote management of Jetson devices.
- Provide a scalable foundation for future enhancements (e.g., multi-zone counting, REST API integration).

**MVP Goal:**
Deliver a refactored application with improved architecture, configuration management, logging, and documentation, while maintaining all existing functionality.

## Mission

**Mission Statement:**
To provide a reliable, maintainable, and scalable real-time pig counting solution for industrial environments, ensuring seamless deployment and operation on Jetson Orin Nano devices.

**Core Principles:**
1. **Clean Architecture:** Separation of concerns, single responsibility principle, and explicit data structures.
2. **Zero-Touch Deployment:** Fully automated configuration and deployment via Ansible and GitOps.
3. **Performance:** Optimize for real-time processing with minimal latency and resource usage.
4. **Maintainability:** Comprehensive documentation, logging, and configuration management.
5. **Scalability:** Design for future enhancements and integrations.

## Target Users

**Primary User Personas:**
1. **Industrial Operators:**
   - Technical comfort level: Moderate
   - Needs: Reliable counting, minimal manual intervention, easy deployment.
   - Pain points: Unstable tracking, manual configuration, lack of documentation.

2. **Developers:**
   - Technical comfort level: High
   - Needs: Clean codebase, modular design, comprehensive logging.
   - Pain points: Poor readability, global state, lack of separation of concerns.

3. **System Administrators:**
   - Technical comfort level: High
   - Needs: Automated deployment, configuration management, monitoring.
   - Pain points: Manual setup, inconsistent logging, lack of remote management.

## MVP Scope

### In Scope ✅

**Core Functionality:**
- Real-time pig counting using TensorRT and Norfair.
- Camera and video file input handling.
- Tracking visualization (bounding boxes, centroid trails).
- Counting logic based on object crossing a vertical line.

**Technical:**
- Clean architecture with separation of concerns.
- Configuration management via `.env`.
- Unified input handling (camera vs. file).
- Resolution normalization (default: 640x480).
- Structured logging with levels (DEBUG, INFO, WARNING, ERROR).
- Thread-safe communication via Queue.
- Video writing with consistent FPS.

### Out of Scope ❌

**Features:**
- Multi-zone counting.
- Kalman filter smoothing for trajectories.
- GPU preprocessing pipeline.
- REST API or UI integration.
- Model abstraction (swap YOLO easily).

**Integration:**
- Ansible for infrastructure automation.
- GitOps for application deployment.
- Prometheus/Grafana for monitoring.

**Deployment:**
- Zero-touch deployment on Jetson Orin Nano.
- Automated network configuration (hotspot, static IP).
- k3s for container orchestration.

**Technical:**
- Advanced error handling (e.g., automatic recovery from crashes).
- Multi-device synchronization.
- Cloud integration (e.g., AWS, Azure).

## User Stories

1. **As a developer, I want a clean, modular codebase, so that I can easily extend and maintain the application.**
   - Example: Separation of inference, tracking, counting, and rendering modules.

3. **As a system administrator, I want comprehensive logging, so that I can monitor the application and troubleshoot issues.**
   - Example: Structured logging with levels (DEBUG, INFO, WARNING, ERROR).

4. **As an industrial operator, I want to configure the application via environment variables, so that I can easily adjust settings without modifying the code.**
   - Example: Configuration management via `.env` (e.g., `CONF_THRESH`, `IOU_THRESHOLD`).

5. **As a developer, I want unified input handling, so that I can seamlessly switch between camera and video file inputs.**
   - Example: `FrameSource` class with `read()` method for both camera and file inputs.

6. **As an industrial operator, I want consistent video resolution, so that the application performs reliably across different devices.**
   - Example: Resolution normalization to 640x480.

7. **As a system administrator, I want thread-safe communication, so that the application can handle high loads without crashing.**
   - Example: Thread-safe communication via Queue.

8. **As a developer, I want comprehensive documentation, so that I can understand and extend the codebase.**
   - Example: English docstrings for all functions, comments for tricky parts.

## Core Architecture & Patterns

**High-Level Architecture:**
```
┌───────────────────────────────────────────────────────────────────────────────┐
│                                                                               │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    │
│   │  Inference  │    │  Tracking   │    │  Counting   │    │ Rendering   │    │
│   └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    │
│                                                                               │
│   ┌───────────────────────────────────────────────────────────────────────┐   │
│   │                            Shared State Object                        │   │
│   └───────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    │
│   │  Frame      │    │  Detections │    │  Tracks     │    │  Output     │    │
│   │  Source     │    │             │    │             │    │  Video      │    │
│   └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘    │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Directory Structure:**
```
app/
├── config/                  # Configuration files
│   └── .env                 # Environment variables
├── src/                     # Source code
│   ├── inference/           # Inference module
│   ├── tracking/            # Tracking module
│   ├── counting/            # Counting module
│   ├── rendering/           # Rendering module
│   ├── utils/               # Utility functions
│   └── main.py              # Main application
├── img/                     # Images
├── model/                   # Tensorrt Model
├── tests/                   # Unit and integration tests
├── docs/                    # Documentation
└── README.md                # Project overview
```

**Key Design Patterns:**
- **Separation of Concerns:** Each module handles a specific responsibility.
- **Single Responsibility Principle (SRP):** Each class/function has one purpose.
- **Thread-Safe Communication:** Use of Queue for inter-thread communication.
- **Configuration Management:** Environment variables for configurable parameters.

**Technology-Specific Patterns:**
- **TensorRT:** Optimized inference pipeline.
- **Norfair:** Tracking with custom counting logic.
- **OpenCV:** Video I/O and frame processing.
- **Python Logging:** Structured logging with levels.

## Tools/Features

**Feature Specifications:**

1. **Inference Module:**
   - Load TensorRT model.
   - Perform inference on frames.
   - Return detections with confidence scores.

2. **Tracking Module:**
   - Initialize Norfair tracker.
   - Update tracks with detections.
   - Manage track lifecycle (creation, update, deletion).

3. **Counting Module:**
   - Define counting line (vertical axis).
   - Count objects crossing the line.
   - Handle track ID instability.

4. **Rendering Module:**
   - Draw bounding boxes (configurable).
   - Draw centroid trails.
   - Display object count.
   - Write output video with consistent FPS.

5. **Frame Source:**
   - Unified interface for camera and video file inputs.
   - Automatic FPS detection for video files.
   - Resolution normalization.

6. **Configuration Management:**
   - Load environment variables via `python-dotenv`.
   - Provide default values for missing variables.
   - Validate configuration on startup.

7. **Logging:**
   - Structured logging with levels.
   - Throttle logging in tight loops.
   - Log lifecycle events (start, stop, recording).

8. **Threading:**
   - Thread-safe communication via Queue.
   - Avoid blocking operations in threads.
   - Increase queue size to prevent bottlenecks.

## Technology Stack

**Backend:**
- **Language:** Python 3.10+
- **Inference:** TensorRT 10.3+
- **Tracking:** Norfair 2.3+
- **Video Processing:** OpenCV 4.11+
- **Logging:** Python Logging
- **Configuration:** python-dotenv 0.19+

**Dependencies:**
- `numpy`
- `opencv-python`
- `norfair`
- `python-dotenv`
- `tensorrt`

**Optional Dependencies:**
- `pytest` (for testing)
- `black` (for code formatting)
- `isort` (for import sorting)

## Security & Configuration

**Configuration Management:**
- Environment variables via `.env`.
- Default values for missing variables.
- Validation on startup.

## API Specification

Not applicable for this MVP. Future enhancements may include a REST API for integration.

## Success Criteria

**MVP Success Definition:**
- Refactored application with improved architecture and maintainability.
- Comprehensive documentation and logging.

**Functional Requirements:**
- ✅ Real-time pig counting with TensorRT and Norfair.
- ✅ Camera and video file input handling.
- ✅ Tracking visualization (bounding boxes, centroid trails).
- ✅ Counting logic based on object crossing a vertical line.
- ✅ Configuration management via `.env`.
- ✅ Unified input handling (camera vs. file).
- ✅ Resolution normalization (default: 640x480).
- ✅ Structured logging with levels (DEBUG, INFO, WARNING, ERROR).
- ✅ Thread-safe communication via Queue.
- ✅ Video writing with consistent FPS.

**Quality Indicators:**
- Code readability and maintainability.
- Comprehensive documentation.
- Robust logging and error handling.
- Performance (real-time processing with minimal latency).

**User Experience Goals:**
- Easy deployment and configuration.
- Clear visualization of tracking and counting.
- Reliable performance in industrial environments.

## Implementation Phases

### Phase 1: Planning and Setup
- **Goal:** Define requirements, architecture, and setup development environment.
- **Deliverables:**
  - ✅ PRD (this document).
  - ✅ Architecture diagram.
  - ✅ Development environment setup.
- **Validation:** Review and approval of PRD and architecture.

### Phase 2: Refactoring and Core Features
- **Goal:** Refactor codebase and implement core features.
- **Deliverables:**
  - ✅ Clean architecture with separation of concerns.
  - ✅ Configuration management via `.env`.
  - ✅ Unified input handling (camera vs. file).
  - ✅ Resolution normalization.
  - ✅ Structured logging.
  - ✅ Thread-safe communication.
- **Validation:** Unit tests for core modules, code review.

### Phase 3: Testing and Deployment
- **Goal:** Test application and deploy on Jetson Orin Nano.
- **Deliverables:**
  - ✅ Integration tests.
- **Validation:** Successful tests.

### Phase 4: Documentation and Handover
- **Goal:** Complete documentation and handover to stakeholders.
- **Deliverables:**
  - ✅ Comprehensive documentation (README, docstrings, comments).
  - ✅ Training for stakeholders.
- **Validation:** Review and approval of documentation.

**Timeline Estimates:**
- Phase 1: 1 week
- Phase 2: 3 weeks
- Phase 3: 2 weeks
- Phase 4: 1 week

## Future Considerations

**Post-MVP Enhancements:**
- Multi-zone counting.
- Kalman filter smoothing for trajectories.
- GPU preprocessing pipeline.
- REST API or UI integration.
- Model abstraction (swap YOLO easily).

**Advanced Features:**
- Automatic recovery from crashes.
- Dynamic configuration updates.
- Advanced error handling and reporting.

## Risks & Mitigations

1. **Risk: Tracking ID instability (Norfair resets IDs).**
   - **Mitigation:** Implement custom logic to handle track ID changes.

2. **Risk: Frame drops due to slow inference.**
   - **Mitigation:** Optimize inference pipeline, increase queue size.

3. **Risk: Logging impacting performance.**
   - **Mitigation:** Throttle logging in tight loops, use appropriate log levels.

4. **Risk: Mismatch between inference FPS and output FPS.**
   - **Mitigation:** Ensure video writing matches real processing FPS.

5. **Risk: Memory leak via uncleaned tracking trails.**
   - **Mitigation:** Implement proper cleanup for tracking trails.

## Appendix

**Related Documents:**
- `INITIAL-AppCounting-Migrate.md`

**Old Code/:**
- `INITIAL-AppCounting-Migrate.md`

**Key Dependencies:**
- [OpenCV Video I/O](https://docs.opencv.org/master/dd/d43/tutorial_py_video_display.html)
- [Norfair Tracking Library](https://tryolabs.github.io/norfair/)
- [TensorRT Python API](https://docs.nvidia.com/deeplearning/tensorrt/api/python_api/index.html)
- [Python Logging Best Practices](https://docs.python.org/3/howto/logging.html)
- [python-dotenv](https://pypi.org/project/python-dotenv/)

**Repository/Project Structure:**
```
app/
├── config/
│   └── .env
├── src/
│   ├── inference/
│   ├── tracking/
│   ├── counting/
│   ├── rendering/
│   ├── utils/
│   └── main.py
├── tests/
├── docs/
└── README.md
```
