# Animal Counter

Real-time animal (pig) counting on NVIDIA Jetson Orin, using a YOLO model
exported to ONNX and compiled into a TensorRT engine, tracked with OC-SORT,
and deployed on a single-node K3s cluster via Ansible.

The system points a **fixed camera** at a counting line, tracks every pig that
crosses it, and maintains a **net bidirectional counter** (+1 right→left,
−1 left→right). It auto-records a video clip whenever a pig is detected and
stops after ~2 minutes with no detection. It is operated daily: powered on in
the morning (counter starts at 0), used through the day across several
animal-moving iterations, and powered off (hard power cut) in the evening.

<p align="center">
  <img src="app/video/frame_count.jpg" alt="Pig counting in action: fixed camera, yellow vertical counting line, and the live net bidirectional counter overlay" width="640">
</p>
<p align="center"><em>The app in action — YOLO/TensorRT detections, OC-SORT tracks, the yellow counting line, and the live net counter (+1 right→left, −1 left→right).</em></p>

> **Status:** counting logic validated on 30 reference videos (4/4 priority
> defect videos pass, REID-SUPPRESS regression guard confirmed). See
> [`docs/06_validation.md`](docs/06_validation.md).

---

## Table of contents

| Doc | What it covers |
|-----|----------------|
| [`docs/01_quickstart.md`](docs/01_quickstart.md) | 5-minute path from a flashed Jetson to a running app, **scripts-first** |
| [`docs/02_setup.md`](docs/02_setup.md) | Flash JetPack, first boot, system preparation |
| [`docs/03_deployment.md`](docs/03_deployment.md) | K3s + Ansible deployment (real playbooks & templates) |
| [`docs/04_configuration.md`](docs/04_configuration.md) | App configuration (`.env`, `settings.py`, parameter table) |
| [`docs/05_counting_pipeline.md`](docs/05_counting_pipeline.md) | Counting pipeline internals & anti-ID-switch guards |
| [`docs/06_validation.md`](docs/06_validation.md) | Validation workflow (`validate_on_jetson.sh`, manifest, reports) |
| [`docs/07_troubleshooting.md`](docs/07_troubleshooting.md) | Troubleshooting |
| [`docs/08_reset.md`](docs/08_reset.md) | Reset procedures |
| [`docs/09_backlog.md`](docs/09_backlog.md) | Improvement backlog (BL-01..BL-53) |
| [`docs/10_development_workflow.md`](docs/10_development_workflow.md) | Development workflow with `archon-jetson-dev` (CLARIFY → plan → validate → PR) |

---

## Repository layout

```
animal-counter/
├── app/                     # The counting application (container image)
│   ├── Dockerfile           # Base: dustynv/l4t-pytorch:r36.4.0 (JetPack 6.2)
│   ├── entrypoint.sh        # Modes: build-engine | serve | debug | test | validate
│   ├── requirements.txt     # pycuda, trackers==2.4.0 (OC-SORT), flask, python-dotenv
│   ├── .env / .env.example  # Runtime config (.env is gitignored; .env.example is versioned)
│   ├── model/               # my_model.{pt,onnx,engine}  (engine built by trtexec)
│   └── src/
│       ├── main.py           # Entry point (Flask web app + InferThread + DisplayThread)
│       ├── settings.py       # Config loader (reads app/.env, defaults documented inline)
│       ├── core/
│       │   ├── inference.py   # TensorRT inference + pre/post-processing
│       │   ├── tracking.py    # OC-SORT tracker integration, letterbox undo, drawing
│       │   └── counting.py    # Counting line logic + anti-ID-switch guards
│       ├── ui/rendering.py    # Overlay & UI drawing
│       └── utils/             # frame_source, shared_state, timer_fps
├── scripts/                 # ⭐ Central automation hub (the starting point for humans)
│   ├── prepare_jetson.sh            # Discover Jetson + deploy the app (one-shot)
│   ├── training_model.sh            # Discover Jetson + build/train a model
│   ├── validate_on_jetson.sh        # Validate counting on reference videos (dev loop)
│   ├── jetson_discover.sh           # nmap scan + SSH credential test → JETSON_IP
│   ├── jetson_first_access.sh       # SSH connectivity check
│   ├── install_ansible.sh           # Install Ansible on the control machine
│   └── install_splash_screen_standalone.sh
├── ansible/                 # Ansible automation (deploy + system + model)
│   ├── inventory/jetsons.yml        # Single host, env-driven (JETSON_IP/USER/PASSWORD)
│   ├── group_vars/all.yml           # Defaults (filebrowser creds, paths…)
│   └── playbooks/
│       ├── app/   deploy_app.yml · deploy_countingapp.yml · build_countingapp.yml
│       ├── model/ build_model.yml
│       └── system/ prepare_system · install_k3s · hotspot · splash · lxde · network_ssh …
├── k3s/templates/           # Jinja2 K8s manifests (the REAL prod manifests, applied by Ansible)
│   ├── countingapp-dep.j2          # DaemonSet (the app, pausable for validation)
│   ├── countingapp-svc.j2 · countingapp-ns.j2
│   ├── countingapp-validate.j2 · countingapp-test.j2 · build-engine-batch.j2
│   ├── filebrowser-dep.j2 · filebrowser-svc.j2 · filebrowser-cmap.j2 · filebrowser-sct.j2
│   └── cronvideo-dep.j2            # Rolling video compression + cleanup
├── validation/              # Reference videos + expected-count manifest
│   ├── config.json                  # reference_video, tolerance, max_iterations, mode
│   ├── expected_counts.json         # Manifest: videos{} + disabled{}
│   └── videos/                      # validation-<seq>-#<count>.mp4 (gitignored except 1 reference)
├── docs/                    # This documentation set
└── tests/                   # pytest unit tests (counting, inference, tracking, rendering)
```

> The real manifests are the Jinja2 templates in `k3s/templates/`, rendered and
> applied by `ansible/playbooks/app/deploy_countingapp.yml`. See
> [`docs/03_deployment.md`](docs/03_deployment.md).

---

## How the app runs

The container `entrypoint.sh` takes a **mode** argument:

| Mode | What it does |
|------|--------------|
| `build-engine` | Compile `model/my_model.onnx` → `my_model.engine` via `trtexec` |
| `serve` | Run `python3 src/main.py` — the Flask web app + inference/display threads (production) |
| `validate` | Run `main.py --input=FILE --file=$VALIDATE_VIDEO` and write `result.json` (used by the validation job) |
| `test` | Run `main.py` on a local test video with tracking drawn |
| `debug` | `tail -f /dev/null` — keep the container alive for `kubectl exec` |

In production the pod runs in `serve` mode. `main.py` exposes a small Flask web
app (port `31501`) that the operator uses to **start/stop** counting and read
the counter, while two background threads do the work:
**InferThread** (capture → TensorRT inference → queue) and **DisplayThread**
(tracking → counting → recording → render). See
[`docs/05_counting_pipeline.md`](docs/05_counting_pipeline.md).

---

## Operator workflow (daily production)

1. **Power on** the Jetson in the morning → K3s starts → the `countingapp`
   DaemonSet pod boots → the web app is ready (counter = 0).
2. Open the app (local screen / `http://<jetson-ip>:31501`), confirm the camera
   feed and the counting line are visible.
3. Move a series of pigs (typically 15–25) past the camera; the counter
   increments for each pig that crosses the line right→left (+1) and
   decrements for a left→right return (−1). A video clip is recorded each time
   a pig is detected and stops after ~2 minutes with no detection.
4. Repeat the series through the day — the counter accumulates across
   iterations and across recordings.
5. **Read the counter** at the end of the day, then **power off** the Jetson
   (hard cut).

> ⚠️ Known production gaps (tracked in the backlog): the counter is **not
> persisted** (a pod restart during the day resets it to 0 — BL-42), and the
> video in progress is **not finalized on SIGTERM** because
> `terminationGracePeriodSeconds: 0` (BL-43/BL-46). See
> [`docs/09_backlog.md`](docs/09_backlog.md).

---

## Onboarding for a new developer

The `scripts/` directory is the central hub. Two flows cover everything:

### A. Provision a Jetson and deploy the app
```bash
# 1. On your control machine (Ubuntu/Debian): install Ansible + helpers
sudo bash scripts/install_ansible.sh

# 2. Configure credentials (copy and edit)
cp .env.local.example .env.local   # then set JETSON_USER, JETSON_PASSWORD, WIFI_NETWORK…

# 3. One-shot: discover the Jetson on the network + deploy
bash scripts/prepare_jetson.sh
```
`prepare_jetson.sh` chains `jetson_discover.sh` (nmap scan + SSH test →
`/tmp/jetson_env.sh`) → `jetson_first_access.sh` (SSH check) →
`ansible-playbook deploy_app.yml`. See
[`docs/02_setup.md`](docs/02_setup.md) and
[`docs/03_deployment.md`](docs/03_deployment.md).

### B. Validate counting against reference videos
```bash
# Validate only the videos declared in validation/expected_counts.json (.videos)
bash scripts/validate_on_jetson.sh --full

# Or single reference video (validation/config.json -> reference_video)
bash scripts/validate_on_jetson.sh
```
This rsyncs the code + a video to the Jetson, pauses the live DaemonSet
(`nodeSelector: validate-paused=true`), runs a one-shot K8s Job
(`countingapp-validate.j2`), fetches `result.json`, compares the count against
the manifest, and writes `validation-report.json`. See
[`docs/06_validation.md`](docs/06_validation.md).

### C. Build/retrain a model
```bash
bash scripts/training_model.sh     # discover + ansible-playbook build_model.yml
```

---

## Requirements

| | Requirement |
|---|---|
| **Target device** | NVIDIA Jetson Orin (tested on Orin Nano 8 GB "Super") |
| **JetPack / L4T** | 6.2 / R36.4.0+ (Docker base `dustynv/l4t-pytorch:r36.4.0`) |
| **Control machine** | Ubuntu/Debian with Ansible 2.14+, `sshpass`, `nmap`, `jq` |
| **Python** | 3.10 (in the container) |
| **Camera** | USB webcam (`/dev/video0`) — fixed position |
| **Network** | Same LAN as the Jetson (or the Jetson's WiFi hotspot) |

---

## Configuration at a glance

Runtime config lives in **`app/.env`** (gitignored); copy `app/.env.example`
and adjust. Key validated values (fixed camera, 30 fps, pigs counted
right→left):

```ini
INPUT_SOURCE=CAMERA
VIDEO_PATH=/dev/video0
FPS_OUTPUT=30
OFFSET_PERCENT_COUNTING_LINE=10   # counting line at x ≈ 384 on a 640px frame
PIG_CONFIDENCE_THRESHOLD=0.6
DRAW_TRACKING=False
LOG_LEVEL=INFO
OUTPUT_VIDEO_PATH=/files
# OC-SORT anti-ID-switch tuning:
TRACKER_LOST_TRACK_BUFFER=20
TRACKER_MIN_CONSECUTIVE_FRAMES=5
COUNTING_GUARD_MAX_AGE=15
COUNTING_REID_WINDOW=15
COUNTING_LOST_BUFFER_FRAMES=60
```
Full parameter table and per-parameter rationale:
[`docs/04_configuration.md`](docs/04_configuration.md).

---

## Tests

```bash
cd app && python -m pytest ../tests/ -v     # unit tests for counting/inference/tracking/rendering
```

---

## License / scope

Internal project for animal-counting on a Jetson Orin. Hardware-specific
(TensorRT engine, `/dev/video0`, X11 display, K3s on a single node).