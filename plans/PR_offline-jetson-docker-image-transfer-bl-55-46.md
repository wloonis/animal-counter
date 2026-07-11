# Plan: Offline Jetson Docker Image Transfer (BL-55 / #46)

## Summary
Two PC-side shell scripts to relay a `countingapp:local` (~20 Go) Docker image from a test Jetson to the PC, then from the PC to an offline production Jetson — using `docker save`/`docker load` only, no registry, no internet on the target. Plus `.gitignore` entry and documentation.

## In Scope
- `scripts/save_image.sh` (new): sources `.env.local`, calls `scripts/jetson_discover.sh` for the test Jetson IP, streams `sudo docker save | gzip` over SSH to `save/<image>-<tag>.tar.gz` on the PC, verifies `gzip -t` + size recap.
- `scripts/load_image.sh` (new): targets the offline Jetson via `JETSON_HOTSPOT_IP` (strips CIDR suffix to get raw IP), `rsync -P --partial` the tar to a dedicated backup directory on the target, SSH-loads via `gunzip -c | docker load`, verifies `docker images`, restarts the countingapp DaemonSet pod, optional `--cleanup`.
- `.gitignore`: add `save/` entry.
- `docs/10_offline_image_transfer.md` (new): usage guide for both scripts.
- Both scripts executable (git mode 100755).

## Out of Scope
- Changes to counting application code (counting.py, main.py, tracker, guard).
- Copying `/var/lib/docker` (overlayfs corruption risk).
- Docker registry usage.
- Internet access on the production target.
- `--full` validation mode.

## Architecture Decisions
- **`docker save` / `docker load` only** — no registry, no `/var/lib/docker` copy. Avoids overlayfs corruption and works fully offline.
- **Single-pass streaming save** — `ssh test-jetson 'sudo docker save IMG | gzip' > save/file.tar.gz`. No intermediate temp file on the Jetson (disk-constrained device).
- **rsync with `--partial` for load transfer** — resumable transfer of the ~20 Go tar to the offline target over wifi (unreliable link).
- **Distant sudo via `echo "$JETSON_PASSWORD" | sudo -S`** — matches existing ansible/playbooks pattern and `scripts/jetson_discover.sh` sshpass approach.
- **Reuse `scripts/jetson_discover.sh`** for test Jetson IP discovery; production target IP passed explicitly as argument (not auto-discovered, since it's offline/on a different network).
- **Reuse `.env.local` vars**: `IMAGE_NAME` (default `countingapp`), `IMAGE_TAG` (default `local`), `JETSON_USER`, `JETSON_PASSWORD`, `JETSON_HOTSPOT_IP` (stripped of CIDR `/24` suffix → raw IP for the offline target), `APP_NAMESPACE` (`countingapp-dev`).
- **`save/` at repo root, gitignored** — holds the ~20 Go tar.gz on the PC, never committed.
- **Dedicated backup directory on target** — rsync to `/data/orin/save/` (not `FILES_PATH` which is the videos dir); script creates it via `mkdir -p` on the target before transfer.
- **Pod restart via `k3s kubectl rollout restart daemonset countingapp -n countingapp-dev`** — namespace from `APP_NAMESPACE`.

## Tasks
- [ ] Task 1: CREATE `scripts/save_image.sh` (100755) — Sources `.env.local`, validates required vars (`JETSON_PASSWORD`, `IMAGE_NAME`, `IMAGE_TAG`), calls `scripts/jetson_discover.sh` to resolve test Jetson IP (or accepts `JETSON_IP` override). Creates `save/` dir if missing. **Cleans up stale temp files**: removes any existing `save/$IMAGE_NAME-$IMAGE_TAG.tar.gz` and any `save/*.tmp` partial files from a previous interrupted run before starting. Streams `sshpass ssh $JETSON_USER@$JETSON_IP 'echo "$JETSON_PASSWORD" | sudo -S docker save $IMAGE_NAME:$IMAGE_TAG | gzip' > save/$IMAGE_NAME-$IMAGE_TAG.tar.gz` (single pass, no intermediate temp on Jetson). Runs `gzip -t` on the output, prints size (human-readable) + recap. Exit non-zero on any failure.
- [ ] Task 2: CREATE `scripts/load_image.sh` (100755) — Derives target IP from `JETSON_HOTSPOT_IP` env var (strip CIDR `/24` suffix → raw IP, e.g. `192.168.100.1`). Validates `save/$IMAGE_NAME-$IMAGE_TAG.tar.gz` exists locally. Creates remote backup dir: `sshpass ssh $JETSON_USER@$TARGET 'mkdir -p /data/orin/save'`. `rsync -P --partial save/<tar> $JETSON_USER@$TARGET:/data/orin/save/` for resumable transfer. SSH to target: `echo "$JETSON_PASSWORD" | sudo -S sh -c 'gunzip -c /data/orin/save/<tar> | docker load'`. Verify image loaded via `docker images | grep $IMAGE_NAME`. Restart pod: `echo "$JETSON_PASSWORD" | sudo -S k3s kubectl rollout restart daemonset countingapp -n $APP_NAMESPACE`. Verify: `k3s kubectl get pods -n $APP_NAMESPACE`. Optional `--cleanup` flag: delete tar on target (`rm /data/orin/save/<tar>`) and on PC (`rm save/<tar>`). Exit non-zero on any failure.
- [ ] Task 3: EDIT `.gitignore` — Add `save/` entry (with comment) so the ~20 Go tar is never committed.
- [ ] Task 4: CREATE `docs/10_offline_image_transfer.md` — Document both scripts: prerequisites (nmap, sshpass, rsync installed on PC; `.env.local` vars `IMAGE_NAME`, `IMAGE_TAG`, `JETSON_USER`, `JETSON_PASSWORD`, `FILES_PATH`, `APP_NAMESPACE`), step-by-step usage (save from test → load to offline), expected output, `--cleanup` flag, troubleshooting (wifi drop → rsync resume, sudo password issues, disk space checks).
- [ ] Task 5: VERIFY executability — Ensure `scripts/save_image.sh` and `scripts/load_image.sh` have git mode 100755 (run `git update-index --chmod=+x` or `chmod +x` as needed).

## Validation
- `shellcheck scripts/save_image.sh scripts/load_image.sh` — no syntax errors.
- `git status` — `save/` does not appear as untracked (gitignore works).
- `ls -la scripts/save_image.sh scripts/load_image.sh` — both have execute bit.
- Dry-run check: `bash -n scripts/save_image.sh && bash -n scripts/load_image.sh` — parse without error.
- **End-to-end (requires hardware — same test Jetson used for both save and load):**
  1. Run `./scripts/save_image.sh` from PC → produces `save/countingapp-local.tar.gz` (~20 Go) with `gzip -t` passing.
  2. **MANUAL CHECKPOINT**: The user must switch the Jetson to hotspot mode (so the PC connects via the Jetson's WiFi hotspot at `JETSON_HOTSPOT_IP`). The script does NOT do this automatically — pause and wait for user confirmation.
  3. After the Jetson is in hotspot mode, run `./scripts/load_image.sh` → connects to `JETSON_HOTSPOT_IP`, rsyncs the tar to `/data/orin/save/` on the target, loads the image via `docker load`.
  4. Verify `docker images` on the target shows the same image ID as the test Jetson.
  5. Pod restarts via `rollout restart` and `get pods` shows Running.
- `git status` clean (no `save/` artifacts tracked).

## Risks
- **~20 Go transfer over wifi is slow and may drop** — mitigated by rsync `--partial` (resumable) and single-pass streaming on save side.
- **Disk space on PC and target** — scripts should check available space before transfer; document the ~20 Go requirement.
- **Sudo password in plaintext via echo pipe** — same pattern as existing ansible/playbooks; `.env.local` is gitignored. Document the security note.
- **`jetson_discover.sh` finds the wrong Jetson** (save side) — user can override `JETSON_IP` in `.env.local` or env; document this escape hatch.
- **`JETSON_HOTSPOT_IP` has CIDR suffix** — script must strip `/24` to get raw IP (`192.168.100.1`); document this in the script header.
- **k3s pod doesn't pick up new image** — `imagePullPolicy: Never` means it uses local image; `rollout restart` forces recreation. Verify via `docker images` ID match between test and prod.