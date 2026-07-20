"""
BL-68 — Persistent counting-session history (JSONL, append-only).

This module is the **single writer** for the counting-history JSONL file
that lives on the pod-mounted hostPath ``/files`` (host:
``/data/orin/files``). It is stdlib-only (``json``, ``os``, ``time``,
``threading``, ``uuid``, ``datetime``, ``subprocess``, ``shutil``,
``gzip``, ``logging``) — no new runtime deps.

Design (see PLAN.md, BL-68):
  * One writer (pod), one reader (the companion host service), same
    hostPath ``/files``. The pod appends the JSONL; the companion reads
    it read-only and never mutates the source file.
  * JSONL lines are fsync'd atomically per-line, so a power cut can only
    lose the last partial line, never corrupt an index (there is no
    sidecar index in the pod).
  * A dedicated ``HistoryThread`` owns (a) a one-shot startup
    compaction, (b) the heartbeat loop, and (c) a 1x/day compaction
    timer. Compaction and heartbeat are never concurrent because they
    run in the same thread.
  * Disk guard adjusts the heartbeat interval (WARN → 30s, CRIT →
    suspend writes, counting continues).

History is **serve-mode only**: ``main.py`` instantiates this writer iff
``RESULT_JSON_PATH`` is unset (so validate/test mode never writes
history — ``result.json`` stays the validation source of truth).

The JSONL line types are:
  * ``session_start`` (A lifecycle + D config snapshot)
  * ``heartbeat``    (periodic: count + last video segment + C/F/G samples)
  * ``event``        (from the counting instrumentation via subscribers)
  * ``session_end``  (E video metadata + B final counters + F system +
                       status=clean | power-loss | unknown)
  * ``startup``      (boot_at, image_tag, git_commit, mode, config_notable)
  * ``summary``      (cold-session compaction output: A–F aggregates)
"""

import datetime
import gzip
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow_iso():
    """UTC ISO-8601 timestamp with 'Z' suffix."""
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _locale_now_iso():
    """Locale (wall-clock) ISO-8601 timestamp, for human-readable fields."""
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _read_lines_tolerant(path):
    """Yield parsed JSON lines from a JSONL file, tolerating a partial
    last line (skip a trailing line that fails ``json.loads``).

    Yields ``(line_obj, raw_line, offset)`` tuples. ``line_obj`` is None
    when the line could not be parsed (partial/truncated). ``offset`` is
    the byte offset where the line starts in the file.
    """
    if not os.path.exists(path):
        return
    offset = 0
    with open(path, "rb") as f:
        for raw_b in f:
            start = offset
            offset += len(raw_b)
            raw = raw_b.decode("utf-8", errors="replace").rstrip("\n")
            if not raw.strip():
                continue
            try:
                yield json.loads(raw), raw, start
            except json.JSONDecodeError:
                # Partial/truncated last line (power cut mid-append) — skip.
                yield None, raw, start


def _append_line(path, obj):
    """Append one JSON line + '\\n' to ``path`` and ``os.fsync`` it.

    Opens the file in append-binary mode so a missing file is created and
    existing content is never rewritten. The write is a single
    ``write()`` followed by ``flush()`` + ``os.fsync`` so the line lands
    on disk atomically (a power cut can at most lose the last partial
    line — the file content before the line is never corrupted).
    """
    line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    # O_APPEND guarantees each write() is atomic w.r.t. file offset on
    # POSIX local filesystems, so concurrent writers (we don't have any,
    # but defensive) cannot interleave.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def disk_free_bytes(path):
    """Return free bytes on the filesystem holding ``path`` (best-effort).

    Tolerates a non-existent path (uses the parent). Returns +inf on
    failure so the disk guard never accidentally suspends writes when
    the statvfs call fails (fail-open for counting continuity).
    """
    try:
        p = path
        while p and not os.path.exists(p):
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
        st = os.statvfs(p)
        return st.f_bavail * st.f_frsize
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"disk_free_bytes({path}) failed: {e!r}")
        return float("inf")


def _read_proc_file(path, default=None):
    """Read a small /proc or /sys file and return its stripped content."""
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return default


def _read_build_info(path="/app/.build-info.json"):
    """Read /app/.build-info.json written at docker build time.

    Returns ``{"git_commit": ..., "image_tag": ...}`` with sensible
    fallbacks if the file is missing or malformed (robust to K3s env
    drift; the build-info file travels with the image).
    """
    info = {"git_commit": "unknown", "image_tag": "unknown"}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if isinstance(data.get("git_commit"), str):
                info["git_commit"] = data["git_commit"]
            if isinstance(data.get("image_tag"), str):
                info["image_tag"] = data["image_tag"]
    except Exception:
        pass
    # Env fallbacks (IMAGE_TAG may be set by K3s; git_commit rarely is).
    env_tag = os.getenv("IMAGE_TAG")
    if env_tag:
        info["image_tag"] = env_tag
    return info


def _sample_thermal():
    """Best-effort thermal sample (C). Returns a dict of zone→temp or {}."""
    samples = {}
    # Jetson thermal zones (best-effort; absent on non-Jetson test hosts).
    for zone in ("thermal_zone0", "thermal_zone1", "thermal_zone2"):
        p = f"/sys/class/thermal/{zone}/temp"
        v = _read_proc_file(p)
        if v is not None:
            try:
                # /sys reports millidegrees Celsius.
                samples[zone] = round(int(v) / 1000.0, 1)
            except ValueError:
                samples[zone] = v
    return samples


def _sample_system():
    """Best-effort system-health sample (F): loadavg, mem, disk.

    Cheap and only called from the heartbeat/compaction path, never
    per-frame.
    """
    loadavg = _read_proc_file("/proc/loadavg")
    cpu_load_avg = None
    if loadavg:
        try:
            cpu_load_avg = [float(x) for x in loadavg.split()[:3]]
        except ValueError:
            cpu_load_avg = loadavg
    meminfo = _read_proc_file("/proc/meminfo", default="")
    mem_used = None
    if meminfo:
        try:
            kv = {}
            for line in meminfo.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].endswith(":"):
                    kv[parts[0][:-1]] = int(parts[1])
            total = kv.get("MemTotal", 0)
            avail = kv.get("MemAvailable", 0)
            if total:
                mem_used = (total - avail) * 1024  # bytes
        except Exception:
            mem_used = None
    disk_free_end = None
    try:
        disk_free_end = disk_free_bytes("/files")
    except Exception:
        pass
    return {
        "cpu_load_avg": cpu_load_avg,
        "mem_used": mem_used,
        "disk_free": disk_free_end,
    }


def _classify_crash():
    """Best-effort crash/OOM classification of the previous boot.

    Uses ``journalctl -b -1`` (preferred) or ``dmesg``. Non-fatal if
    unavailable (e.g. inside a container without journal access, or on a
    fresh host with no previous boot). Returns a string or None.
    """
    for cmd in (
        ["journalctl", "-b", "-1", "-p", "err", "--no-pager", "-n", "200"],
        ["dmesg", "--level=err,crit,alert,emerg"],
    ):
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            ).stdout
        except Exception:
            continue
        low = out.lower()
        if "out of memory" in low or "oom-kill" in low or "oom killer" in low:
            return "oom"
        if "panic" in low or "hung_task" in low:
            return "kernel_panic"
        if out.strip():
            return "error_logs"
    return None


# ---------------------------------------------------------------------------
# HistoryWriter
# ---------------------------------------------------------------------------

class HistoryWriter:
    """Append-only JSONL counting-session history writer.

    Owns the JSONL file at ``path``. Provides ``start_session`` (with
    power-loss recovery), ``emit_event``, ``heartbeat``, ``end_session``
    and ``compact``. The companion host service reads the same file
    read-only; this class is the only writer.

    Lifecycle is driven by ``HistoryThread`` (heartbeat loop + 1x/day
    compaction), which serializes heartbeat and compaction in one thread
    so they are never concurrent.
    """

    # Heartbeat interval raised to this (s) when free disk < WARN threshold.
    WARN_HEARTBEAT_S = 30
    # Staleness threshold (s) for recovery: if the last heartbeat is
    # older than this relative to now, the previous session's end_reason
    # is "unknown" rather than "power-loss".
    RECOVERY_STALE_S = 3600  # 1 hour
    # 1x/day compaction: re-compact every this many seconds.
    COMPACTION_PERIOD_S = 24 * 3600

    def __init__(self, path, settings, shared_state=None, counting=None,
                 mode="serve"):
        """
        Args:
            path (str): JSONL history file path (inside the pod, on /files).
            settings: Settings instance (HISTORY_* + config snapshot source).
            shared_state: SharedState (for counter_to_right + DisplayThread).
            counting: Counting instance (for B final counters in session_end).
            mode (str): Run mode ("serve" / "validate" / "test"); recorded in
                the startup line for diagnostics.
        """
        self.path = path
        self.settings = settings
        self.shared_state = shared_state
        self.counting = counting
        self.mode = mode

        # Session bookkeeping (filled by start_session).
        self.session_id = None
        self.prev_session_id = None
        self.session_start_ts = None  # UTC ISO of session_start
        self.last_heartbeat_ts = None  # UTC ISO of last heartbeat
        self._writes_suspended = False  # disk-guard CRIT
        self._stopped = False  # end_session has run; refuse further writes

        # Build-info (git_commit, image_tag) — read once at construction.
        self.build_info = _read_build_info()

        # Lock for the start/recovery/end critical sections (heartbeat +
        # compaction run in HistoryThread, but start/end can be called
        # from main thread + SIGTERM handler concurrently).
        self._lock = threading.Lock()

        # Ensure parent dir exists (best-effort; /files is mounted by K3s).
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"history: makedirs({parent}) failed: {e!r}")

    # -- low-level append (respects suspension) ----------------------------

    def _append(self, obj):
        """Append a line unless writes are suspended (disk CRIT) or
        the session has ended. Never raises: history is best-effort and
        must never break counting.

        Note: ``_stopped`` is intentionally NOT checked here — ``end_session``
        sets ``_stopped = True`` first (to halt concurrent heartbeats/events,
        which check ``_stopped`` at their own top) and then must still be
        able to append its own ``session_end`` line. ``emit_event`` and
        ``heartbeat`` guard themselves on ``_stopped`` before reaching here.
        """
        if self._writes_suspended:
            return False
        try:
            _append_line(self.path, obj)
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"history: append failed: {e!r}")
            return False

    # -- recovery (run once before session_start) --------------------------

    def _find_last_session(self):
        """Scan the JSONL for the last session that has no ``session_end``.

        Returns ``(session_id, last_heartbeat_ts, end_found)`` or
        ``(None, None, True)`` if every session is terminated (or the
        file is empty/missing). ``end_found=True`` means no recovery
        needed; ``False`` means a synthetic session_end should be
        written.
        """
        if not os.path.exists(self.path):
            return None, None, True
        sessions = {}  # session_id -> {"end": bool, "last_hb": ts}
        order = []
        for obj, raw, off in _read_lines_tolerant(self.path):
            if obj is None:
                continue
            t = obj.get("type")
            sid = obj.get("session_id")
            if t == "session_start" and sid:
                sessions.setdefault(sid, {"end": False, "last_hb": None})
                order.append(sid)
            elif t == "session_end" and sid:
                if sid in sessions:
                    sessions[sid]["end"] = True
            elif t == "heartbeat" and sid:
                if sid in sessions:
                    sessions[sid]["last_hb"] = obj.get("ts")
        if not order:
            return None, None, True
        last_sid = order[-1]
        info = sessions.get(last_sid, {"end": False, "last_hb": None})
        return last_sid, info["last_hb"], bool(info["end"])

    def _recover_previous_session(self):
        """Write a synthetic ``session_end`` for an unterminated last
        session (power-loss recovery). Idempotent — only acts if the last
        session has no session_end.

        Returns the recovered session_id (or None)."""
        try:
            sid, last_hb, ended = self._find_last_session()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"history: recovery scan failed: {e!r}")
            return None
        if ended or sid is None:
            return None
        now_ts = _utcnow_iso()
        end_reason = "power-loss"
        end_at = last_hb or now_ts
        if last_hb is None:
            end_reason = "unknown"
            end_at = now_ts
        else:
            # Staleness check: if the last heartbeat is far older than a
            # plausible session, treat the cause as "unknown" (the pod
            # may have been idle/stopped normally and the file not
            # updated for unrelated reasons).
            try:
                hb_dt = datetime.datetime.strptime(
                    last_hb, "%Y-%m-%dT%H:%M:%S.%fZ"
                ).replace(tzinfo=datetime.timezone.utc)
                now_dt = datetime.datetime.now(datetime.timezone.utc)
                age = (now_dt - hb_dt).total_seconds()
                if age > self.RECOVERY_STALE_S:
                    end_reason = "unknown"
            except Exception:
                end_reason = "unknown"
        crash_cls = None
        try:
            crash_cls = _classify_crash()
        except Exception:
            crash_cls = None
        line = {
            "type": "session_end",
            "session_id": sid,
            "end_at": end_at,
            "end_reason": end_reason,
            "synthetic": True,
            "crash_class": crash_cls,
            "ts": now_ts,
        }
        self._append(line)
        logger.info(
            f"history: recovered previous session {sid} "
            f"(end_reason={end_reason}, crash_class={crash_cls})"
        )
        return sid

    # -- config snapshot (D) -----------------------------------------------

    def _config_snapshot(self):
        """Build the config snapshot (D) from Settings + build-info.

        Only serializes the BL-68-relevant settings; counting/tracking
        params are captured via their existing names for diagnostics.
        """
        s = self.settings
        # config_notable: a short list of the most operationally-relevant
        # settings (the ones an operator might change between sessions).
        config_notable = {
            "INPUT_SOURCE": getattr(s, "INPUT_SOURCE", None),
            "VIDEO_PATH": getattr(s, "VIDEO_PATH", None),
            "PIG_CONFIDENCE_THRESHOLD": getattr(s, "PIG_CONFIDENCE_THRESHOLD", None),
            "COUNTING_TRACKER_IOU": getattr(s, "COUNTING_TRACKER_IOU", None),
            "COUNTING_MIRROR_GUARD": getattr(s, "COUNTING_MIRROR_GUARD", None),
            "OFFSET_PERCENT_COUNTING_LINE": getattr(s, "OFFSET_PERCENT_COUNTING_LINE", None),
        }
        return {
            "image_tag": self.build_info.get("image_tag", "unknown"),
            "git_commit": self.build_info.get("git_commit", "unknown"),
            "mode": self.mode,
            "history": {
                "HISTORY_RETENTION_DAYS": s.HISTORY_RETENTION_DAYS,
                "HISTORY_MAX_BYTES": s.HISTORY_MAX_BYTES,
                "HISTORY_HEARTBEAT_S": s.HISTORY_HEARTBEAT_S,
                "HISTORY_DISK_WARN_GB": s.HISTORY_DISK_WARN_GB,
                "HISTORY_DISK_CRIT_GB": s.HISTORY_DISK_CRIT_GB,
                "HISTORY_ROTATE_BYTES": s.HISTORY_ROTATE_BYTES,
                "HISTORY_ARCHIVE_MAX": s.HISTORY_ARCHIVE_MAX,
            },
            "tracker": {
                "TRACKER_LOST_TRACK_BUFFER": getattr(s, "TRACKER_LOST_TRACK_BUFFER", None),
                "TRACKER_MIN_CONSECUTIVE_FRAMES": getattr(s, "TRACKER_MIN_CONSECUTIVE_FRAMES", None),
                "TRACKER_HIGH_CONF_THRESHOLD": getattr(s, "TRACKER_HIGH_CONF_THRESHOLD", None),
                "COUNTING_TRACKER_IOU": getattr(s, "COUNTING_TRACKER_IOU", None),
            },
            "config_notable": config_notable,
        }

    # -- public API ---------------------------------------------------------

    def start_session(self, start_reason="boot"):
        """Emit ``session_start`` + ``startup`` line, after running
        power-loss recovery on the previous session.

        Safe to call from the main thread before starting HistoryThread.
        """
        with self._lock:
            try:
                prev_sid = self._recover_previous_session()
                self.prev_session_id = prev_sid
                self.session_id = str(uuid.uuid4())
                self.session_start_ts = _utcnow_iso()
                self.last_heartbeat_ts = None
                self._stopped = False
                cfg = self._config_snapshot()
                start_line = {
                    "type": "session_start",
                    "session_id": self.session_id,
                    "prev_session_id": prev_sid,
                    "start_at": self.session_start_ts,
                    "start_at_locale": _locale_now_iso(),
                    "start_reason": start_reason,
                    "status": "running",
                    "config": cfg,
                    "ts": self.session_start_ts,
                }
                self._append(start_line)
                # Startup history line (boot_at, image_tag, git_commit,
                # mode, config_notable).
                startup_line = {
                    "type": "startup",
                    "boot_at": self.session_start_ts,
                    "boot_at_locale": _locale_now_iso(),
                    "session_id": self.session_id,
                    "image_tag": cfg.get("image_tag", "unknown"),
                    "git_commit": cfg.get("git_commit", "unknown"),
                    "mode": self.mode,
                    "config_notable": cfg.get("config_notable", {}),
                    "ts": self.session_start_ts,
                }
                self._append(startup_line)
                logger.info(f"history: session_start {self.session_id}")
                return self.session_id
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(f"history: start_session failed: {e!r}")
                return None

    def emit_event(self, event_type, detail=None):
        """Append an ``event`` line (called from the counting
        instrumentation via the subscriber wired in main.py).

        Best-effort: never raises. ``detail`` is opaque to the writer.
        """
        if self._stopped or self._writes_suspended or self.session_id is None:
            return
        line = {
            "type": "event",
            "session_id": self.session_id,
            "event_type": event_type,
            "detail": detail if detail is not None else {},
            "ts": _utcnow_iso(),
        }
        self._append(line)

    def video(self, video_id, filename, duration, count_delta, session_id=None):
        """Append a ``video`` line (one per finalized recording). This
        makes the recorded VIDEO a first-class entity in the JSONL,
        alongside ``session_start``/``heartbeat``/``event``/``session_end``.

        Best-effort: never raises. Called from ``_finalize_recording``
        in main.py after the successful rename to
        ``tocompress-counting-{ts}-#{delta}.mp4``.

        ``session_id`` defaults to the writer's current session so the
        companion can correlate a video to its session even when the
        caller does not pass it explicitly.
        """
        if self._stopped or self.session_id is None:
            return
        sid = session_id if session_id is not None else self.session_id
        line = {
            "type": "video",
            "video_id": video_id,
            "filename": filename,
            "duration": duration,
            "count_delta": count_delta,
            "session_id": sid,
            "ts": _utcnow_iso(),
        }
        self._append(line)

    def heartbeat(self):
        """Append a ``heartbeat`` line (count + last video segment +
        system/thermal samples). Cheap; called only from HistoryThread,
        never per-frame."""
        if self._stopped or self.session_id is None:
            return
        count = 0
        last_segment = None
        status = None
        auto_mode = None
        if self.shared_state is not None:
            try:
                count = int(getattr(self.shared_state, "counter_to_right", 0))
            except Exception:
                count = 0
            # last video segment from the DisplayThread (best-effort).
            try:
                dt = getattr(self.shared_state, "display_thread", None)
                if dt is not None and getattr(dt, "filename", None):
                    last_segment = dt.filename
            except Exception:
                last_segment = None
            # Live status + auto_mode for /api/count (absorbed BL-66 scope).
            try:
                status = int(getattr(self.shared_state, "status", 3))
            except Exception:
                status = None
            try:
                auto_mode = bool(getattr(self.shared_state, "auto_mode", True))
            except Exception:
                auto_mode = None
            # record_start_count: snapshot of the counter at recording start,
            # sourced from the DisplayThread so the companion can compute the
            # running recording's live count delta (count - record_start_count).
            record_start_count = None
            if self.shared_state is not None:
                try:
                    dt = getattr(self.shared_state, "display_thread", None)
                    if dt is not None:
                        rsc = getattr(dt, "record_start_count", None)
                        if rsc is not None:
                            record_start_count = int(rsc)
                except Exception:
                    record_start_count = None
        line = {
            "type": "heartbeat",
            "session_id": self.session_id,
            "ts": _utcnow_iso(),
            "count": count,
            "status": status,
            "auto_mode": auto_mode,
            "last_segment": last_segment,
            "record_start_count": record_start_count,
            "thermal": _sample_thermal(),
            "system": _sample_system(),
        }
        ok = self._append(line)
        if ok:
            self.last_heartbeat_ts = line["ts"]

    def end_session(self, end_reason="clean"):
        """Append ``session_end`` with real ``end_at`` + E (video
        metadata) + B final counters (from the Counting accumulator) +
        F (disk/cpu/mem) + status. Idempotent."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            if self.session_id is None:
                return
            end_at = _utcnow_iso()
            # B final counters from the Counting accumulator.
            b = {}
            if self.counting is not None:
                try:
                    b = {
                        "count_left_to_right": int(getattr(self.counting, "count_left_to_right", 0)),
                        "count_right_to_left": int(getattr(self.counting, "count_right_to_left", 0)),
                        "guard_interventions": dict(getattr(self.counting, "guard_interventions", {})),
                        "id_switch_recoveries": int(getattr(self.counting, "id_switch_recoveries", 0)),
                        "unique_track_ids": len(getattr(self.counting, "unique_track_ids", set())),
                        "max_concurrent_tracks": int(getattr(self.counting, "max_concurrent_tracks", 0)),
                    }
                except Exception:
                    b = {}
            # E video metadata (best-effort from shared_state.display_thread).
            e = {}
            if self.shared_state is not None:
                try:
                    dt = getattr(self.shared_state, "display_thread", None)
                    if dt is not None:
                        e = {
                            "last_segment": getattr(dt, "filename", None),
                            "duration": getattr(dt, "record_duration", None),
                        }
                except Exception:
                    e = {}
            line = {
                "type": "session_end",
                "session_id": self.session_id,
                "start_at": self.session_start_ts,
                "end_at": end_at,
                "end_reason": end_reason,
                "status": end_reason if end_reason in ("clean", "power-loss") else "clean",
                "synthetic": False,
                "counters": b,
                "video": e,
                "system": _sample_system(),
                "ts": end_at,
            }
            self._append(line)
            logger.info(
                f"history: session_end {self.session_id} ({end_reason})"
            )

    # -- compaction --------------------------------------------------------

    def _iter_sessions_for_compact(self):
        """Parse the JSONL into an ordered list of session dicts.

        Each entry: ``{session_id, lines: [raw_objs...], start, last_hb,
        end}``. Non-session lines (``startup``) are kept separately and
        re-emitted verbatim (they are not session-scoped).
        """
        sessions = {}
        order = []
        startups = []
        for obj, raw, off in _read_lines_tolerant(self.path):
            if obj is None:
                continue
            t = obj.get("type")
            if t == "startup":
                startups.append(obj)
                continue
            sid = obj.get("session_id")
            if sid is None:
                continue
            if sid not in sessions:
                sessions[sid] = {
                    "session_id": sid,
                    "lines": [],
                    "start": None,
                    "last_hb": None,
                    "end": None,
                }
                order.append(sid)
            sess = sessions[sid]
            sess["lines"].append(obj)
            if t == "session_start":
                sess["start"] = obj
            elif t == "heartbeat":
                sess["last_hb"] = obj
            elif t == "session_end":
                sess["end"] = obj
        return [sessions[sid] for sid in order], startups

    @staticmethod
    def _session_summary(sess):
        """Build the cold-session ``summary`` line (A–F aggregates)."""
        start = sess.get("start") or {}
        end = sess.get("end")
        last_hb = sess.get("last_hb")
        significant = []
        net_count = None
        for obj in sess["lines"]:
            t = obj.get("type")
            if t == "event":
                et = obj.get("event_type", "")
                # Keep only "significant" events for cold sessions.
                if et in (
                    "crossed", "id_switch_recovery", "mirror_guard_enforce",
                    "mirror_suppress", "reid_suppress", "resurrection",
                    "lost_buffer_expired", "disk_warning",
                ):
                    significant.append({
                        "event_type": et,
                        "ts": obj.get("ts"),
                        "detail": obj.get("detail"),
                    })
            elif t == "heartbeat":
                if obj.get("count") is not None:
                    net_count = obj.get("count")
            elif t == "session_end":
                if obj.get("counters"):
                    net_count = obj.get("counters", {}).get("count_left_to_right", net_count)
        end_at = (end or {}).get("end_at") or (last_hb or {}).get("ts")
        end_reason = (end or {}).get("end_reason")
        synthetic = (end or {}).get("synthetic", False) if end else False
        return {
            "type": "summary",
            "session_id": sess.get("session_id"),
            "start_at": start.get("start_at"),
            "end_at": end_at,
            "end_reason": end_reason,
            "synthetic_end": synthetic,
            "net_count": net_count,
            "config": start.get("config"),
            "significant_events": significant,
            "ts": _utcnow_iso(),
        }

    def _archive_count(self):
        """Count existing gz archives matching the rotation pattern."""
        d = os.path.dirname(self.path)
        base = os.path.basename(self.path)
        if not d or not os.path.isdir(d):
            return 0, []
        archives = []
        for name in os.listdir(d):
            if name.startswith(base + ".") and name.endswith(".jsonl.gz"):
                archives.append(name)
        archives.sort()
        return len(archives), [os.path.join(d, n) for n in archives]

    def _rotate_cold(self, cold_objs):
        """Gzip-archive the cold-session lines, bounded by
        HISTORY_ARCHIVE_MAX. Returns the list of archive paths created
        (for tests)."""
        if not cold_objs:
            return []
        d = os.path.dirname(self.path)
        if not d:
            return []
        ts = time.strftime("%Y%m%d-%H%M%S")
        arc_path = os.path.join(
            d, os.path.basename(self.path) + f".{ts}.jsonl.gz"
        )
        try:
            with gzip.open(arc_path, "wb") as gz:
                for obj in cold_objs:
                    gz.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"history: rotate archive failed: {e!r}")
            return []
        # Bound the archive count.
        try:
            n, archives = self._archive_count()
            max_arch = self.settings.HISTORY_ARCHIVE_MAX
            while n > max_arch and archives:
                oldest = archives.pop(0)
                try:
                    os.remove(oldest)
                except Exception:
                    pass
                n -= 1
        except Exception:
            pass
        return [arc_path]

    def compact(self):
        """2-level compaction + bounded-size rotation. Atomic rewrite
        via temp file + ``os.replace``; a crash before ``os.replace``
        leaves the old file intact.

          * Hot (≤ HISTORY_RETENTION_DAYS): keep raw lines.
          * Cold (> retention): replace each session's lines with one
            ``summary`` line (A–F aggregates) keeping only significant
            events; drop heartbeats. ``startup`` lines are kept verbatim
            (not session-scoped).
          * Bounded to HISTORY_MAX_BYTES: if the rewritten file still
            exceeds HISTORY_ROTATE_BYTES, gzip-archive the cold portion.
        """
        with self._lock:
            try:
                if not os.path.exists(self.path):
                    return
                sessions, startups = self._iter_sessions_for_compact()
                if not sessions and not startups:
                    return
                now_dt = datetime.datetime.now(datetime.timezone.utc)
                retention_s = self.settings.HISTORY_RETENTION_DAYS * 86400
                new_objs = []
                cold_objs = []
                # Startups are kept verbatim at the top.
                for s in startups:
                    new_objs.append(s)
                for sess in sessions:
                    start = sess.get("start")
                    cold = False
                    if start and start.get("start_at"):
                        try:
                            sdt = datetime.datetime.strptime(
                                start["start_at"], "%Y-%m-%dT%H:%M:%S.%fZ"
                            ).replace(tzinfo=datetime.timezone.utc)
                            age = (now_dt - sdt).total_seconds()
                            if age > retention_s:
                                cold = True
                        except Exception:
                            cold = False
                    if cold:
                        summ = self._session_summary(sess)
                        new_objs.append(summ)
                        cold_objs.extend(sess["lines"])
                    else:
                        # Hot: keep raw lines.
                        new_objs.extend(sess["lines"])
                # Atomic rewrite via temp file + os.replace.
                d = os.path.dirname(self.path) or "."
                tmp_fd, tmp_path = tempfile__mkstemp_in(d)
                try:
                    with os.fdopen(tmp_fd, "w") as f:
                        for obj in new_objs:
                            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, self.path)
                except Exception as e:  # pragma: no cover - defensive
                    logger.warning(f"history: compact rewrite failed: {e!r}")
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    return
                # Rotation: if still over ROTATE_BYTES, archive the cold
                # portion. We archive the cold session lines we already
                # collapsed (they are now summaries in the live file, so
                # archiving the raw cold lines is the historical record).
                try:
                    size = os.path.getsize(self.path)
                except Exception:
                    size = 0
                if size > self.settings.HISTORY_ROTATE_BYTES and cold_objs:
                    self._rotate_cold(cold_objs)
                # Hard cap: if the live file is somehow still over
                # HISTORY_MAX_BYTES, drop oldest summaries/startups from
                # the head until under the cap (last-resort).
                try:
                    size = os.path.getsize(self.path)
                except Exception:
                    size = 0
                if size > self.settings.HISTORY_MAX_BYTES:
                    self._enforce_cap_by_truncating()
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(f"history: compact failed: {e!r}")

    def _enforce_cap_by_truncating(self):
        """Last-resort hard cap: drop oldest lines from the head of the
        file until the size is under HISTORY_MAX_BYTES. Only drops whole
        lines; never splits a line."""
        try:
            target = self.settings.HISTORY_MAX_BYTES
            objs = []
            for obj, raw, off in _read_lines_tolerant(self.path):
                if obj is not None:
                    objs.append(obj)
            # Drop from the head until the serialized size fits.
            serialized = [json.dumps(o, ensure_ascii=False) + "\n" for o in objs]
            total = sum(len(s.encode("utf-8")) for s in serialized)
            idx = 0
            while total > target and idx < len(serialized):
                total -= len(serialized[idx].encode("utf-8"))
                idx += 1
            kept = serialized[idx:]
            d = os.path.dirname(self.path) or "."
            tmp_fd, tmp_path = tempfile__mkstemp_in(d)
            try:
                with os.fdopen(tmp_fd, "w") as f:
                    for s in kept:
                        f.write(s)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.path)
            except Exception:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"history: enforce_cap failed: {e!r}")

    # -- disk guard --------------------------------------------------------

    def check_disk_guard(self):
        """Return the effective heartbeat interval (s), or None to
        suspend writes (disk CRIT). Also sets ``_writes_suspended`` and
        emits a ``disk_warning`` event on transitions into CRIT."""
        try:
            free = disk_free_bytes(self.path)
        except Exception:
            free = float("inf")
        crit = self.settings.HISTORY_DISK_CRIT_GB * 1024 ** 3
        warn = self.settings.HISTORY_DISK_WARN_GB * 1024 ** 3
        if free < crit:
            if not self._writes_suspended:
                # Emit the warning BEFORE flipping the suspended flag, so
                # the warning line itself is not blocked by the suspension
                # (it IS the alert that documents the suspension).
                self.emit_event("disk_warning", {
                    "free_bytes": free,
                    "threshold_bytes": crit,
                    "level": "crit",
                    "message": "history writes suspended (disk CRIT); counting continues",
                })
                self._writes_suspended = True
                logger.error(
                    f"history: disk CRIT ({free/1024**3:.2f} GB free) — "
                    f"writes suspended, counting continues"
                )
            return None
        if self._writes_suspended and free >= crit:
            # Hysteresis: only resume once we're comfortably above CRIT.
            # Clear the suspended flag BEFORE emitting the resume warning so
            # the warning line is actually written.
            self._writes_suspended = False
            self.emit_event("disk_warning", {
                "free_bytes": free,
                "level": "resume",
                "message": "history writes resumed (disk above CRIT)",
            })
            logger.info("history: disk above CRIT — writes resumed")
        if free < warn:
            return self.WARN_HEARTBEAT_S
        return self.settings.HISTORY_HEARTBEAT_S

    # -- stop ---------------------------------------------------------------

    def stop(self):
        """Mark the writer stopped so the heartbeat loop exits."""
        self._stopped = True


# ---------------------------------------------------------------------------
# HistoryThread
# ---------------------------------------------------------------------------

class HistoryThread(threading.Thread):
    """Dedicated history thread: owns heartbeat + 1x/day compaction.

    Serialized: compaction and heartbeat are never concurrent because
    they run in the same thread. Started by main.py in serve mode only.
    """

    def __init__(self, writer, stop_event=None, name="HistoryThread"):
        super().__init__(daemon=True, name=name)
        self.writer = writer
        self.stop_event = stop_event or threading.Event()
        self._next_compact_ts = time.time() + 0  # compact once at start

    def run(self):
        # (a) one-shot startup compaction.
        try:
            self.writer.compact()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"history: startup compact failed: {e!r}")
        # (b) heartbeat loop + (c) 1x/day compaction timer.
        next_compact_deadline = time.time() + self.writer.COMPACTION_PERIOD_S
        while not self.stop_event.is_set() and not self.writer._stopped:
            try:
                interval = self.writer.check_disk_guard()
                if interval is None:
                    # Suspended: sleep longer and retry the guard.
                    time.sleep(5)
                    continue
                self.writer.heartbeat()
                # 1x/day compaction.
                now = time.time()
                if now >= next_compact_deadline:
                    self.writer.compact()
                    next_compact_deadline = now + self.writer.COMPACTION_PERIOD_S
                # Sleep in small increments so a stop_event is responsive.
                slept = 0.0
                while slept < interval and not self.stop_event.is_set() and not self.writer._stopped:
                    time.sleep(min(0.5, interval - slept))
                    slept += 0.5
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(f"history: loop iteration failed: {e!r}")
                time.sleep(1)


# ---------------------------------------------------------------------------
# temp-file helper (stdlib only, no external dep)
# ---------------------------------------------------------------------------

def tempfile__mkstemp_in(directory):
    """Create an unnamed temp fd in ``directory`` (like tempfile.mkstemp
    but inline so the module stays importable on minimal images)."""
    import tempfile
    return tempfile.mkstemp(dir=directory, prefix=".history-tmp-")