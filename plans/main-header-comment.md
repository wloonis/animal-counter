# Plan — Add descriptive header comment to app/src/main.py

## Context

The user wants a descriptive header comment at the top of `app/src/main.py` documenting its role as the entry point of the `animal-counter` application. The current top of the file is:

```python
# hello-plannotator
"""
Main application entry point for the pig counting application.

This module initializes and runs the pig counting application with TensorRT inference
and Norfair tracking.
"""

import threading
...
```

The first line (`# hello-plannotator`) is a terse one-line marker. The user wants a richer, multi-line header comment that complements (not duplicates) the existing module docstring 3 lines down.

## Approach

Replace the placeholder `# hello-plannotator` line with a multi-line descriptive header comment block that summarizes the file's role: which modules it wires, the producer-consumer pipeline (InferThread producer / DisplayThread consumer), and lifecycle/SIGTERM/CLI responsibilities. Keep the existing module docstring untouched so the two play complementary roles — the header comment focuses on architecture and threading, the docstring focuses on high-level purpose.

## File to modify

- `app/src/main.py` — single-file edit at the top, replacing only line 1 (`# hello-plannotator`).

## Reuse / constraints

- Do NOT touch the existing module docstring (lines 2–6). It serves a complementary purpose (high-level purpose statement).
- Do NOT modify any other file.
- Do NOT create any other file.
- The new header should be a plain Python comment (`#` lines), distinct from the docstring.

## Steps

- [ ] Edit `app/src/main.py`: replace the single `# hello-plannotator` line on line 1 with a multi-line `#` comment block covering:
  - Entry-point role for the `animal-counter` application.
  - Module wiring (settings, core.inference, core.tracking, core.counting, ui.rendering, utils.frame_source, utils.shared_state, utils.timer_fps, OCSORTTracker).
  - Producer–consumer multi-threaded pipeline:
    - `InferThread` (producer): captures frames + runs TensorRT YOLO inference, pushes results to a queue.
    - `DisplayThread` (consumer): pops the queue, runs OCSORT tracking + counting + UI rendering.
  - Lifecycle responsibilities: SIGTERM/SIGINT handling, CLI argument parsing, thread start/stop coordination.

## Verification

- `read app/src/main.py` and confirm:
  - Line 1 is replaced with the new descriptive header comment.
  - Lines 2–6 (the existing module docstring) are intact and untouched.
  - No imports, classes, functions, or other code below line 6 are changed.
- `git diff app/src/main.py` should show changes only on line 1 (replacement of the `# hello-plannotator` marker).
- No runtime behavior change — comment-only edit, so no functional tests needed.