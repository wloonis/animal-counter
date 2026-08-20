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
Leaf module holding the process-wide singletons used by the pig counting
application: the `Settings` instance, the `SharedState` instance (with its
draw_* field setup), the module `logger` (+ `logging.basicConfig`), and the
`_IOU_METRICS` map.

Every split module (`infer_thread`, `display_thread`, `cli`, `main`) imports
these singletons from here so they all bind to the *same* object instances
(no circular imports — this module imports nothing from the split modules).
"""

import json
import logging
import os
import tempfile

from settings import Settings
from utils.shared_state import SharedState
# OC-SORT tracker (lib `trackers`). Tuned to resist ID switches near the
# counting line: longer lost_track_buffer + low high_conf_det_threshold so the
# OCR second-chance association can re-bind a briefly-occluded pig to its
# original ID instead of spawning a new one.
from trackers.utils.iou import IoU, GIoU, DIoU, CIoU, BIoU

# Load settings
settings = Settings()

# Configure logging
logging.basicConfig(format='%(levelname)s:%(message)s', level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

# Shared state
shared_state = SharedState()
shared_state.draw_tracking = settings.DRAW_TRACKING
shared_state.centroid_tracking = settings.CENTROID_TRACKING
shared_state.box_tracking = settings.BOX_TRACKING
# BL-58 bounding-box render tuning (visual only - no counting/tracking impact)
shared_state.draw_box_line_thickness = settings.DRAW_BOX_LINE_THICKNESS
shared_state.draw_label_font_scale = settings.DRAW_LABEL_FONT_SCALE
shared_state.draw_label_thickness = settings.DRAW_LABEL_THICKNESS
shared_state.draw_centroid_radius = settings.DRAW_CENTROID_RADIUS

# Map the COUNTING_TRACKER_IOU setting (string) to a BaseIoU instance for
# OCSORTTracker(iou=...). trackers>=2.5.0 expects an IoU instance, not a string.
_IOU_METRICS = {"iou": IoU, "giou": GIoU, "diou": DIoU, "ciou": CIoU, "biou": BIoU}

# BL-76: shared file used by the Jetson companion to push runtime toggles
# (hot-reloaded at the start of each recording by main.py). BL-79 split:
# config/control files live in /conf (hostPath /data/orin/conf), separate
# from data files in /files (hostPath /data/orin/files, e.g.
# counting-history.jsonl, BL-68). Both hostPaths are mounted RW in the pod.
RUNTIME_SETTINGS_PATH = "/conf/runtime-settings.json"
# BL-78: model class catalog. classes.yaml is the source of truth, written at
# build time by ansible/playbooks/model/build_model.yml (Task 2) into the
# model dir (pod-side /app/model/classes.yaml). model-classes.json is a
# read-only mirror the app publishes at startup under /conf (IPC file #5,
# app->companion) so the companion knows which classes the model can count.
CLASSES_YAML_PATH = "/app/model/classes.yaml"
MODEL_CLASSES_PATH = "/conf/model-classes.json"


def load_runtime_settings():
    """Best-effort read of the shared runtime-settings.json file.

    Returns a dict (possibly empty) deserialized from RUNTIME_SETTINGS_PATH.
    Any read/parse error is logged at WARNING level and yields `{}` — the
    caller is expected to fall back on os.getenv / existing defaults for the
    missing keys. Never raises.
    """
    try:
        with open(RUNTIME_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
        logger.warning("runtime-settings.json is not a JSON object: %r", data)
        return {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("runtime-settings.json unreadable (%s): %s",
                        type(exc).__name__, exc)
        return {}


def load_classes_yaml():
    """Best-effort read of the model classes.yaml catalog (BL-78).

    Returns a dict with keys ``model_version``, ``nc``, ``names`` (list) and
    ``default_counting_class`` (int) on success, or ``None`` when the file is
    absent / unreadable / unparseable. Any error is logged at WARNING level and
    the function returns ``None`` (fail-open): the caller then keeps the
    SharedState legacy defaults (``['human', 'pig']``, ``1``, ``[1]``) — i.e.
    the exact pre-BL-78 behavior. Never raises.

    YAML parsing uses PyYAML when available (deferred import so this module
    loads even on images without PyYAML); a missing PyYAML is treated as a
    fail-open ``None`` rather than a hard dependency.
    """
    try:
        try:
            import yaml  # deferred import — not a hard runtime dependency
        except ImportError:
            logger.warning("PyYAML unavailable — cannot parse classes.yaml; "
                           "falling back to legacy class defaults")
            return None
        with open(CLASSES_YAML_PATH, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            logger.warning("classes.yaml is not a YAML mapping: %r", data)
            return None
        names = data.get("names")
        nc = data.get("nc")
        default = data.get("default_counting_class")
        if not isinstance(names, list) or not names:
            logger.warning("classes.yaml 'names' is not a non-empty list: %r",
                           names)
            return None
        if not isinstance(nc, int) or nc != len(names):
            logger.warning("classes.yaml 'nc' mismatch (nc=%r, len(names)=%d); "
                           "trusting len(names)", nc, len(names))
            nc = len(names)
        if not isinstance(default, int) or not (0 <= default < nc):
            logger.warning("classes.yaml 'default_counting_class' invalid "
                           "(%r) for nc=%d; falling back to legacy defaults",
                           default, nc)
            return None
        return {
            "model_version": data.get("model_version"),
            "nc": nc,
            "names": list(names),
            "default_counting_class": default,
        }
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("classes.yaml unreadable (%s): %s",
                        type(exc).__name__, exc)
        return None


def publish_model_classes_json(class_names, default_counting_class,
                                model_version):
    """Atomically write the read-only /conf/model-classes.json mirror (BL-78).

    Schema: ``{model_version, nc, names, default_counting_class}``. The file
    is written to a temp path then ``os.replace``-d into place so the companion
    never observes a half-written file. Best-effort: any failure is logged at
    WARNING level and the app continues counting (the companion simply won't
    see the catalog until the next successful write). Never raises.
    """
    payload = {
        "model_version": model_version,
        "nc": len(class_names),
        "names": list(class_names),
        "default_counting_class": int(default_counting_class),
    }
    try:
        os.makedirs(os.path.dirname(MODEL_CLASSES_PATH), exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(MODEL_CLASSES_PATH),
            prefix=".model-classes.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp_path, MODEL_CLASSES_PATH)
        except Exception:
            # cleanup the temp file if the write/replace failed mid-way
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        logger.info("published model-classes.json (nc=%d, default=%s)",
                    payload["nc"], payload["default_counting_class"])
    except (OSError, ValueError) as exc:
        logger.warning("failed to publish model-classes.json (%s): %s",
                        type(exc).__name__, exc)


def resolve_counting_class_ids(rt, model_classes):
    """Resolve the effective counting_class_ids set (BL-78, 3 levels).

    ``rt`` is the runtime-settings dict (from ``load_runtime_settings()``);
    ``model_classes`` is the catalog returned by ``load_classes_yaml()`` (or a
    dict shaped ``{names: [...], default_counting_class: N}``).

    Resolution order:
      1. ``rt['counting_class_ids']`` companion override — must be a list of
         ints, each a valid index into ``model_classes['names']``. Invalid IDs
         are dropped with a WARNING log.
      2. Fallback to ``[model_classes['default_counting_class']]`` when the
         override is absent / empty / entirely invalid.

    Returns a list of ints (never empty, never ``None``). Never raises.
    """
    names = model_classes.get("names", []) if model_classes else []
    nc = len(names)
    default = (model_classes.get("default_counting_class")
               if model_classes else None)

    raw = rt.get("counting_class_ids") if isinstance(rt, dict) else None
    if isinstance(raw, list) and raw:
        valid = []
        for cid in raw:
            if isinstance(cid, int) and isinstance(cid, bool) is False \
                    and 0 <= cid < nc:
                valid.append(cid)
            else:
                logger.warning("counting_class_ids: dropping invalid id %r "
                                "(valid range 0..%d)", cid, nc - 1)
        if valid:
            return valid
        logger.warning("counting_class_ids all-invalid; falling back to "
                       "default_counting_class")
    elif raw is not None:
        logger.warning("counting_class_ids must be a list of ints, got %r; "
                        "falling back to default_counting_class", raw)

    # Fallback to the model default (or legacy 1 when no catalog).
    fallback = default if isinstance(default, int) and 0 <= default < nc else 1
    return [fallback]