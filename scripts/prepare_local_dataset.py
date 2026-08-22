#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 LOONIS Wennaël
"""One-shot: prepare a LOCAL dataset into the Ultralytics YOLO layout.

Reorganizes a local dataset (images + YOLO labels, e.g. an export with
``all/`` + ``test/`` subsets) into the standard Ultralytics layout under
``--out``::

    <out>/data.yaml
    <out>/images/{train,val,test}
    <out>/labels/{train,val,test}

so the training playbook (``ansible/playbooks/model/build_model.yml`` with
``TRAINING_DATASET_SOURCE=local``) can train from it WITHOUT any Roboflow
fetch — just point ``TRAINING_PROJECT_DIR=<out>``.

The input label format is YOLO (``class cx cy w h`` normalized) — the same as
the Roboflow ``yolo26`` export. Other input formats (COCO/VOC) can be added via
``--format`` later; for now only ``--format yolo`` (pass-through reorganize).

Stdlib only (no ultralytics/opencv/PyYAML needed) — runs on the control
machine. Idempotent: refuses a non-empty ``--out`` unless ``--force``.

Layout detection
----------------
Walks ``--src`` (max depth 4) for directories named ``images`` (case-insensitive)
that have a sibling ``labels`` dir. Each pair is classified by its path:

  * any component ``test``        → test pool
  * any component ``valid``/``val`` → val pool (pre-split, kept as-is)
  * any component ``all``/``train`` → train pool
  * otherwise                       → train pool (default)

If the val pool is empty but the train pool is non-empty, the train pool is
auto-split into train/val with ``--val-split`` (default 0.2 = 80/20),
**deterministically** by SHA-256 of the image stem (reproducible across runs).

Images without a matching label file get an **empty** label file (explicit
negative / background sample, matches Roboflow behavior — avoids Ultralytics
"no labels" warnings). Filename collisions within a split (e.g. two ``test/``
subsets) are resolved by prefixing the stem with the source subdirectory slug.

The generated ``data.yaml`` matches the shape the playbook already parses
(``nc`` + ``names``), with an absolute ``path:`` + relative train/val/test.
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
MAX_DEPTH = 4  # search depth for `images` dirs under --src


# ───────────────────────── helpers ─────────────────────────


def find_image_label_pairs(src: Path):
    """Return list of (images_dir, labels_dir, split) discovered under src.

    ``split`` ∈ {"train", "val", "test"}. Pairs with no sibling ``labels`` dir
    are skipped (warned).
    """
    pairs = []
    for root, dirs, _ in src.walk():
        # depth guard
        try:
            depth = len(root.relative_to(src).parts)
        except ValueError:
            continue
        if depth > MAX_DEPTH:
            dirs.clear()  # don't descend further
            continue
        if root.name.lower() == "images":
            labels_dir = root.parent / "labels"
            if labels_dir.is_dir():
                split = classify_split(root.relative_to(src))
                pairs.append((root, labels_dir, split))
            else:
                print(f"  ⚠️  images dir without sibling labels/ — skipped: {root}",
                      file=sys.stderr)
    return pairs


def classify_split(rel: Path) -> str:
    parts = {p.lower() for p in rel.parts}
    if "test" in parts:
        return "test"
    if "valid" in parts or "val" in parts:
        return "val"
    # 'all' / 'train' / default → train pool
    return "train"


def list_images(images_dir: Path):
    return sorted(
        p for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMG_EXTS
    )


def find_label(images_dir: Path, labels_dir: Path, img: Path):
    """Find the YOLO label for ``img`` by stem (case-insensitive suffix match)."""
    stem = img.stem
    # exact stem match (any .txt)
    cand = labels_dir / f"{stem}.txt"
    if cand.is_file():
        return cand
    # case-insensitive suffix match (e.g. img.JPG → label.txt with same stem)
    target = f"{stem}.txt".lower()
    for p in labels_dir.iterdir():
        if p.is_file() and p.name.lower() == target:
            return p
    return None


def parse_label_classes(label_path: Path):
    """Return the set of class ids present in a YOLO label file (0-row → empty)."""
    ids = set()
    with label_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(int(line.split()[0]))
            except (ValueError, IndexError):
                continue
    return ids


def sha_percent(stem: str) -> int:
    """Deterministic 0..99 bucket from a filename stem (reproducible split)."""
    h = hashlib.sha256(stem.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 100


# ───────────────────────── main ─────────────────────────


def main():
    ap = argparse.ArgumentParser(
        description="Prepare a local dataset into the Ultralytics YOLO layout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Example (sheep dataset):
  python3 scripts/prepare_local_dataset.py \\
    --src  /mnt/c/Users/tt/Downloads/dataset_11_images_avec_annotations/dataset_11_images_avec_annotations \\
    --out  dataset/sheep_template \\
    --names sheep
""",
    )
    ap.add_argument("--src", required=True, type=Path,
                    help="Local dataset root (contains all/ + test/ subsets, each with images/ + labels/).")
    ap.add_argument("--out", default=Path("dataset/sheep_template"), type=Path,
                    help="Output dir (default: dataset/sheep_template). Must be empty unless --force.")
    ap.add_argument("--names", default=None,
                    help="Comma-separated class names (e.g. 'sheep' or 'human,pig'). "
                         "If omitted, derived from the max class id in the labels (class_0..class_N).")
    ap.add_argument("--val-split", type=float, default=0.2,
                    help="Val fraction when no explicit val split is present (default 0.2 = 80/20).")
    ap.add_argument("--format", default="yolo", choices=["yolo"],
                    help="Input label format. 'yolo' = pass-through reorganize "
                         "(labels are already class cx cy w h). Others (coco/voc) reserved.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite a non-empty --out (deletes it first).")
    args = ap.parse_args()

    src = args.src.resolve()
    out = args.out.resolve()
    if not src.is_dir():
        sys.exit(f"❌ --src not a directory: {src}")

    # Resolve class names / nc.
    if args.names is not None:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
        if not names:
            sys.exit("❌ --names is empty after parsing")
        nc = len(names)
    else:
        names = None  # derive after scanning labels

    # Prepare out (refuse non-empty unless --force).
    if out.exists():
        if any(out.iterdir()):
            if not args.force:
                sys.exit(f"❌ --out is not empty: {out}\n   pass --force to overwrite.")
            print(f"  ℹ️  --force: removing existing {out}")
            shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    # Discover pairs.
    print(f"🔎 Scanning {src} …")
    pairs = find_image_label_pairs(src)
    if not pairs:
        sys.exit("❌ no images/+labels/ pairs found under --src. "
                 "Expected dirs with a sibling 'labels/' next to 'images/'.")
    for img_dir, lbl_dir, split in pairs:
        print(f"   • {split:5s}  images={len(list_images(img_dir)):4d}  {img_dir}")

    # Collect into pools.
    pools = {"train": [], "val": [], "test": []}
    # entries: (img_path, label_path_or_None, source_slug)
    for img_dir, lbl_dir, split in pairs:
        slug = img_dir.parent.name  # e.g. 'all', 'Nadir_and_oblique'
        for img in list_images(img_dir):
            lbl = find_label(img_dir, lbl_dir, img)
            pools[split].append((img, lbl, slug))

    # Auto-split train → train/val if val is empty.
    if not pools["val"] and pools["train"]:
        train_keep, val_keep = [], []
        for entry in pools["train"]:
            img = entry[0]
            if sha_percent(img.stem) < int(args.val_split * 100):
                val_keep.append(entry)
            else:
                train_keep.append(entry)
        pools["train"] = train_keep
        pools["val"] = val_keep
        print(f"  ℹ️  no explicit val — auto-split train {args.val_split:.0%} → "
              f"train={len(train_keep)} val={len(val_keep)}")

    # Derive nc/names from labels if not provided.
    all_label_ids = set()
    label_less = 0
    for split in ("train", "val", "test"):
        for img, lbl, _ in pools[split]:
            if lbl is not None:
                all_label_ids |= parse_label_classes(lbl)
            else:
                label_less += 1
    if names is None:
        nc = (max(all_label_ids) + 1) if all_label_ids else 1
        names = [f"class_{i}" for i in range(nc)]
    else:
        nc = len(names)
    if all_label_ids:
        bad = [i for i in sorted(all_label_ids) if i < 0 or i >= nc]
        if bad:
            sys.exit(f"❌ label class ids {bad} out of range [0,{nc}) for names={names}. "
                     "Check --names.")

    # Copy into out/images/<split> + out/labels/<split>.
    stats = {s: {"images": 0, "labels": 0, "anns": 0, "empty_labels": 0} for s in pools}
    for split in ("train", "val", "test"):
        img_out = out / "images" / split
        lbl_out = out / "labels" / split
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)
        seen_stems = set()
        for img, lbl, slug in pools[split]:
            stem = img.stem
            # collision handling within the split (e.g. merged test subsets)
            if stem in seen_stems:
                stem = f"{slug}__{stem}"
                if stem in seen_stems:
                    stem = f"{stem}_{hashlib.sha256(str(img).encode()).hexdigest()[:4]}"
            seen_stems.add(stem)
            dst_img = img_out / f"{stem}{img.suffix}"
            shutil.copy2(img, dst_img)
            stats[split]["images"] += 1
            dst_lbl = lbl_out / f"{stem}.txt"
            if lbl is not None:
                shutil.copy2(lbl, dst_lbl)
                stats[split]["labels"] += 1
                stats[split]["anns"] += sum(
                    1 for _ in lbl.open() if _.strip()
                )
            else:
                dst_lbl.write_text("")  # empty label = negative/background
                stats[split]["empty_labels"] += 1

    # Write data.yaml (absolute path, relative split dirs — standard Ultralytics).
    names_yaml = "[" + ", ".join(f"'{n}'" for n in names) + "]"
    data_yaml = out / "data.yaml"
    data_yaml.write_text(
        f"# Generated by scripts/prepare_local_dataset.py — local dataset (no Roboflow).\n"
        f"# Source: {src}\n"
        f"path: {out}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"test: images/test\n\n"
        f"nc: {nc}\n"
        f"names: {names_yaml}\n"
    )

    # Report.
    print("\n✅ Prepared dataset:")
    print(f"   out: {out}")
    print(f"   nc: {nc}  names: {names}")
    for s in ("train", "val", "test"):
        st = stats[s]
        if st["images"] == 0 and s == "test":
            print(f"   {s:5s}: (none)")
            continue
        print(f"   {s:5s}: images={st['images']:4d}  labels={st['labels']:4d}  "
              f"anns={st['anns']:5d}  empty_labels={st['empty_labels']}")
    if label_less:
        print(f"   ℹ️  {label_less} image(s) had no label file → empty label created "
              f"(background/negative samples).")
    print(f"\n   data.yaml: {data_yaml}")
    print("   → train with: TRAINING_DATASET_SOURCE=local, "
          f"TRAINING_PROJECT_DIR={out}")


if __name__ == "__main__":
    main()