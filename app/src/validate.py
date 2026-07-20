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