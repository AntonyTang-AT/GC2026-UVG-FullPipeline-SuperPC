#!/usr/bin/env python3
"""Temporal sliding-window smoothing on enhanced PLY sequences (XYZ only; colors follow)."""
from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict

import numpy as np
from tqdm import tqdm

from uvg_io import read_ply_xyz_rgb, write_ply_xyz_rgb

FRAME_RE = re.compile(r"_(\d{4})\.ply$", re.IGNORECASE)


def parse_frame_id(path: str) -> int:
    match = FRAME_RE.search(path)
    if not match:
        raise ValueError(f"Cannot parse frame from {path}")
    return int(match.group(1))


def smooth_xyz_window(xyz_stack: np.ndarray, center: int, window: int) -> np.ndarray:
    """Per-point mean XYZ over a temporal window. xyz_stack: (T, N, 3)."""
    half = window // 2
    lo = max(0, center - half)
    hi = min(xyz_stack.shape[0], center + half + 1)
    return xyz_stack[lo:hi].mean(axis=0)

def main() -> None:
    parser = argparse.ArgumentParser(description="Temporal smooth enhanced PLY sequences")
    parser.add_argument("--in-dir", required=True, help="Directory with per-sequence enhanced PLY folders")
    parser.add_argument("--out-dir", required=True, help="Output directory (mirrors structure)")
    parser.add_argument("--window", type=int, default=5, help="Sliding window size (odd recommended)")
    parser.add_argument("--sequences", nargs="*", default=None, help="Optional sequence names to process")
    args = parser.parse_args()

    window = max(1, args.window)
    by_seq: dict[str, list[tuple[int, str]]] = defaultdict(list)

    for seq_name in sorted(os.listdir(args.in_dir)):
        seq_path = os.path.join(args.in_dir, seq_name)
        if not os.path.isdir(seq_path):
            continue
        if args.sequences and seq_name not in args.sequences:
            continue
        for fname in os.listdir(seq_path):
            if not fname.endswith(".ply"):
                continue
            full = os.path.join(seq_path, fname)
            by_seq[seq_name].append((parse_frame_id(full), full))

    for seq_name, items in tqdm(sorted(by_seq.items()), desc="sequences"):
        items = sorted(items, key=lambda x: x[0])
        frame_ids = [x[0] for x in items]
        paths = [x[1] for x in items]
        xyz_list = []
        rgb_list = []
        for p in paths:
            xyz, rgb = read_ply_xyz_rgb(p)
            xyz_list.append(xyz)
            rgb_list.append(rgb)

        out_seq_dir = os.path.join(args.out_dir, seq_name)
        os.makedirs(out_seq_dir, exist_ok=True)

        point_counts = {xyz.shape[0] for xyz in xyz_list}
        if len(point_counts) != 1:
            print(
                f"[temporal_smooth] WARN {seq_name}: variable point counts "
                f"{sorted(point_counts)[:8]} — copy without smoothing"
            )
            for src_path, xyz, rgb in zip(paths, xyz_list, rgb_list):
                out_path = os.path.join(out_seq_dir, os.path.basename(src_path))
                write_ply_xyz_rgb(out_path, xyz.astype(np.float32), rgb)
            continue

        xyz_stack = np.stack(xyz_list, axis=0)
        for i, src_path in enumerate(paths):
            smoothed_xyz = smooth_xyz_window(xyz_stack, i, window)
            rgb = rgb_list[i]
            out_path = os.path.join(out_seq_dir, os.path.basename(src_path))
            write_ply_xyz_rgb(out_path, smoothed_xyz.astype(np.float32), rgb)

    print(f"Smoothed {sum(len(v) for v in by_seq.values())} frames -> {args.out_dir}")


if __name__ == "__main__":
    main()
