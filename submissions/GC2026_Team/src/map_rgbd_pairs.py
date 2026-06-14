#!/usr/bin/env python3
"""Map CG PLY paths to RGBD color images and optional intrinsics."""
from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from uvg_io import cg_to_rgbd_color_path, iter_frame_pairs, list_sequences  # noqa: E402

GC2026_ROOT = os.path.dirname(SCRIPT_DIR)


def find_intrinsics(rgbd_dir: str, stem: str) -> str | None:
    for name in (f"{stem}_intrinsics.json", f"{stem}_intrinsics.npy", "intrinsics.json", "camera_intrinsics.json"):
        p = os.path.join(rgbd_dir, name)
        if os.path.isfile(p):
            return p
    calib = os.path.join(rgbd_dir, "calibration")
    if os.path.isdir(calib):
        for name in os.listdir(calib):
            if "intrinsic" in name.lower() and name.endswith((".json", ".npy", ".txt")):
                return os.path.join(calib, name)
    return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw-root", default=os.path.join(GC2026_ROOT, "data/raw"))
    p.add_argument("--out-dir", default=os.path.join(GC2026_ROOT, "data/processed"))
    p.add_argument("--sequences", nargs="*", default=None)
    args = p.parse_args()

    seqs = args.sequences or list_sequences(args.raw_root)
    pairs = iter_frame_pairs(args.raw_root, seqs)

    os.makedirs(args.out_dir, exist_ok=True)
    pairs_path = os.path.join(args.out_dir, "rgbd_pairs.txt")
    missing_path = os.path.join(args.out_dir, "rgbd_missing.txt")

    mapped = 0
    missing = 0
    with open(pairs_path, "w", encoding="utf-8") as f_out, open(missing_path, "w", encoding="utf-8") as f_miss:
        for pair in pairs:
            cg = pair.cg_path
            rgb = cg_to_rgbd_color_path(cg)
            if rgb is None or not os.path.isfile(rgb):
                f_miss.write(cg + "\n")
                missing += 1
                continue
            rgbd_dir = os.path.dirname(os.path.dirname(rgb)) if "/color/" in rgb else os.path.dirname(rgb)
            stem = os.path.splitext(os.path.basename(rgb))[0]
            intr = find_intrinsics(rgbd_dir, stem) or ""
            f_out.write(f"{cg}\t{rgb}\t{intr}\n")
            mapped += 1

    meta = {
        "sequences": seqs,
        "total_cg_frames": len(pairs),
        "mapped": mapped,
        "missing_rgb": missing,
        "pairs_file": pairs_path,
        "missing_file": missing_path,
    }
    meta_path = os.path.join(args.out_dir, "rgbd_pairs_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"[map_rgbd_pairs] mapped={mapped} missing={missing} -> {pairs_path}")
    if missing > 0:
        print(f"[map_rgbd_pairs] missing list: {missing_path}")


if __name__ == "__main__":
    main()
