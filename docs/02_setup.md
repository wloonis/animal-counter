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

Complete the Ubuntu setup wizard. During the wizard, set exactly:

- **Username:** `nano-counter` (the scripts SSH into this user — it must
  match `JETSON_USER` in `.env.local`).
- **Computer name (hostname):** `nano-counter-desktop` (this is the hostname
  K3s registers as the node name; the deployment expects it).
- **Connect to your box / router WiFi** during setup (so the Jetson has
  internet for the next steps — package installs, K3s download, etc.). This is
  the internet WiFi connection that will later be pinned to a static IP by
  `configure_static_wifi.yml`.

> The wizard may offer to install **Chromium** — **skip it**, it is not needed
> (the countingapp runs headless in K3s; no browser is required on the Jetson).

Set the same credentials in `.env.local` (`JETSON_USER` / `JETSON_PASSWORD`).

After first boot, ensure:
- SSH is enabled (`sudo systemctl enable --now ssh`).
- The Jetson is on the same network as the control machine (WiFi or Ethernet).
- The webcam is at `/dev/video0` (`ls -l /dev/video0`).

### 2.1 (Optional) Migrate to NVMe SSD — drop the SD card

After the setup is complete, you can optionally move the root filesystem to an
**NVMe SSD** for reliability and speed. Follow the
[**JetsonHacks `migrate-jetson-to-ssd`**](https://github.com/jetsonhacks/migrate-jetson-to-ssd)
project's instructions — it clones the SD-card rootfs onto the NVMe drive and
points the boot config at it. Once done, **the SD card is no longer needed**
(the Jetson boots from the NVMe SSD; you can remove the SD card).

> Do this **after** the first-boot setup wizard is complete (the migration
> copies the already-configured rootfs, so the `nano-counter` user, hostname,
> and WiFi connection are preserved on the SSD).

Procedure:

1. From the control machine, discover the Jetson's IP:
   ```bash
   ./scripts/jetson_discover.sh
   ```
2. SSH into it:
   ```bash
   ssh nano-counter@<IP>
   ```
3. Create the tools directory under `/data`:
   ```bash
   sudo mkdir -p /data/tools
   ```
4. Enter it and clone the JetsonHacks project:
   ```bash
   cd /data/tools
   git clone https://github.com/jetsonhacks/migrate-jetson-to-ssd.git
   cd migrate-jetson-to-ssd
   ```
5. Follow the project's `README.md` from there (it scripts the rootfs clone
   onto the NVMe drive + the boot-config switch). Reboot when it tells you to,
   then remove the SD card.

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