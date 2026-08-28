# SPDX-License-Identifier: GPL-3.0-or-later
# animal-counter — pig counter on Jetson Orin Nano (OC-SORT + anti-ID-switch guards).
# Copyright (C) 2026  LOONIS Wennaël
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Main entry point for the pig counting application.

BL-29 refactor: this file is now a thin orchestration layer. The inference
thread, display thread, result-JSON writer, CLI/serve loop, and the
process-wide singletons (`shared_state`/`logger`/`settings`/`_IOU_METRICS`)
have been split into leaf modules:

- `state.py`         — `shared_state`, `logger`, `settings`, `_IOU_METRICS`
- `infer_thread.py`  — `class InferThread`
- `display_thread.py`— `class DisplayThread`
- `validate.py`      — `write_result_json()`
- `cli.py`           — `cli.main()` (argparse + serve/validate loop + poweroff)

What remains here is `start()` / `stop()` (the orchestration glue that
instantiates the threads and wires the history recorder) and the
`if __name__ == "__main__"` guard delegating to `cli.main()`.

Re-exports: `DisplayThread`, `shared_state`, `settings`, `logger` are exposed
as module-level names so `tests/test_finalize_recording_filename.py`
(`import main as main_mod; main_mod.DisplayThread; main_mod.shared_state;
main_mod.settings; main_mod.settings.OUTPUT_VIDEO_PATH`) keeps working
unchanged.
"""

import os
import logging

import cv2
from queue import Queue

# OC-SORT tracker (lib `trackers`). Tuned to resist ID switches near the
# counting line: longer lost_track_buffer + low high_conf_det_threshold so the
# OCR second-chance association can re-bind a briefly-occluded pig to its
# original ID instead of spawning a new one.
from trackers import OCSORTTracker
from trackers.utils.iou import IoU

from core.tracking import Tracking
from core.counting import Counting
from ui.rendering import Rendering
# BL-68: append-only JSONL counting-session history (serve mode only).
# Stdlib-only writer + dedicated heartbeat/compaction thread.
from core.history import HistoryWriter, HistoryThread

# Process-wide singletons (leaf module — no circular imports).
from state import (
    shared_state, settings, logger, _IOU_METRICS,
    load_runtime_settings, load_classes_yaml, publish_model_classes_json,
    read_onnx_class_names,
    resolve_counting_class_ids, resolve_counting_line_orientation,
    resolve_counting_direction, resolve_counting_direction_mode,
    resolve_mask_zones,
    resolve_input_config, resolve_output_fps,
    RuntimeSettingsWatcher,
)
# Split thread classes.
from infer_thread import InferThread
from display_thread import DisplayThread

import cli


def stop():
    logger.info("Stopping threads...")

    shared_state.stop_event.set()

    # Finalize the in-progress recording FIRST (before ending the history
    # session) so the per-video `video` JSONL line is written while the
    # HistoryWriter is still active (history.video() guards on _stopped).
    # _finalize_recording releases the mp4 writer (flushing the moov atom)
    # AND renames tmp-counting to tocompress-counting. Idempotent (no-op if
    # the loop already finalized). Best-effort: never raises into the
    # shutdown path. The SIGTERM handler calls stop(), so this covers SIGTERM.
    if shared_state.display_thread is not None:
        shared_state.display_thread._finalize_recording()

    # BL-68: finalize the history session (serve mode) before joining
    # threads, so the session_end line is fsync'd to /files even if a
    # later join times out or the process is killed during poweroff.
    # Idempotent (end_session guards on _stopped). Best-effort: never
    # raises into the shutdown path.
    hw = getattr(shared_state, "history_writer", None)
    if hw is not None:
        try:
            hw.end_session("clean")
        except Exception as e:
            logger.warning(f"history: end_session failed: {e!r}")
    ht = getattr(shared_state, "history_thread", None)
    if ht is not None and ht.is_alive():
        try:
            ht.stop_event.set()
            ht.join(timeout=2)
        except Exception as e:
            logger.warning(f"history: thread join failed: {e!r}")

    # BL-86: best-effort join of the runtime-settings watcher (mirrors the
    # HistoryThread join above). stop_event is already set at the top of
    # stop(), so the watcher exits its poll loop within poll_interval.
    sw = getattr(shared_state, "settings_watcher", None)
    if sw is not None and sw.is_alive():
        try:
            sw.join(timeout=2)
        except Exception as e:
            logger.warning(f"settings-watcher: thread join failed: {e!r}")

    if shared_state.infer_thread and shared_state.infer_thread.is_alive():
        shared_state.infer_thread.join(timeout=5)

    if shared_state.display_thread and shared_state.display_thread.is_alive():
        shared_state.display_thread.join(timeout=5)

    cv2.destroyAllWindows()

    logger.info("Stopped cleanly")


def start(input_source, video_path):
    """
    Start the pig counting application.

    Args:
        input_source (str): Input source (CAMERA or FILE).
        video_path (str): Path to video file.
    """
    logger.info("Started!")

    if shared_state.recording:
        return "Counting already started\nStop It if you want to start again."

    try:
        shared_state.recording = False

        # BL-78: load the model class catalog (classes.yaml, written at build
        # time by ansible/playbooks/model/build_model.yml). Best-effort: when
        # the file is absent (legacy deployed model without a rebuild) the
        # shared_state keeps its __init__ legacy defaults (['human','pig'],
        # default_counting_class=1, counting_class_ids=[1]) → byte-identical
        # pre-BL-78 counting behavior. publish_model_classes_json mirrors the
        # catalog to the read-only /conf/model-classes.json (IPC file #5,
        # app→companion) so the companion can label sub-counts.
        model_classes = load_classes_yaml()
        # Active model name (BL-89): used both to load <model_name>.engine AND
        # to resolve the per-model runtime-settings section + publish to the
        # companion via model-classes.json. Fallback `my_model` for legacy
        # deploys whose classes.yaml predates the model_name field.
        model_name = (model_classes or {}).get("model_name") or "my_model"
        # BL-96 part (b): once-per-process startup cross-check of the
        # classes.yaml nc/names against the class names embedded in the
        # deployed <model_name>.onnx metadata (state.read_onnx_class_names,
        # pure-stdlib grep — no onnx lib). The deployed .engine/.onnx is fixed
        # for a process lifetime, so the check runs only on the first start()
        # and the resulting 3-state classes_drift (False/True/None) is cached
        # on shared_state for later recordings to republish without re-reading
        # the .onnx. Fail-open: any error leaves classes_drift at null (could
        # not verify) and start() proceeds. Only runs when the catalog is
        # present — when classes.yaml is absent (legacy deploy) counting stays
        # byte-identical and classes_drift stays at its __init__ default (None).
        if model_classes is not None and not shared_state.classes_drift_checked:
            try:
                onnx_names = read_onnx_class_names(
                    f"./model/{model_name}.onnx")
                if onnx_names is None:
                    # .onnx missing / unreadable / unparseable — the helper
                    # already logged (INFO/WARNING); could not verify.
                    shared_state.classes_drift = None
                else:
                    onnx_nc, onnx_list = onnx_names
                    yaml_nc = model_classes.get("nc")
                    yaml_names = list(model_classes.get("names") or [])
                    if yaml_nc != onnx_nc or yaml_names != onnx_list:
                        shared_state.classes_drift = True
                        logger.warning(
                            "classes_drift=true: classes.yaml (nc=%r, "
                            "names=%r) differs from %s.onnx (nc=%r, "
                            "names=%r)", yaml_nc, yaml_names, model_name,
                            onnx_nc, onnx_list)
                    else:
                        shared_state.classes_drift = False
                        logger.info(
                            "classes_drift=false: classes.yaml matches "
                            "%s.onnx (nc=%r)", model_name, onnx_nc)
            except Exception as exc:
                # Fail-open: never let the cross-check abort start().
                logger.warning("classes_drift cross-check raised (%s): "
                               "%s; classes_drift=null", type(exc).__name__,
                               exc)
                shared_state.classes_drift = None
            shared_state.classes_drift_checked = True
        if model_classes is not None:
            shared_state.class_names = list(model_classes.get("names") or [])
            shared_state.default_counting_class = model_classes.get(
                "default_counting_class", 1)
            shared_state.model_version = model_classes.get("model_version")
            # BL-96 part (b): thread the once-per-process classes_drift
            # (cached on shared_state) into the IPC payload so the companion
            # can distinguish "checked OK" (false) / "drifted" (true) /
            # "could not verify" (null).
            publish_model_classes_json(
                shared_state.class_names,
                shared_state.default_counting_class,
                shared_state.model_version,
                model_name,
                classes_drift=shared_state.classes_drift,
            )

        if shared_state.infer_thread is None or (shared_state.infer_thread and not shared_state.infer_thread.is_alive()):
            engine_file_path = f"./model/{model_name}.engine"

            shared_state.stop_event.clear()

            byte_tracker = OCSORTTracker(
                lost_track_buffer=settings.TRACKER_LOST_TRACK_BUFFER,
                frame_rate=settings.TRACKER_FRAME_RATE,
                minimum_consecutive_frames=settings.TRACKER_MIN_CONSECUTIVE_FRAMES,
                minimum_iou_threshold=settings.TRACKER_MIN_IOU_THRESHOLD,
                direction_consistency_weight=settings.TRACKER_DIRECTION_CONSISTENCY_WEIGHT,
                high_conf_det_threshold=settings.TRACKER_HIGH_CONF_THRESHOLD,
                delta_t=settings.TRACKER_DELTA_T,
                iou=_IOU_METRICS.get(settings.COUNTING_TRACKER_IOU.lower(), IoU)(),
            )

            # BL-76: hot-reload runtime toggles from the shared runtime-settings.json
            # (written by the Jetson companion from the Android app) just before the
            # per-recording Tracking/Rendering/Counting instantiation. Falls back to
            # the current os.getenv-backed values for any missing/invalid key. Only the
            # 4 render-affecting keys are touched; TRACKER_*/COUNTING_*/PIG_* are never
            # overridden here.
            # BL-92: defaults for the configurable +1 direction; overwritten
            # inside the `isinstance(rt, dict)` block when the runtime
            # settings carry valid values. Kept defined here so the
            # Counting(...) constructor below works even when rt is absent.
            _dir_mode = None
            _dir = None
            rt = load_runtime_settings()
            if isinstance(rt, dict):
                if isinstance(rt.get("draw_tracking"), bool):
                    shared_state.draw_tracking = rt["draw_tracking"]
                if isinstance(rt.get("box_tracking"), bool):
                    shared_state.box_tracking = rt["box_tracking"]
                if isinstance(rt.get("centroid_tracking"), bool):
                    shared_state.centroid_tracking = rt["centroid_tracking"]
                # BL-87: draw_mask_zones is an independent toggle (default
                # true), NOT gated on draw_tracking — the mask overlay is a
                # detection-level concept that exists independent of tracking
                # visualization. Same boot-read pattern as the other toggles.
                if isinstance(rt.get("draw_mask_zones"), bool):
                    shared_state.draw_mask_zones = rt["draw_mask_zones"]
                _off = rt.get("offset_counting_line")
                if isinstance(_off, bool) or not isinstance(_off, int):
                    # bool is a subclass of int — reject it explicitly; only accept
                    # a plain signed int. BL-83: this loose sanity cap (-300..300)
                    # only garbage-filters; the AUTHORITATIVE bound (line stays
                    # inside the image with a 200px margin on both edges along the
                    # crossing axis: vertical x∈[200,W-200], horizontal y∈[200,H-200])
                    # is enforced by clamping the computed line position at use-time
                    # in counting.py + rendering.py, where frame dimensions are known.
                    pass
                elif -300 <= _off <= 300:
                    settings.OFFSET_PERCENT_COUNTING_LINE = _off
                else:
                    logger.warning("runtime-settings: offset_counting_line out of range (ignored): %r", _off)

                # BL-83: resolve the effective counting_line_orientation
                # ("vertical" | "horizontal") from runtime-settings.json, same
                # per-recording "next recording" semantics as offset_counting_line.
                # resolve_counting_line_orientation returns None for absent/invalid
                # → leave the settings default in place (do not overwrite).
                _orient = resolve_counting_line_orientation(rt)
                if _orient is not None:
                    settings.COUNTING_LINE_ORIENTATION = _orient

                # BL-92: resolve the configurable +1 counting direction.
                # `counting_direction_mode` ("auto" default | "manual") and
                # `counting_direction` (manual only; one of up|down|left|right,
                # validated against the effective orientation above). Per-
                # recording resolution (same "next recording" semantics as
                # offset_counting_line / counting_line_orientation). Absent/
                # invalid -> None -> the Counting constructor keeps its own
                # defaults (auto / None). No reset change here: boot always
                # starts fresh.
                _dir_mode = resolve_counting_direction_mode(rt)
                _dir = resolve_counting_direction(rt, settings.COUNTING_LINE_ORIENTATION)
                logger.info("counting direction resolved: mode=%r direction=%r",
                            _dir_mode, _dir)

                # BL-78: resolve the effective counting_class_ids set (3 levels:
                # model default from classes.yaml → companion override in
                # runtime-settings.json → validated against the model class
                # catalog). Per-recording resolution (same semantics as
                # offset_counting_line): a companion change takes effect on
                # the NEXT recording, never mid-recording. Invalid/unknown IDs
                # are dropped with a WARNING; fallback to the model default when
                # the override is absent/empty/all-invalid. sub_counts is reset
                # for the new recording ({class_id: 0}).
                shared_state.counting_class_ids = resolve_counting_class_ids(
                    rt,
                    {"names": shared_state.class_names,
                     "default_counting_class": shared_state.default_counting_class},
                )
                shared_state.sub_counts = {
                    cid: 0 for cid in shared_state.counting_class_ids}
                logger.info("counting_class_ids resolved: %r",
                            shared_state.counting_class_ids)

                # BL-87: resolve the effective mask_zones (detection-level
                # exclusion rects) from runtime-settings.json. Per-recording
                # resolution (same semantics as offset_counting_line): a
                # companion change takes effect on the NEXT recording, never
                # mid-recording. resolve_mask_zones returns None for
                # absent/invalid → leave the prior value in place (default []).
                # No counter reset on a mask change (mask alters WHERE we
                # count, not WHAT we count — analogous to line offset).
                _mz = resolve_mask_zones(rt)
                if _mz is not None:
                    shared_state.mask_zones = _mz
            tracking = Tracking(draw_box=shared_state.draw_tracking, shared_state=shared_state)
            counting = Counting(shared_state=shared_state, pig_confidence_threshold=settings.PIG_CONFIDENCE_THRESHOLD, offset_counting_line=settings.OFFSET_PERCENT_COUNTING_LINE, counting_line_orientation=settings.COUNTING_LINE_ORIENTATION, counting_direction_mode=(_dir_mode if _dir_mode is not None else "auto"), counting_direction=_dir, lost_buffer_frames=settings.COUNTING_LOST_BUFFER_FRAMES, reassoc_line_band=settings.COUNTING_REASSOC_LINE_BAND, reassoc_max_dist_x=settings.COUNTING_REASSOC_MAX_DIST_X, reassoc_max_dist_y=settings.COUNTING_REASSOC_MAX_DIST_Y, hysteresis_px=settings.COUNTING_HYSTERESIS_PX, mirror_guard=settings.COUNTING_MIRROR_GUARD, mirror_max_age=settings.COUNTING_MIRROR_MAX_AGE, mirror_line_band=settings.COUNTING_MIRROR_LINE_BAND, mirror_new_band=settings.COUNTING_MIRROR_NEW_BAND, mirror_max_dist_y=settings.COUNTING_MIRROR_MAX_DIST_Y, resurrection_threshold=settings.COUNTING_RESURRECTION_THRESHOLD, resurrection_min_jump=settings.COUNTING_RESURRECTION_MIN_JUMP, guard_max_age=settings.COUNTING_GUARD_MAX_AGE, reid_window=settings.COUNTING_REID_WINDOW, reid_min_age=settings.COUNTING_REID_MIN_AGE)
            # BL-78: plumb the resolved counting set to the counting pipeline.
            # Forward-compatible: settable attribute (constructor gains the
            # param in Task 9). DisplayThread/InferThread already import
            # shared_state and read shared_state.counting_class_ids directly.
            counting.counting_class_ids = list(shared_state.counting_class_ids)
            rendering = Rendering(draw_box=shared_state.draw_tracking, offset_counting_line=settings.OFFSET_PERCENT_COUNTING_LINE, counting_line_orientation=settings.COUNTING_LINE_ORIENTATION)

            max_queue_size = 3
            shared_state.frame_queue = Queue(maxsize=max_queue_size)

            # BL-93: per-model input config + output_fps (startup-only read —
            # NOT hot-reloaded; a camera↔drone switch = pod restart).
            # resolve_input_config returns {input_source, input_url,
            # input_device, input_width, input_height} with per-model values
            # when present/valid, else env fallbacks. resolve_output_fps
            # returns the per-model writer fps (fallback settings.FPS_OUTPUT=30).
            # These are read once here; the hot-reload watcher deliberately
            # ignores the input keys (startup-only by design).
            input_cfg = resolve_input_config(rt, settings)
            output_fps = resolve_output_fps(rt, settings)

            # Effective top-level input_source/video_path. A CLI override
            # (-m/-f, validation/test) is detected as a deviation from the env
            # baseline (settings.INPUT_SOURCE / settings.VIDEO_PATH) — keep those
            # as-is. Otherwise (serve mode, env baseline unchanged) apply the
            # per-model resolved values: CAMERA → input_device, STREAM →
            # input_url, FILE → video_path as passed. This makes start()
            # self-contained pre-Task-7 (cli.py still passes the env baseline in
            # serve mode); after Task-7 cli.py resolves the top-level itself and
            # this branch becomes a no-op (keeps the already-resolved values).
            if input_source != settings.INPUT_SOURCE or \
                    video_path != settings.VIDEO_PATH:
                # CLI override (validation/test): keep the caller's values.
                eff_input_source = input_source
                eff_video_path = video_path
            else:
                eff_input_source = input_cfg["input_source"]
                if eff_input_source == "CAMERA":
                    eff_video_path = input_cfg["input_device"] or video_path
                elif eff_input_source == "STREAM":
                    eff_video_path = input_cfg["input_url"] or video_path
                else:
                    # FILE: keep video_path as passed (per-model FILE uses
                    # the runtime-settings path only when explicitly set;
                    # validation passes the file path via -f).
                    eff_video_path = video_path

            logger.info(
                "BL-93 input config resolved: model=%r source=%r video_path=%r "
                "input_width=%r input_height=%r output_fps=%r",
                model_name, eff_input_source, eff_video_path,
                input_cfg["input_width"], input_cfg["input_height"],
                output_fps,
            )

            shared_state.infer_thread = InferThread(
                frame_queue=shared_state.frame_queue,
                max_queue_size=max_queue_size,
                engine_file_path=engine_file_path,
                video_path=eff_video_path,
                stop_event=shared_state.stop_event,
                input_type=eff_input_source,
                input_width=input_cfg["input_width"],
                input_height=input_cfg["input_height"],
                input_url=input_cfg["input_url"],
            )
            shared_state.display_thread = DisplayThread(frame_queue=shared_state.frame_queue, sort_tracker=byte_tracker, tracking=tracking, counting=counting, rendering=rendering, stop_event=shared_state.stop_event, input_type=eff_input_source, output_fps=output_fps)

            # BL-68: wire the history recorder (serve mode only — when
            # RESULT_JSON_PATH is unset, consistent with the existing
            # write_result_json branch). History is best-effort and must
            # never break counting: every step is wrapped in try/except.
            if not os.getenv("RESULT_JSON_PATH", "") and getattr(shared_state, "history_writer", None) is None:
                try:
                    hw = HistoryWriter(
                        path=settings.HISTORY_FILE,
                        settings=settings,
                        shared_state=shared_state,
                        counting=counting,
                        mode="serve",
                    )
                    shared_state.history_writer = hw
                    # Read-only subscriber: counting._emit_event → JSONL event line.
                    # Purely additive to the existing control flow.
                    counting._event_subscribers.append(hw.emit_event)
                    # Power-loss recovery + session_start + startup line.
                    hw.start_session(start_reason="boot")
                    # Dedicated thread: heartbeat loop + 1x/day compaction
                    # (serialized in one thread, never per-frame I/O).
                    shared_state.history_thread = HistoryThread(
                        writer=hw, stop_event=shared_state.stop_event
                    )
                    shared_state.history_thread.start()
                    logger.info(f"history: recorder started → {settings.HISTORY_FILE}")
                except Exception as e:
                    logger.warning(f"history: failed to start recorder: {e!r}")

            shared_state.infer_thread.start()
            shared_state.display_thread.start()

            # BL-86: start the runtime-settings watcher AFTER the worker
            # threads so it only picks up *subsequent* /conf changes (boot
            # read above is the one-shot). The watcher stores validated
            # pending settings on shared_state; DisplayThread.run() applies
            # them at the first idle window (single applier → no race).
            shared_state.settings_watcher = RuntimeSettingsWatcher(
                shared_state, shared_state.stop_event
            )
            shared_state.settings_watcher.start()
    except Exception as e:
        if logger.isEnabledFor(logging.ERROR):
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Exception: {repr(e)}")
            raise


if __name__ == "__main__":
    cli.main()