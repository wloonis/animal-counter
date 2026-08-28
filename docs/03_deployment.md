# 03 — Deployment (K3s + Ansible)

How the app is packaged, deployed, and run on the Jetson's single-node K3s
cluster. The real manifests are the **Jinja2 templates in `k3s/templates/`**,
rendered and applied by **Ansible** (`ansible/playbooks/app/deploy_countingapp.yml`).

## Container image

`app/Dockerfile` builds on `dustynv/l4t-pytorch:r36.4.0` (JetPack 6.2) and
installs `pycuda`, `trackers==2.4.0` (OC-SORT), `flask`, `python-dotenv`. The
entrypoint (`app/entrypoint.sh`) takes a **mode**:

| Mode | Purpose |
|------|---------|
| `build-engine` | `trtexec` compiles `model/my_model.onnx` → `my_model.engine` |
| `serve` | Run `python3 src/main.py` (on-screen X11/cv2 UI + inference/display threads) — production |
| `validate` | Run `main.py --input=FILE --file=$VALIDATE_VIDEO` and emit `result.json` (validation job) |
| `test` / `debug` | Local test video / keep-alive for `kubectl exec` |

The image is built **on the Jetson** (aarch64 + CUDA) and tagged
`countingapp:local` (imagePullPolicy `Never` — local only).

## Ansible inventory

`ansible/inventory/jetsons.yml` defines a single host `jetson-01` whose
connection is **env-driven**:

```yaml
ansible_host: "{{ lookup('env', 'JETSON_IP') }}"
ansible_user: "{{ lookup('env', 'JETSON_USER') | default('nano-counter') }}"
ansible_ssh_pass: "{{ lookup('env', 'JETSON_PASSWORD') | default(omit) }}"
```

So `JETSON_IP` / `JETSON_USER` / `JETSON_PASSWORD` (from `.env.local`, set by
`jetson_discover.sh`) drive everything.

## Playbooks

| Playbook | What it does |
|----------|--------------|
| `app/build_countingapp.yml` | Build the `countingapp:local` image on the Jetson |
| `app/deploy_app.yml` | Discover + deploy (wrapped by `scripts/prepare_jetson.sh`) |
| `app/deploy_countingapp.yml` | Render all `k3s/templates/*.j2` and `kubectl apply` them |
| `model/build_model.yml` | Train the model from a Roboflow dataset version (wrapped by `scripts/training_model.sh`) — see [Model build](#model-build--roboflow-dataset--yolo--onnx--tensorrt-engine) below |
| `system/install_k3s_with_docker_tasks.yml` | Install Docker + K3s (single-node) |
| `system/prepare_system.yml`, `network_ssh.yml`, `hotspot_setup.yml`, `install_lxde.yml`, `configure_splash_screen.yml`, `diagnose_splash_screen.yml` | System setup (see [`02_setup.md`](02_setup.md)) |

`deploy_countingapp.yml` renders each `*.j2` into `$K3S_APP_PATH/*.yaml` and
applies them with `k3s kubectl apply -f`. Defaults (paths,
ports) come from `ansible/group_vars/all.yml`.

## Model build — Roboflow dataset → YOLO → ONNX → TensorRT engine

The detection model is **trained from a dataset version the operator prepares
on Roboflow** — the repo does not ship a model. `ansible/playbooks/model/build_model.yml`
(wrapped by `scripts/training_model.sh`) automates the full chain, driven by
`TRAINING_ROBOFLOW_*` env vars (set in `.env.local`):

1. **Fetch the dataset version from Roboflow** — calls the Roboflow API
   (`https://api.roboflow.com/{workspace}/{project}/{version}/{format}?api_key=…`)
   to get the export link, then downloads + unarchives the dataset zip. The
   version is the Roboflow dataset export the operator built/versioned on
   Roboflow (`TRAINING_ROBOFLOW_WORKSPACE`, `TRAINING_ROBOFLOW_PROJECT`,
   `TRAINING_ROBOFLOW_VERSION`, `TRAINING_ROBOFLOW_FORMAT`,
   `TRAINING_ROBOFLOW_API_KEY`).
2. **Train YOLO locally** (on the dev machine, `delegate_to: localhost`, using
   the local ultralytics venv) → `model/my_model.pt` (`TRAINING_MODEL`,
   `epochs`, `imgsz`).
3. **Export to ONNX** — `yolo export model=my_model.pt format=onnx` →
   `model/my_model.onnx`.
4. **Compile the TensorRT engine on the Jetson** — the container's `build-engine`
   mode runs `trtexec` to compile `model/my_model.onnx` → `model/my_model.engine`
   (the engine `serve` mode loads at runtime; see `app/src/core/inference.py`).
   The build precision + imgsz are **per-model** via `app/build-config.json`
   (keyed by `MODEL_NAME`): `fp16` for imgsz=1280 models (~15 FPS on Orin
   Nano), `fp32` for legacy 640 pig models (30 FPS). The model artifact is
   named after the dataset dir (`model_name = basename(TRAINING_PROJECT_DIR)`;
   fallback `my_model`). See `docs/04_configuration.md`.
5. **Per-model input source** (BL-93, startup-only) — `input_source`
   (`CAMERA`/`STREAM`/`FILE`), `input_url` (RTSP, drone 720p), `input_device`,
   `input_width`/`input_height`, `output_fps` are read **once at startup** from
   the active model's section in `/conf/runtime-settings.json` (falling back to
   env defaults). Switching the physical sensor (camera ↔ drone) is a restart,
   not a hot-swap. See `docs/04_configuration.md` + `docs/IPC_CONTRACT.md`.

> Prerequisite: the operator creates/versions a dataset on Roboflow and puts
> the `TRAINING_ROBOFLOW_*` values (including the Roboflow API key) in
> `.env.local`. Without a valid Roboflow version + API key, step 1 fails.
> This is a **pre-deployment step** — see
> [`02_setup.md`](02_setup.md#before-you-deploy--train--version-a-model-on-roboflow).

## K3s resources (what gets deployed)

| Template | Kind | Role |
|----------|------|------|
| `countingapp-ns.j2` | Namespace | `countingapp-dev` |
| `countingapp-dep.j2` | **DaemonSet** | The app pod (`countingapp:local`, `serve`), hostPaths for `/dev/video0`, `/app` (code), `/files` (videos/history/data), `/conf` (runtime-settings + `.arret_requested` config/contrôle — BL-79), `/tmp/.X11-unix` (X11), `/var/run/docker.sock` |
| `countingapp-svc.j2` | Service (ClusterIP) | `:31501` (declared containerPort named `web`; the operator UI is the on-screen X11/cv2 window, **not** HTTP — the app does not serve HTTP) — no externalIP |
| `cronvideo-dep.j2` | Deployment | Rolling ffmpeg compression (`tocompress-*` → `count*`, keep 50, delete `.mp4` > 2 GiB) |
| `countingapp-validate.j2` | Job | One-shot validation run (used by `validate_on_jetson.sh`) |
| `countingapp-test.j2` | Job | One-shot test run |
| `build-engine-batch.j2` | Job/CronJob | Build the TensorRT engine |

### The counting-app DaemonSet at a glance

```yaml
kind: DaemonSet
spec:
  selector: { app: countingapp }
  template:
    spec:
      terminationGracePeriodSeconds: 0   # ⚠️ could be raised to 30
      nodeSelector: { validate-paused: "true" }   # set only during validation
      containers:
      - name: countingapp
        image: countingapp:local
        args: ["serve"]
        env: [{ name: DISPLAY, value: ":0" }]
        ports: [{ name: web, containerPort: 31501 }]
        securityContext: { privileged: true }     # ⚠️ reducible
        resources:
          requests: { cpu: "500m", memory: "2Gi", nvidia.com/gpu: 1 }
          limits:   { cpu: "2",    memory: "4Gi", nvidia.com/gpu: 1 }
        volumeMounts: [dev-video0, dev-app(/app), files(/files), conf(/conf), dev-x11, docker-sock]
```

### Pausing the live app for validation

During a validation run the live DaemonSet would hog the camera/GPU, so
`validate_on_jetson.sh` patches the node selector:

```bash
kubectl patch daemonset countingapp -n countingapp-dev \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"validate-paused":"true"}}}}}'
```

With `validate-paused=true` on the node, the DaemonSet schedules 0 pods; the
validation Job runs alone. To **resume** the live app, remove the node label:

```bash
kubectl label node <node> validate-paused-
```

## Deploy / redeploy

```bash
# One-shot (discover + deploy)
bash scripts/prepare_jetson.sh

# Or just re-apply the manifests after editing a template
export ANSIBLE_HOST_KEY_CHECKING=False
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/app/deploy_countingapp.yml
```

## What is intentionally a hostPath (live code)

The pod mounts `/data/orin/git/animal-counting/app` at `/app` — i.e. the **live
source tree** of the host. This is **intentional**: it lets you rsync code and
restart the pod to iterate without rebuilding the image. The trade-off (no
immutability, the running version depends on the host checkout) is accepted for
this single-device edge deployment.

## Known production gaps

- The counter is **not persisted** — a pod restart during the day resets it to
  0. (The video is written correctly; only the in-memory tally is lost.)
- No `livenessProbe` on the `countingapp` pod.
- `privileged` security context + `docker.sock` mount (used by the validation
  Job's image rebuild; could be narrowed).
- `ffmpeg:latest` (compression cron image) is not pinned to a digest.

> The recording is now **finalized and renamed on every exit path** (end of
> source, SIGTERM, pod restart, web-UI stop) via `_finalize_recording` in
> `stop()` / the post-loop safety-net, so the previous "orphan
> `tmp-counting-*` / video not finalized on SIGTERM" gap is closed.