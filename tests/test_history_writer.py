"""
BL-68 unit tests for ``core.history.HistoryWriter`` (stdlib only).

These tests exercise the JSONL writer in isolation on a temp dir:

  * append + fsync (lines land on disk, one JSON object per line)
  * partial-line tolerance on reopen (a truncated trailing line is
    skipped, not fatal)
  * recovery writes a synthetic ``session_end`` for an unterminated last
    session, classifying ``power-loss`` (recent heartbeat) vs ``unknown``
    (stale heartbeat beyond RECOVERY_STALE_S)
  * compaction drops heartbeats for cold sessions and replaces them
    with a single ``summary`` line (hot sessions kept raw)
  * bounded size: the live JSONL is ≤ ``HISTORY_MAX_BYTES`` after
    compaction (last-resort head truncation enforces the cap)
  * rotation creates a gz archive of the cold portion and bounds the
    archive count (oldest deleted beyond ``HISTORY_ARCHIVE_MAX``)
  * disk guard suspends writes below ``HISTORY_DISK_CRIT_GB`` (counting
    continues; heartbeat/emit_event become no-ops)

History is best-effort and must never break counting, so every path is
also checked to be non-raising.
"""

import gzip
import json
import os
import tempfile
import time

import pytest

import core.history as history_mod
from core.history import HistoryWriter


# ---------------------------------------------------------------------------
# Minimal fake Settings (stdlib only — avoids depending on python-dotenv).
# ---------------------------------------------------------------------------

class FakeSettings:
    """A minimal settings stub exposing only the HISTORY_* attributes the
    writer reads, plus a few config_notable fields with sensible defaults."""

    def __init__(self, **overrides):
        self.INPUT_SOURCE = "CAMERA"
        self.VIDEO_PATH = "/dev/video0"
        self.PIG_CONFIDENCE_THRESHOLD = 0.5
        self.COUNTING_TRACKER_IOU = 0.45
        self.COUNTING_MIRROR_GUARD = "log"
        self.OFFSET_PERCENT_COUNTING_LINE = 10
        self.TRACKER_LOST_TRACK_BUFFER = 30
        self.TRACKER_MIN_CONSECUTIVE_FRAMES = 3
        self.TRACKER_HIGH_CONF_THRESHOLD = 0.7

        self.HISTORY_RETENTION_DAYS = 30
        self.HISTORY_MAX_BYTES = 200 * 1024 * 1024
        self.HISTORY_HEARTBEAT_S = 5
        self.HISTORY_DISK_WARN_GB = 2
        self.HISTORY_DISK_CRIT_GB = 0.5
        self.HISTORY_ROTATE_BYTES = 10 * 1024 * 1024
        self.HISTORY_ARCHIVE_MAX = 20
        for k, v in overrides.items():
            setattr(self, k, v)


def _read_jsonl(path):
    """Read a JSONL file and return the list of parsed objects (skipping
    trailing partial lines, like the writer's tolerant reader)."""
    objs = []
    if not os.path.exists(path):
        return objs
    with open(path, "r") as f:
        for raw in f:
            raw = raw.rstrip("\n")
            if not raw.strip():
                continue
            try:
                objs.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return objs


def _utc_iso(dt):
    """Format a datetime (UTC) the same way the writer does."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@pytest.fixture
def tmp_jsonl(tmp_path):
    return str(tmp_path / "counting-history.jsonl")


# ---------------------------------------------------------------------------
# append + fsync
# ---------------------------------------------------------------------------

def test_append_persists_lines_and_is_one_object_per_line(tmp_jsonl):
    """start_session must fsync'd-append a session_start + startup line,
    each a single JSON object on its own line."""
    w = HistoryWriter(tmp_jsonl, FakeSettings(), mode="serve")
    sid = w.start_session(start_reason="boot")
    assert sid is not None
    objs = _read_jsonl(tmp_jsonl)
    types = [o["type"] for o in objs]
    # session_start then startup.
    assert types[0] == "session_start"
    assert types[1] == "startup"
    assert objs[0]["session_id"] == sid
    assert objs[0]["start_reason"] == "boot"
    assert objs[0]["status"] == "running"
    # startup line carries build-info + config_notable.
    assert objs[1]["image_tag"] == "unknown"
    assert objs[1]["git_commit"] == "unknown"
    assert objs[1]["mode"] == "serve"
    # Each line is exactly one JSON object (no mid-line concatenation).
    with open(tmp_jsonl, "rb") as f:
        raw = f.read()
    assert raw.count(b"\n") == len(objs)


def test_emit_event_appends_event_line(tmp_jsonl):
    w = HistoryWriter(tmp_jsonl, FakeSettings(), mode="serve")
    w.start_session()
    w.emit_event("crossed", {"direction": "LEFT", "track_id": 7, "count": 1})
    objs = _read_jsonl(tmp_jsonl)
    ev = [o for o in objs if o["type"] == "event"]
    assert len(ev) == 1
    assert ev[0]["event_type"] == "crossed"
    assert ev[0]["detail"]["direction"] == "LEFT"


def test_heartbeat_appends_count_and_segment(tmp_jsonl):
    class FakeDisplay:
        filename = "/files/seg_0001.mp4"

    class FakeShared:
        counter_to_right = 9
        display_thread = FakeDisplay()

    w = HistoryWriter(tmp_jsonl, FakeSettings(), shared_state=FakeShared(),
                      mode="serve")
    w.start_session()
    w.heartbeat()
    objs = _read_jsonl(tmp_jsonl)
    hb = [o for o in objs if o["type"] == "heartbeat"]
    assert len(hb) == 1
    assert hb[0]["count"] == 9
    assert hb[0]["last_segment"] == "/files/seg_0001.mp4"
    assert "thermal" in hb[0]
    assert "system" in hb[0]


def test_heartbeat_includes_live_status_and_auto_mode(tmp_jsonl):
    """The heartbeat carries status + auto_mode from SharedState for /api/count
    (absorbed BL-66 scope)."""
    class FakeDisplay:
        filename = "/files/seg_0001.mp4"

    class FakeShared:
        counter_to_right = 12
        display_thread = FakeDisplay()
        status = 3
        auto_mode = False

    w = HistoryWriter(tmp_jsonl, FakeSettings(), shared_state=FakeShared(),
                      mode="serve")
    w.start_session()
    w.heartbeat()
    hb = [o for o in _read_jsonl(tmp_jsonl) if o["type"] == "heartbeat"][0]
    assert hb["count"] == 12
    assert hb["status"] == 3
    assert hb["auto_mode"] is False


def test_heartbeat_status_auto_mode_default_when_shared_state_absent(tmp_jsonl):
    """Without a shared_state, status + auto_mode are None (graceful)."""
    w = HistoryWriter(tmp_jsonl, FakeSettings(), shared_state=None,
                      mode="serve")
    w.start_session()
    w.heartbeat()
    hb = [o for o in _read_jsonl(tmp_jsonl) if o["type"] == "heartbeat"][0]
    assert hb["status"] is None
    assert hb["auto_mode"] is None


# ---------------------------------------------------------------------------
# partial-line tolerance on reopen
# ---------------------------------------------------------------------------

def test_partial_trailing_line_is_tolerated_on_reopen(tmp_jsonl):
    """A power-cut-truncated last line must not corrupt recovery or block
    future appends: the tolerant reader skips it and the writer appends
    after it."""
    # Seed a valid session_start + a truncated (partial) last line.
    with open(tmp_jsonl, "w") as f:
        f.write(json.dumps({
            "type": "session_start",
            "session_id": "old-session",
            "start_at": _utc_iso_from_now(hours=2),
            "start_reason": "boot",
            "status": "running",
            "ts": _utc_iso_from_now(hours=2),
        }) + "\n")
        # A truncated (power-cut) line, newline-terminated so the next
        # append does not concatenate onto it. The tolerant reader must
        # skip it because it fails json.loads.
        f.write('{"type":"heartbeat","session_id":"old-session",')  # truncated
        f.write("\n")

    w = HistoryWriter(tmp_jsonl, FakeSettings(), mode="serve")
    # Recovery: the old session has no session_end, so a synthetic one is
    # written. The partial line must not raise.
    sid = w.start_session(start_reason="boot")
    assert sid is not None
    objs = _read_jsonl(tmp_jsonl)
    types = [o["type"] for o in objs]
    # recovery session_end for the old session, then a new session_start.
    assert "session_end" in types
    end = [o for o in objs if o["type"] == "session_end"][0]
    assert end["session_id"] == "old-session"
    assert end.get("synthetic") is True
    # New session started.
    assert types[-2] == "session_start"
    assert types[-1] == "startup"


def _utc_iso_from_now(hours=0, minutes=0, seconds=0):
    """UTC ISO timestamp this far in the PAST (positive = ago)."""
    import datetime as _dt
    return _utc_iso(
        _dt.datetime.now(_dt.timezone.utc)
        - _dt.timedelta(hours=hours, minutes=minutes, seconds=seconds)
    )


# ---------------------------------------------------------------------------
# recovery: synthetic session_end for an unterminated last session
# ---------------------------------------------------------------------------

def _seed_unterminated_session(path, session_id, hb_ts, with_heartbeat=True):
    """Write a session_start and (optionally) one heartbeat, no end."""
    with open(path, "w") as f:
        f.write(json.dumps({
            "type": "session_start",
            "session_id": session_id,
            "start_at": hb_ts,
            "start_reason": "boot",
            "status": "running",
            "ts": hb_ts,
        }) + "\n")
        if with_heartbeat:
            f.write(json.dumps({
                "type": "heartbeat",
                "session_id": session_id,
                "ts": hb_ts,
                "count": 3,
            }) + "\n")


def test_recovery_writes_power_loss_for_recent_heartbeat(tmp_jsonl):
    sid = "sess-recent"
    # A heartbeat 1 minute ago — well within RECOVERY_STALE_S (1h).
    recent = _utc_iso_from_now(minutes=1)
    _seed_unterminated_session(tmp_jsonl, sid, recent, with_heartbeat=True)

    w = HistoryWriter(tmp_jsonl, FakeSettings(), mode="serve")
    w.start_session(start_reason="boot")
    objs = _read_jsonl(tmp_jsonl)
    ends = [o for o in objs if o["type"] == "session_end" and o["session_id"] == sid]
    assert len(ends) == 1
    assert ends[0].get("synthetic") is True
    assert ends[0]["end_reason"] == "power-loss"
    # end_at is the last heartbeat ts.
    assert ends[0]["end_at"] == recent


def test_recovery_writes_unknown_for_stale_heartbeat(tmp_jsonl):
    sid = "sess-stale"
    # A heartbeat 2 hours ago — beyond RECOVERY_STALE_S (1h) -> unknown.
    stale = _utc_iso_from_now(hours=2)
    _seed_unterminated_session(tmp_jsonl, sid, stale, with_heartbeat=True)

    w = HistoryWriter(tmp_jsonl, FakeSettings(), mode="serve")
    w.start_session(start_reason="boot")
    objs = _read_jsonl(tmp_jsonl)
    ends = [o for o in objs if o["type"] == "session_end" and o["session_id"] == sid]
    assert len(ends) == 1
    assert ends[0].get("synthetic") is True
    assert ends[0]["end_reason"] == "unknown"


def test_recovery_noop_when_last_session_already_ended(tmp_jsonl):
    sid = "sess-clean"
    ts = _utc_iso_from_now(minutes=1)
    _seed_unterminated_session(tmp_jsonl, sid, ts, with_heartbeat=True)
    # Append a clean session_end so the session is terminated.
    with open(tmp_jsonl, "a") as f:
        f.write(json.dumps({
            "type": "session_end",
            "session_id": sid,
            "end_at": _utc_iso_from_now(minutes=1),
            "end_reason": "clean",
            "synthetic": False,
            "ts": _utc_iso_from_now(minutes=1),
        }) + "\n")

    w = HistoryWriter(tmp_jsonl, FakeSettings(), mode="serve")
    w.start_session(start_reason="boot")
    objs = _read_jsonl(tmp_jsonl)
    ends = [o for o in objs if o["type"] == "session_end" and o["session_id"] == sid]
    # Exactly one session_end for sid (the clean one we wrote) — no extra
    # synthetic end.
    assert len(ends) == 1
    assert ends[0].get("synthetic") is False


# ---------------------------------------------------------------------------
# compaction: cold sessions collapse to one summary, heartbeats dropped
# ---------------------------------------------------------------------------

def _seed_session(path, session_id, start_hours_ago, n_heartbeats=3,
                  events=None, ended=True, net_count=4):
    """Write a full session (start, heartbeats, optional events, end)."""
    import datetime as _dt
    start_dt = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=start_hours_ago)
    start_ts = _utc_iso(start_dt)
    lines = []
    lines.append(json.dumps({
        "type": "session_start",
        "session_id": session_id,
        "start_at": start_ts,
        "start_reason": "boot",
        "status": "running",
        "ts": start_ts,
    }))
    for i in range(n_heartbeats):
        hb_dt = start_dt + _dt.timedelta(seconds=5 * (i + 1))
        lines.append(json.dumps({
            "type": "heartbeat",
            "session_id": session_id,
            "ts": _utc_iso(hb_dt),
            "count": i + 1,
        }))
    for ev in (events or []):
        ev_obj = {"type": "event", "session_id": session_id,
                  "event_type": ev["event_type"],
                  "detail": ev.get("detail", {}), "ts": _utc_iso(start_dt)}
        lines.append(json.dumps(ev_obj))
    if ended:
        end_dt = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=start_hours_ago - 1)
        lines.append(json.dumps({
            "type": "session_end",
            "session_id": session_id,
            "start_at": start_ts,
            "end_at": _utc_iso(end_dt),
            "end_reason": "clean",
            "synthetic": False,
            "counters": {"count_left_to_right": net_count,
                         "count_right_to_left": 0},
            "ts": _utc_iso(end_dt),
        }))
    with open(path, "a") as f:
        for ln in lines:
            f.write(ln + "\n")


def test_compaction_drops_heartbeats_for_cold_sessions(tmp_jsonl):
    # A cold session (> 30 days retention) + a hot session (recent).
    # Use a tiny retention so "cold" is easy to trigger without waiting.
    settings = FakeSettings(HISTORY_RETENTION_DAYS=1)
    # Cold: started 10 days ago.
    _seed_session(tmp_jsonl, "cold-1", start_hours_ago=10 * 24,
                  n_heartbeats=5, ended=True)
    # Hot: started 1 hour ago (< 1 day retention).
    _seed_session(tmp_jsonl, "hot-1", start_hours_ago=1, n_heartbeats=3,
                  ended=True)

    w = HistoryWriter(tmp_jsonl, settings, mode="serve")
    w.compact()
    objs = _read_jsonl(tmp_jsonl)

    cold_lines = [o for o in objs if o.get("session_id") == "cold-1"]
    hot_lines = [o for o in objs if o.get("session_id") == "hot-1"]

    # Cold session collapsed to a single summary line; no heartbeats.
    assert len(cold_lines) == 1
    assert cold_lines[0]["type"] == "summary"
    assert "significant_events" in cold_lines[0]
    # Net count is carried forward from the session_end counters.
    assert cold_lines[0]["net_count"] == 4

    # Hot session kept raw (start + heartbeats + end).
    hot_types = [o["type"] for o in hot_lines]
    assert "session_start" in hot_types
    assert "heartbeat" in hot_types
    assert "session_end" in hot_types


def test_compaction_keeps_significant_events_for_cold(tmp_jsonl):
    settings = FakeSettings(HISTORY_RETENTION_DAYS=1)
    _seed_session(
        tmp_jsonl, "cold-ev", start_hours_ago=10 * 24, n_heartbeats=4,
        events=[
            {"event_type": "crossed", "detail": {"direction": "LEFT"}},
            {"event_type": "mirror_guard_enforce", "detail": {"id": 1}},
            {"event_type": "ignored_type", "detail": {}},  # not significant
        ],
        ended=True,
    )
    w = HistoryWriter(tmp_jsonl, settings, mode="serve")
    w.compact()
    objs = _read_jsonl(tmp_jsonl)
    summ = [o for o in objs if o.get("type") == "summary"]
    assert len(summ) == 1
    sig_types = sorted(e["event_type"] for e in summ[0]["significant_events"])
    assert sig_types == ["crossed", "mirror_guard_enforce"]


# ---------------------------------------------------------------------------
# bounded size: live file ≤ HISTORY_MAX_BYTES after compaction
# ---------------------------------------------------------------------------

def test_bounded_size_after_compaction(tmp_path):
    path = str(tmp_path / "hist.jsonl")
    settings = FakeSettings(
        HISTORY_RETENTION_DAYS=1,
        HISTORY_MAX_BYTES=400,        # very small cap
        HISTORY_ROTATE_BYTES=10 * 1024 * 1024,  # don't rotate (test cap)
    )
    # Many cold sessions with lots of heartbeats → big raw file.
    for i in range(40):
        _seed_session(path, f"cold-{i}", start_hours_ago=10 * 24,
                      n_heartbeats=8, ended=True)
    raw_size = os.path.getsize(path)
    assert raw_size > 400  # the raw file exceeds the cap

    w = HistoryWriter(path, settings, mode="serve")
    w.compact()
    final_size = os.path.getsize(path)
    assert final_size <= settings.HISTORY_MAX_BYTES, (
        f"live file {final_size} exceeds cap {settings.HISTORY_MAX_BYTES}"
    )
    # The file must still be valid JSONL (every line parses).
    objs = _read_jsonl(path)
    assert len(objs) >= 1


# ---------------------------------------------------------------------------
# rotation: gz archive created + bounded count
# ---------------------------------------------------------------------------

def test_rotation_creates_gz_archive_and_bounds_count(tmp_path):
    path = str(tmp_path / "hist.jsonl")
    settings = FakeSettings(
        HISTORY_RETENTION_DAYS=1,
        HISTORY_ROTATE_BYTES=200,      # tiny: forces rotation after compact
        HISTORY_MAX_BYTES=10 * 1024 * 1024,  # cap not the limiter here
        HISTORY_ARCHIVE_MAX=2,
    )
    # Several cold sessions so the raw cold portion exceeds ROTATE_BYTES.
    for i in range(10):
        _seed_session(path, f"cold-{i}", start_hours_ago=10 * 24,
                      n_heartbeats=6, ended=True)

    w = HistoryWriter(path, settings, mode="serve")
    w.compact()

    # A gz archive should exist next to the live file.
    d = tmp_path
    archives = sorted(n for n in os.listdir(d)
                      if n.startswith("hist.jsonl.") and n.endswith(".jsonl.gz"))
    assert len(archives) >= 1, "no gz archive created on rotation"
    # The archive is valid gzip JSONL.
    with gzip.open(os.path.join(d, archives[0]), "rb") as gz:
        raw = gz.read().decode("utf-8")
    arc_objs = [json.loads(l) for l in raw.splitlines() if l.strip()]
    assert all("session_id" in o for o in arc_objs)

    # Bounded count: run rotation several more times to exceed ARCHIVE_MAX.
    # Re-seed + compact repeatedly to create multiple archives.
    for _ in range(4):
        # Re-append the same cold sessions so compact re-rotates.
        for i in range(10):
            _seed_session(path, f"cold-x{i}", start_hours_ago=10 * 24,
                          n_heartbeats=6, ended=True)
        # Force the live file to look hot-enough to retrigger rotation by
        # lowering ROTATE_BYTES is already tiny; just compact again.
        w.compact()
    archives = sorted(n for n in os.listdir(d)
                      if n.startswith("hist.jsonl.") and n.endswith(".jsonl.gz"))
    assert len(archives) <= settings.HISTORY_ARCHIVE_MAX, (
        f"archive count {len(archives)} exceeds max {settings.HISTORY_ARCHIVE_MAX}"
    )


# ---------------------------------------------------------------------------
# disk guard: writes suspended below CRIT threshold
# ---------------------------------------------------------------------------

def test_disk_guard_suspends_writes_below_crit(tmp_jsonl):
    # Force the disk-free check to report below CRIT (0.5 GB default).
    crit_bytes = 0.5 * 1024 ** 3
    orig = history_mod.disk_free_bytes
    history_mod.disk_free_bytes = lambda p: crit_bytes // 2  # below CRIT
    try:
        w = HistoryWriter(tmp_jsonl, FakeSettings(), mode="serve")
        w.start_session()
        # check_disk_guard must signal suspension (None interval) and set
        # the suspended flag + emit a disk_warning event.
        interval = w.check_disk_guard()
        assert interval is None
        assert w._writes_suspended is True

        before = _read_jsonl(tmp_jsonl)
        w.heartbeat()
        w.emit_event("crossed", {"direction": "LEFT"})
        after = _read_jsonl(tmp_jsonl)
        # No new lines were written while suspended.
        assert len(after) == len(before)
        # A disk_warning event was emitted before suspension took effect
        # (the emit_event inside check_disk_guard runs while not yet fully
        # suspended for that one line).
        warnings = [o for o in after if o.get("event_type") == "disk_warning"]
        assert len(warnings) >= 1
        assert warnings[-1]["detail"]["level"] == "crit"
    finally:
        history_mod.disk_free_bytes = orig


def test_disk_guard_warn_raises_interval_but_keeps_writing(tmp_jsonl):
    warn_bytes = 2 * 1024 ** 3
    history_mod.disk_free_bytes = lambda p: warn_bytes * 0.5  # below WARN, above CRIT
    orig_warn = None
    try:
        w = HistoryWriter(tmp_jsonl, FakeSettings(), mode="serve")
        w.start_session()
        interval = w.check_disk_guard()
        assert interval == HistoryWriter.WARN_HEARTBEAT_S
        assert w._writes_suspended is False
        # Writes still proceed (not suspended).
        before = len(_read_jsonl(tmp_jsonl))
        w.heartbeat()
        after = len(_read_jsonl(tmp_jsonl))
        assert after == before + 1
    finally:
        # restore is via re-import safety; reset explicitly.
        import importlib
        importlib.reload(history_mod)


def test_disk_guard_resumes_above_crit(tmp_jsonl):
    crit_bytes = 0.5 * 1024 ** 3
    free = {"v": crit_bytes // 2}
    history_mod.disk_free_bytes = lambda p: free["v"]
    try:
        w = HistoryWriter(tmp_jsonl, FakeSettings(), mode="serve")
        w.start_session()
        assert w.check_disk_guard() is None
        assert w._writes_suspended is True
        # Recover above CRIT.
        free["v"] = crit_bytes * 4
        interval = w.check_disk_guard()
        assert w._writes_suspended is False
        assert interval == FakeSettings().HISTORY_HEARTBEAT_S
    finally:
        import importlib
        importlib.reload(history_mod)


# ---------------------------------------------------------------------------
# end_session: idempotent + records counters
# ---------------------------------------------------------------------------

def test_end_session_writes_counters_and_is_idempotent(tmp_jsonl):
    class FakeCounting:
        count_left_to_right = 5
        count_right_to_left = 1
        guard_interventions = {"lost_buffer_expired": 0, "mirror_guard": 1,
                               "resurrection": 0, "reid_rebind": 0}
        id_switch_recoveries = 2
        unique_track_ids = {1, 2, 3}
        max_concurrent_tracks = 3

    w = HistoryWriter(tmp_jsonl, FakeSettings(), counting=FakeCounting(),
                      mode="serve")
    w.start_session()
    w.end_session("clean")
    objs = _read_jsonl(tmp_jsonl)
    ends = [o for o in objs if o["type"] == "session_end"]
    assert len(ends) == 1
    assert ends[0]["end_reason"] == "clean"
    assert ends[0]["counters"]["count_left_to_right"] == 5
    assert ends[0]["counters"]["count_right_to_left"] == 1
    assert ends[0]["counters"]["id_switch_recoveries"] == 2
    assert ends[0]["counters"]["unique_track_ids"] == 3
    assert ends[0]["counters"]["max_concurrent_tracks"] == 3

    # Idempotent: a second call writes nothing.
    w.end_session("clean")
    objs2 = _read_jsonl(tmp_jsonl)
    assert len(objs2) == len(objs)


# ---------------------------------------------------------------------------
# best-effort: writer never raises (history must not break counting)
# ---------------------------------------------------------------------------

def test_writer_survives_unwritable_path():
    # A path under a non-creatable location should not raise on start.
    bad = "/proc/cannot-create-here/hist.jsonl"
    w = HistoryWriter(bad, FakeSettings(), mode="serve")
    # start_session is best-effort: it must not raise (history must never
    # break counting). It returns a session_id (the uuid it generated) even
    # though the appends failed — the key contract is no exception + no
    # file created at the unwritable path.
    try:
        w.start_session()
    except Exception as e:  # pragma: no cover - defensive
        pytest.fail(f"start_session raised on unwritable path: {e!r}")
    assert not os.path.exists(bad)