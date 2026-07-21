# 01 — Quick start

Get from a **flashed Jetson** to a **running counting app** in ~5 minutes,
driven entirely by the `scripts/` hub.

> If the Jetson is not flashed yet, see [`02_setup.md`](02_setup.md) first.

## 1. Prerequisites on your control machine (Ubuntu/Debian)

```bash
sudo bash scripts/install_ansible.sh     # installs ansible, sshpass, nmap, curl, git
pip install --user jq 2>/dev/null || sudo apt install -y jq   # needed by validate_on_jetson.sh
```

## 2. Configure credentials

`.env.local` (repo root, gitignored) holds the connection details used by all
scripts and Ansible. Create it from the example and edit:

```bash
cp .env.local.example .env.local
```

Required keys:

```ini
JETSON_USER=nano-counter                 # SSH user on the Jetson
JETSON_PASSWORD=***                      # SSH password (sshpass)
WIFI_NETWORK=192.168.0.0/24              # CIDR scanned by jetson_discover.sh
JETSON_HOTSPOT_SSID=animal-counter        # informational
JETSON_ETH_IP=192.168.1.158              # informational (discovery overrides this)
```

> The Jetson IP is **not** hardcoded: `jetson_discover.sh` scans `WIFI_NETWORK`
> for hosts with port 22 open and tries the SSH credentials on each. The result
> is cached in `/tmp/jetson_env.sh` and reused while it still answers SSH.

## 3. Discover + deploy (one shot)

> **Prerequisite:** the app ships no model. Before this, a detection model
> must have been trained from a **versioned Roboflow dataset** (operator
> versions it on Roboflow; `scripts/training_model.sh` fetches that version,
> trains YOLO locally, exports ONNX, compiles the TensorRT engine). See
> [`02_setup.md`](02_setup.md#before-you-deploy--train--version-a-model-on-roboflow)
> and [`03_deployment.md`](03_deployment.md#model-build--roboflow-dataset--yolo--onnx--tensorrt-engine).

```bash
bash scripts/prepare_jetson.sh
```

What it does, in order:
1. `scripts/jetson_discover.sh` — nmap scan + SSH credential test → `JETSON_IP`
2. `scripts/jetson_first_access.sh` — confirms SSH works
3. `ansible-playbook -i ansible/inventory/jetsons.yml
   ansible/playbooks/app/deploy_app.yml` — renders the K3s templates and
   applies them (namespace, DaemonSet, service, filebrowser, video-compress)

On success the app runs and displays the live camera feed + counting line on
the Jetson's attached screen (the on-screen X11/cv2 window). There is no web
UI; the `countingapp-svc` port `31501` is declared but the app does not serve
HTTP.

## 4. Operate

Open the app on the Jetson's attached screen (the on-screen X11/cv2 window).
Use the on-screen buttons to **start** counting, move pigs past the camera, and
**read the counter**. A video clip is recorded automatically while pigs are
detected (stops ~2 min after the last detection). Power off when done.

## 5. Validate counting (developer loop)

To check that counting logic still matches the reference videos:

```bash
# Validate only the videos listed in validation/expected_counts.json (.videos)
bash scripts/validate_on_jetson.sh --full

# Single reference video from validation/config.json
bash scripts/validate_on_jetson.sh
```

A pass means the app's count equals the expected count (tolerance = 0 by
default). The report is written to `validation-report.json`. Full details:
[`06_validation.md`](06_validation.md).

## 6. Reconfigure / redeploy

- **Change a runtime parameter** (thresholds, line offset…): edit `app/.env`
  on the Jetson (`/data/orin/git/animal-counting/app/.env`, the hostPath
  mounted into the pod) and restart the pod — no rebuild needed:
  `ssh $JETSON_USER@$JETSON_IP "kubectl delete pod -n countingapp-dev -l app=countingapp"`
- **Change a manifest** (resources, image…): edit the Jinja2 template in
  `k3s/templates/` and re-run the `deploy_countingapp.yml` playbook.
- **Rebuild the model** (after retraining): `bash scripts/training_model.sh`,
  then rebuild the TensorRT engine (`build-engine-batch.j2`).

See [`04_configuration.md`](04_configuration.md) for the full parameter list.

## Troubleshooting

- Discovery finds nothing → Jetson powered on? on the same LAN? `WIFI_NETWORK`
  CIDR correct? `JETSON_PASSWORD` correct?
- App not reachable → `kubectl get pod,svc -n countingapp-dev` on the Jetson;
  the DaemonSet may be paused (`nodeSelector: validate-paused=true`) — remove
  the node label to resume.
- More in [`07_troubleshooting.md`](07_troubleshooting.md).