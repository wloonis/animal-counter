# 02 — Jetson setup

From a blank Jetson Orin to a device ready for app deployment. Covers flashing
JetPack, first boot, system preparation, and K3s installation.

> For the 5-minute deploy-after-flash path, see [`01_quickstart.md`](01_quickstart.md).

## Hardware

- NVIDIA Jetson Orin (tested on **Orin Nano 8 GB "Super"** dev kit)
- microSD card ≥ 64 GB (or NVMe)
- USB webcam (the app reads `/dev/video0`)
- Keyboard / mouse / HDMI monitor for first boot (X11 display is used by the app)
- Network: same LAN as your control machine, or the Jetson's own WiFi hotspot

## 1. Flash JetPack

The application targets **JetPack 6.2 / L4T R36.4.0+** (the container base is
`dustynv/l4t-pytorch:r36.4.0`). Flashing is done the standard NVIDIA way on the
host PC:

1. Download **JetPack 6.2** (SD-card image) from
   <https://developer.nvidia.com/embedded/jetpack>.
2. Format the SD card with **SD Card Formatter** (<https://www.sdcard.org/downloads/formatter/>).
3. Flash the image with **BalenaEtcher** (<https://www.balena.io/etcher/>)
   (you may skip the post-flash verification).
4. Insert the SD card, connect keyboard/mouse/monitor/camera, power on.

> JetPack 6.1 Rev.1 also works and enables the "Super Orin Nano" mode on the
> dev kit. Anything older is not supported.

> **SD card not recognized by the flasher / Windows?** It is **not necessarily
> defective.** A card that Windows refuses to mount or that BalenaEtcher / SD
> Card Formatter can't see often just has a corrupted or missing partition
> table. Open **Windows Disk Management** (`diskmgmt.msc`) or **diskpart**,
> delete all existing partitions on the SD card, create a single new simple
> volume (FAT32 or exFAT), and the card will reappear — then retry the
> flasher. (In `diskpart`: `list disk` → `select disk <N>` → `clean` →
> `create partition primary` → `format fs=fat32 quick` → `assign`.) This
> recovers most "dead" SD cards without replacing them.

## 2. First boot

Complete the Ubuntu setup wizard (locale, timezone, user). Create the user
that the scripts will SSH into — the validated setup uses **`nano-counter`**;
set the same in `.env.local` (`JETSON_USER` / `JETSON_PASSWORD`).

After first boot, ensure:
- SSH is enabled (`sudo systemctl enable --now ssh`).
- The Jetson is on the same network as the control machine (WiFi or Ethernet).
- The webcam is at `/dev/video0` (`ls -l /dev/video0`).

## 3. Install Ansible on the control machine

On **your** machine (not the Jetson):

```bash
sudo bash scripts/install_ansible.sh     # ansible + sshpass + nmap + curl + git
```

## 4. Configure `.env.local`

```bash
cp .env.local.example .env.local   # set JETSON_USER, JETSON_PASSWORD, WIFI_NETWORK
```

See [`01_quickstart.md`](01_quickstart.md) §2 for the keys.

## 5. System preparation (optional, via Ansible)

The repo ships Ansible playbooks under `ansible/playbooks/system/`:

| Playbook | Purpose |
|----------|---------|
| `prepare_system.yml` | Base packages, user, sudoers, timezone |
| `network_ssh.yml` | Network + SSH hardening |
| `install_k3s_with_docker_tasks.yml` | Install Docker + K3s (single-node) |
| `hotspot_setup.yml` | WiFi hotspot for offline operation |
| `install_lxde.yml` | LXDE desktop (kiosk-style boot into the app) |
| `configure_splash_screen.yml` | Splash screen while the app loads; block LXDE until the pod is up |
| `diagnose_splash_screen.yml` | Diagnose splash-screen issues |

Run any of them directly, e.g.:

```bash
export ANSIBLE_HOST_KEY_CHECKING=False
ansible-playbook -i ansible/inventory/jetsons.yml ansible/playbooks/system/install_k3s_with_docker_tasks.yml
```

`scripts/prepare_jetson.sh` is the one-shot wrapper that handles discovery +
app deployment; the system playbooks above are the building blocks when you
need finer control.

## 6. Verify the cluster

On the Jetson:

```bash
kubectl get nodes
kubectl get pods -A
```

You should see `coredns`, `metrics-server`, `local-path-provisioner`, and
`nvidia-device-plugin` running. The counting app itself is deployed next by
`prepare_jetson.sh` / `deploy_app.yml` — see [`03_deployment.md`](03_deployment.md).

## Before you deploy — train + version a model on Roboflow

The app ships **no model**. Before the first deployment, the operator must
have **prepared and versioned a dataset on Roboflow** that
`ansible/playbooks/model/build_model.yml` can fetch. The pipeline downloads
that Roboflow version and trains YOLO locally → `my_model.pt` → ONNX → TensorRT
engine (see [Model build](03_deployment.md#model-build--roboflow-dataset--yolo--onnx--tensorrt-engine)).
Without it the app has nothing to run.

Once, before deploying:

1. On Roboflow: create/version the dataset (and train, if you train on Roboflow
   directly). Note the `workspace`, `project`, `version`, and `format`; generate
   an API key.
2. Put them in `.env.local` as `TRAINING_ROBOFLOW_WORKSPACE`,
   `TRAINING_ROBOFLOW_PROJECT`, `TRAINING_ROBOFLOW_VERSION`,
   `TRAINING_ROBOFLOW_FORMAT`, `TRAINING_ROBOFLOW_API_KEY`
   (+ `TRAINING_MODEL`, `epochs`, `imgsz`).
3. Build the model on the Jetson: `bash scripts/training_model.sh` (fetches the
   Roboflow version, trains locally, exports ONNX), then compile the TensorRT
   engine (`build-engine-batch.j2` / the `build-engine` container mode).

Only then proceed to deploy.

## Next

- Deploy the app: [`bash scripts/prepare_jetson.sh`](01_quickstart.md)
- Or manually: [`03_deployment.md`](03_deployment.md)