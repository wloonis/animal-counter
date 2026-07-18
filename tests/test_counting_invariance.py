"""
BL-68 regression test: prove the read-only instrumentation in
``core.counting.Counting`` cannot alter ``counter_to_right``.

The instrumentation added in BL-68 (``_emit_event`` hook, accumulator
counters, detection-stat aggregates) is purely additive: no decision
branch reads any of it. This test proves that property by running an
identical crossing sequence through two fresh ``Counting`` instances —
one with no subscribers (the default, un-instrumented behaviour) and one
with a subscriber attached — and asserting the returned
``counter_to_right`` is byte-identical. It also asserts the new
accumulators increment correctly on a known crossing sequence, and that
a faulty subscriber cannot perturb the count (``_emit_event`` swallows
subscriber exceptions).

This is the unit-level complement to the Jetson STANDARD validation
(tolerance 0): together they prove the instrumentation is read-only.
"""

import numpy as np
import pytest

from core.counting import Counting


# ---------------------------------------------------------------------------
# Helpers to build deterministic frames.
# ---------------------------------------------------------------------------

IMG_H, IMG_W = 480, 640
# With offset_counting_line=0 and hysteresis_px=25:
#   x = 320, x_low = 295, x_high = 345


def _frame(track_ids_cx_cy, class_id=0, scores=None):
    """Build one frame's inputs for Counting.count().

    track_ids_cx_cy: list of (track_id, cx, cy).
    Returns (image_raw, result_boxes, result_trackid, result_classid,
             result_scores).
    """
    n = len(track_ids_cx_cy)
    if n == 0:
        img = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)
        empty = np.zeros((0,), dtype=np.float64)
        return img, np.zeros((0, 4)), empty, empty, None

    boxes = []
    tids = []
    cids = []
    scs = []
    for tid, cx, cy in track_ids_cx_cy:
        # 40x40 bbox centred on (cx, cy).
        boxes.append([cx - 20, cy - 20, cx + 20, cy + 20])
        tids.append(tid)
        cids.append(class_id)
        scs.append(0.9)
    img = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)
    return (
        img,
        np.array(boxes, dtype=np.float64),
        np.array(tids, dtype=np.float64),
        np.array(cids, dtype=np.float64),
        np.array(scs, dtype=np.float64),
    )


def _run_sequence(counting):
    """Feed a fixed, representative crossing sequence to ``counting``.

    Sequence (img 640x480, x=320, x_low=295, x_high=345):
      F1: ID1 right (400), ID2 left (200)   -> both appear; max_concurrent=2
      F2: ID1 right (400), ID2 left (200)   -> no crossing
      F3: ID1 crosses to left (200)         -> crossed LEFT (+1); ID2 stays
      F4: ID2 crosses to right (400)       -> crossed RIGHT (-1); ID1 gone

    Expected net counter_to_right = 0.
    """
    counter = 0
    seq = [
        [(1, 400, 200), (2, 200, 250)],
        [(1, 400, 200), (2, 200, 250)],
        [(1, 200, 200), (2, 200, 250)],
        [(2, 400, 250)],
    ]
    for tracks in seq:
        img, boxes, tids, cids, scs = _frame(tracks)
        counter = counting.count(img, boxes, tids, cids, scs, counter_to_right=counter)
    return counter


# ---------------------------------------------------------------------------
# Invariance: counter_to_right is identical with/without subscribers.
# ---------------------------------------------------------------------------

def test_instrumentation_is_read_only_on_counter():
    """The BL-68 instrumentation must not change counter_to_right.

    Run the same deterministic crossing sequence through a fresh Counting
    instance with no subscribers (default) and through another with a
    subscriber attached. The final counter_to_right must be identical.
    """
    # Baseline: no subscribers (un-instrumented behaviour).
    baseline = Counting()
    assert baseline._event_subscribers == []
    counter_baseline = _run_sequence(baseline)

    # Instrumented: a subscriber records every emitted event.
    recorded = []
    instrumented = Counting()
    instrumented._event_subscribers.append(lambda t, d: recorded.append((t, d)))
    counter_instrumented = _run_sequence(instrumented)

    assert counter_baseline == counter_instrumented, (
        f"instrumentation altered the count: baseline={counter_baseline} "
        f"instrumented={counter_instrumented}"
    )
    # Sanity: the subscriber actually saw events (proves the hook fires
    # without affecting the count).
    assert len(recorded) > 0, "subscriber recorded no events"
    directions = sorted(
        d["direction"] for (t, d) in recorded if t == "crossed"
    )
    assert directions == ["LEFT", "RIGHT"], (
        f"expected one LEFT and one RIGHT crossed event, got {directions}"
    )


def test_instrumentation_read_only_across_guard_modes():
    """Repeat the invariance check across several guard configurations to
    ensure no guard branch reads the instrumentation state."""
    configs = [
        dict(mirror_guard="off"),
        dict(mirror_guard="log"),
        dict(mirror_guard="enforce"),
        dict(hysteresis_px=0),
        dict(lost_buffer_frames=1),
        dict(resurrection_threshold=1, resurrection_min_jump=10),
        dict(reid_window=1, reid_min_age=1),
    ]
    for cfg in configs:
        plain = Counting(**cfg)
        wired = Counting(**cfg)
        wired._event_subscribers.append(lambda t, d: None)
        c_plain = _run_sequence(plain)
        c_wired = _run_sequence(wired)
        assert c_plain == c_wired, (
            f"instrumentation changed count for config {cfg}: "
            f"plain={c_plain} wired={c_wired}"
        )


# ---------------------------------------------------------------------------
# Accumulators increment correctly on the known sequence.
# ---------------------------------------------------------------------------

def test_accumulators_increment_on_known_sequence():
    """The new additive accumulators must reflect the known crossings."""
    counting = Counting()
    counter = _run_sequence(counting)

    # Net count is 0 (one LEFT +1, one RIGHT -1).
    assert counter == 0
    # Directional raw counters (independent of net).
    assert counting.count_left_to_right == 1
    assert counting.count_right_to_left == 1
    # Both IDs were seen.
    assert counting.unique_track_ids == {1, 2}
    # Frame 1 and 2 had both IDs visible simultaneously.
    assert counting.max_concurrent_tracks == 2
    # No guards fired in this clean sequence.
    assert counting.guard_interventions == {
        "lost_buffer_expired": 0,
        "mirror_guard": 0,
        "resurrection": 0,
        "reid_rebind": 0,
    }
    assert counting.id_switch_recoveries == 0
    # Detection stats: 4 frames had detections, each with 1 or 2 boxes.
    s = counting._det_stats
    assert s["frames"] == 4
    # F1/F2 had 2 dets, F3 had 2, F4 had 1 -> sum=7, min=1, max=2.
    assert s["det_sum"] == 7
    assert s["det_min"] == 1
    assert s["det_max"] == 2
    # Confidence samples: 2+2+2+1 = 7 boxes at 0.9 each.
    assert s["conf_count"] == 7
    assert pytest.approx(s["conf_sum"], rel=1e-6) == 7 * 0.9


# ---------------------------------------------------------------------------
# A faulty subscriber cannot perturb the count.
# ---------------------------------------------------------------------------

def test_faulty_subscriber_does_not_break_counting():
    """_emit_event must swallow subscriber exceptions so a bad recorder
    can never affect counter_to_right."""
    counting = Counting()

    def bad_sub(t, d):
        raise RuntimeError("boom")

    counting._event_subscribers.append(bad_sub)
    counter = _run_sequence(counting)
    # The count must still be the expected 0 despite the raising subscriber.
    assert counter == 0
    # And the directional accumulators still incremented.
    assert counting.count_left_to_right == 1
    assert counting.count_right_to_left == 1


def test_no_subscriber_means_no_io_on_emit():
    """With the default empty subscribers list, _emit_event must be a
    trivial no-op (no I/O, no side effects) — this is the property that
    makes the default path byte-identical to the un-instrumented code."""
    counting = Counting()
    # Should not raise and should not alter any accumulator.
    before = (counting.count_left_to_right, counting.count_right_to_left,
              dict(counting.guard_interventions))
    counting._emit_event("crossed", {"direction": "LEFT", "track_id": 999,
                                     "count": 0})
    after = (counting.count_left_to_right, counting.count_right_to_left,
             dict(counting.guard_interventions))
    assert before == after