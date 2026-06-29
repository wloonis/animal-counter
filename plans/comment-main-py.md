# Plan — Add role-explaining comment at top of `app/src/main.py`

## Context

User asked to add a pertinent comment to `app/src/main.py` that explains its role, placed at the beginning of the file. Constraint: do not create any other file, do not touch any other file. This is plan mode, so no edits will be made until the plan is submitted and approved.

## File

`./app/src/main.py` (single file to touch)

## What I learned about the file's role

From reading the file and `README.md`:
- It is the **main entry point** of the animal-counter (pig counting) application.
- It wires together all modules: `settings`, `core.inference`, `core.tracking`, `core.counting`, `ui.rendering`, `utils.frame_source`, `utils.shared_state`, `utils.timer_fps`, and the `OCSORTTracker`.
- It implements a **producer-consumer multi-threaded pipeline**:
  - `InferThread` — captures frames (camera or video file), runs TensorRT YOLO inference, post-processes detections, and pushes results into a bounded `Queue`.
  - `DisplayThread` — consumes the queue, runs OCSORT tracking, applies the counting logic, draws overlays/UI, displays the window, and records video when animals are detected.
- It manages **lifecycle and signals**: `stop()` for clean shutdown (joins threads, destroys OpenCV windows), SIGTERM/SIGINT handlers, and CLI argument parsing (`--input CAMERA|FILE`, `--file`, `--drawtracking`).
- It exposes a `start(input_source, video_path)` function that builds the tracker, the `Tracking`/`Counting`/`Rendering` helpers, the frame queue, and launches both threads.

## Approach

Insert **one** relevant comment block at the very top of the file (before the existing first line `# hello-plannotator`). The comment will summarize the entry-point role and the producer-consumer two-thread pipeline, so future readers immediately understand what this file is responsible for.

The comment will be a triple-quoted docstring-style block (matching the style already used 3 lines down in the file for the existing module docstring). No code changes, no other files modified.

## Files to modify

- `app/src/main.py` — prepend one comment block at the top.

## Reuse

- The existing module docstring on lines 2-7 already explains the high-level role at a glance. The new comment should complement (not duplicate) it by adding concrete information about the **two-thread pipeline** and the **lifecycle / CLI responsibilities** that the existing docstring does not mention.

## Steps

- [ ] Prepend a single comment block at the top of `app/src/main.py` describing:
  - Its role as the application entry point.
  - The two-thread producer-consumer pipeline (`InferThread` → queue → `DisplayThread`).
  - The lifecycle (`stop()`, signal handlers) and CLI parsing responsibilities.
- [ ] Do not modify any other file.
- [ ] Do not create any other file.

## Verification

- `read app/src/main.py` from line 1 to confirm the new comment is at the top, well-formed, and explains the file's role.
- Confirm the rest of the file is byte-identical to the current content.
- No runtime verification needed — comment-only change.
