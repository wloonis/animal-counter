# 08 — Offline Jetson Docker Image Transfer

Transfer a `countingapp:local` Docker image (~20 Go) from a **test Jetson** to
the **PC**, then from the PC to an **offline production Jetson** — no internet,
no registry, no `/var/lib/docker` copy. Uses `docker save`/`docker load` only,
with the PC acting as a relay over WiFi.

This implements [GitHub issue BL-55 (#46)](https://github.com/user/repo/issues/46).

## When to use this

The production Jetson has no internet access. You've rebuilt the
`countingapp:local` image on a test Jetson (which has internet for `apt` /
`pip`), and need to push that image to the production Jetson to deploy an
update. The PC can reach both Jetsons over WiFi.

## Prerequisites (PC)

Install these tools on the PC (control machine):

```bash
sudo apt install nmap sshpass rsync
```

### `.env.local` variables

Ensure these are set in `.env.local` (see `.env.local.example` for the full
template):

| Variable | Example | Used by |
|----------|---------|---------|
| `JETSON_USER` | `nano-counter` | SSH user on both Jetsons |
| `JETSON_PASSWORD` | `change-me` | sudo/SSH password (sshpass) |
| `IMAGE_NAME` | `countingapp` | Docker image name |
| `IMAGE_TAG` | `local` | Docker image tag |
| `APP_NAMESPACE` | `countingapp-dev` | K3s namespace for the pod |
| `JETSON_HOTSPOT_IP` | `192.168.100.1/24` | Offline target IP (CIDR stripped automatically) |
| `WIFI_NETWORK` | `192.168.0.0/24` | Network scanned by `jetson_discover.sh` (test Jetson) |

> **Note:** `JETSON_IP` is auto-discovered by `jetson_discover.sh` for the
> test Jetson. You can override it in `.env.local` if discovery finds the
> wrong device.

## Workflow overview

```
Test Jetson (internet)          PC (control)          Offline Jetson (hotspot)
  docker save ──ssh/gzip──>  save/<tar>.tar.gz  ──rsync──>  /data/orin/save/
                                                                docker load
                                                          k3s rollout restart
```

## Step 1: Save the image from the test Jetson

Ensure the PC is on the same network as the test Jetson (e.g. your home WiFi
or the `WIFI_NETWORK` in `.env.local`).

```bash
./scripts/save_image.sh
```

The script will:
1. Source `.env.local` for credentials and image name/tag.
2. Run `scripts/jetson_discover.sh` to find the test Jetson IP (or use
   `JETSON_IP` if already set).
3. Clean up any stale `save/*.tar.gz` or `save/*.tmp` files from a previous
   interrupted run.
4. Stream `sudo docker save <image>:<tag> | gzip` over SSH directly to
   `save/<image>-<tag>.tar.gz` on the PC (single pass, no intermediate temp
   on the Jetson).
5. Verify the gzip integrity with `gzip -t`.
6. Print the file size (human-readable) and a recap.

### Expected output

```
🔎 JETSON_IP not set — running jetson_discover.sh...
...
🎯 Test Jetson IP: 192.168.0.180
🧹 Removing stale save/countingapp-local.tar.gz from a previous run...
📦 Saving countingapp:local from nano-counter@192.168.0.180...
   → save/countingapp-local.tar.gz (streaming, single pass)
🔍 Verifying gzip integrity...
✅ gzip integrity OK

════════════════════════════════════════════════════════════
✅ Image saved successfully
   Source : nano-counter@192.168.0.180:countingapp:local
   File  : save/countingapp-local.tar.gz
   Size  : 18G
════════════════════════════════════════════════════════════
```

> **Tip:** If the transfer is interrupted, simply re-run the script — it
> cleans up stale files before starting.

## Step 2: Switch the test Jetson to hotspot mode (MANUAL)

> ⚠️ **This is a manual checkpoint.** The script does not do this automatically.

Before loading the image, the target Jetson must be in **WiFi hotspot mode**
so the PC can connect to it at `JETSON_HOTSPOT_IP` (e.g. `192.168.100.1`).

1. Switch the Jetson to hotspot mode (via `nmcli` or the Ansible playbook).
2. Connect the PC to the Jetson's WiFi hotspot (SSID: `JetsonHotspot` by
   default, password: `JETSON_HOTSPOT_PASSWORD`).
3. Verify connectivity:
   ```bash
   sshpass -p "$JETSON_PASSWORD" ssh nano-counter@192.168.100.1 "echo connected"
   ```
4. Proceed to Step 3.

## Step 3: Load the image onto the offline Jetson

From the PC (now connected to the Jetson's hotspot):

```bash
./scripts/load_image.sh
```

Or with cleanup (deletes the tar on both target and PC after successful load):

```bash
./scripts/load_image.sh --cleanup
```

The script will:
1. Read `JETSON_HOTSPOT_IP` from `.env.local`, strip the CIDR suffix
   (`/24`) to get the raw IP (e.g. `192.168.100.1`).
2. Validate that `save/<image>-<tag>.tar.gz` exists locally on the PC.
3. Create `/data/orin/save/` on the target (a dedicated backup directory,
   not the videos `FILES_PATH`).
4. `rsync -P --partial` the tar to the target — resumable if WiFi drops.
5. Load the image on the target: `sudo sh -c 'gunzip -c <tar> | docker load'`.
6. Verify the image appears in `docker images` on the target.
7. Restart the countingapp pod: `sudo k3s kubectl rollout restart daemonset
   countingapp -n countingapp-dev`.
8. Check pod status with `k3s kubectl get pods`.
9. If `--cleanup`: delete the tar on the target and on the PC.

### Expected output

```
🎯 Target (offline) Jetson IP: 192.168.100.1 (from JETSON_HOTSPOT_IP=192.168.100.1/24)
📦 Local tar: save/countingapp-local.tar.gz (18G)
📁 Creating remote backup directory (/data/orin/save)...
📡 Rsyncing save/countingapp-local.tar.gz to nano-counter@192.168.100.1:/data/orin/save/ ...
   (resumable via --partial — re-run if wifi drops)
✅ Rsync complete
🐳 Loading image on target via docker load...
✅ Image loaded
🔍 Verifying image presence on target...
✅ Image verified on target:
   countingapp   local   1a2b3c4d5e6f   2 days ago   18GB
🔄 Restarting countingapp DaemonSet (rollout restart)...
⏳ Waiting 10s for pod to restart...
🔍 Checking pod status...
NAME                READY   STATUS    RESTARTS   AGE
countingapp-xxxxx   1/1     Running   0          10s

════════════════════════════════════════════════════════════
✅ Image loaded and pod restarted
   Target : nano-counter@192.168.100.1
   Image  : countingapp:local
   Namespace : countingapp-dev
   Tar on target : /data/orin/save/countingapp-local.tar.gz (use --cleanup to remove)
   Tar on PC     : save/countingapp-local.tar.gz
════════════════════════════════════════════════════════════
```

## `--cleanup` flag

After a successful load, you may want to reclaim disk space (~20 Go on each
side). Pass `--cleanup` to delete the tar on both the target and the PC:

```bash
./scripts/load_image.sh --cleanup
```

Without `--cleanup`, the tars remain:
- **Target:** `/data/orin/save/<image>-<tag>.tar.gz`
- **PC:** `save/<image>-<tag>.tar.gz`

## Troubleshooting

### WiFi drop during rsync

rsync uses `--partial`, so an interrupted transfer resumes on re-run. Just
re-run `./scripts/load_image.sh` — the partial file on the target will be
completed, not restarted from scratch.

### Sudo password issues

The scripts use `echo "$JETSON_PASSWORD" | sudo -S` (same pattern as the
Ansible playbooks' `become` method). If you see `sudo: a password is
required` errors:
- Verify `JETSON_PASSWORD` is correct in `.env.local`.
- Ensure the Jetson user has sudo privileges without a TTY:
  `sudo -S` reads the password from stdin, which works over SSH.

### Disk space

The image tar is ~20 Go. Before running:

```bash
# Check PC disk space
df -h .

# Check target disk space
sshpass -p "$JETSON_PASSWORD" ssh nano-counter@192.168.100.1 "df -h /data/orin"
```

You need at least ~20 Go free on both the PC (`save/`) and the target
(`/data/orin/save/`).

### `jetson_discover.sh` finds the wrong Jetson

If multiple devices respond on port 22, the discovery may connect to the
wrong one. Override it:

```bash
# In .env.local:
JETSON_IP=192.168.0.180

# Or inline:
JETSON_IP=192.168.0.180 ./scripts/save_image.sh
```

### Pod doesn't pick up the new image

The countingapp DaemonSet uses `imagePullPolicy: Never` (local image only).
The `rollout restart` forces pod recreation, which re-reads the local image.
If the pod is stuck:

```bash
# Check pod status
sshpass -p "$JETSON_PASSWORD" ssh nano-counter@192.168.100.1 \
  "echo '$JETSON_PASSWORD' | sudo -S k3s kubectl get pods -n countingapp-dev"

# Force delete the pod
sshpass -p "$JETSON_PASSWORD" ssh nano-counter@192.168.100.1 \
  "echo '$JETSON_PASSWORD' | sudo -S k3s kubectl delete pod -l app=countingapp -n countingapp-dev"
```

## Security note

The sudo password is passed via `echo "$JETSON_PASSWORD" | sudo -S` over SSH.
This matches the existing Ansible playbook `become` pattern. The password is
stored in `.env.local` which is gitignored (see `!.env.local.example` for the
template). Never commit real credentials.
