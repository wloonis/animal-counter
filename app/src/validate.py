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

"""Result JSON writer for validate mode.

Provides `write_result_json()`, called only when `RESULT_JSON_PATH` is set
(mode validate). In normal serve mode this function is never called.
"""

import time
import datetime
import os
import json
import logging

from state import logger, shared_state


def write_result_json(result_path, video_path, shared_state, start_time, error=None):
    """Write structured result JSON after processing completes.

    Called only when RESULT_JSON_PATH env var is set (mode validate).
    In normal serve mode, this function is never called.
    """
    end_time = time.time()
    result = {
        "count": int(shared_state.counter_to_right),
        "video_file": os.path.basename(video_path),
        "timestamp": datetime.datetime.now().isoformat(),
        "duration_seconds": round(end_time - start_time, 2),
        "frames_processed": shared_state.infer_thread.frame_counter if shared_state.infer_thread else 0,
        "status": "error" if error else "completed",
        "error": str(error) if error else None
    }
    result_dir = os.path.dirname(result_path)
    if result_dir:
        os.makedirs(result_dir, exist_ok=True)
    with open(result_path, 'w') as f:
        json.dump(result, f, indent=2)
    logger.info(f"Result JSON written to {result_path}: {json.dumps(result)}")