#!/usr/bin/env python3
"""15fps CG frame ids mapped to 30fps RGBD/cwipc playback indices."""
from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from uvg_io import parse_frame_id  # noqa: E402


def cg_frame_id_to_playback_index(
    frame_id: str,
    cg_fps: int = 15,
    source_fps: int = 30,
    mode: str = "even",
) -> int:
    idx15 = int(frame_id)
    if mode == "identity":
        return idx15
    if mode == "even":
        if source_fps == 30 and cg_fps == 15:
            return idx15 * 2
        ratio = max(1, int(round(source_fps / cg_fps)))
        return idx15 * ratio
    raise ValueError(f"Unknown frame map mode: {mode}")


def build_playback_map(
    cg_paths: list[str],
    cg_fps: int = 15,
    source_fps: int = 30,
    mode: str = "even",
) -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for cg_path in cg_paths:
        frame_id = parse_frame_id(cg_path)
        playback_index = cg_frame_id_to_playback_index(frame_id, cg_fps, source_fps, mode)
        mapping[cg_path] = {
            "frame_id": frame_id,
            "playback_index": playback_index,
            "cg_fps": cg_fps,
            "source_fps": source_fps,
            "mode": mode,
        }
    return mapping


def main() -> None:
    p = argparse.ArgumentParser(description="Build CG path -> cwipc playback index map")
    p.add_argument(
        "--cg-list",
        default=os.path.join(GC2026_ROOT, "data/processed/all_cg_only.txt"),
    )
    p.add_argument(
        "--pairs-file",
        default=None,
        help="Alias for --cg-list (same one-column CG path list)",
    )
    p.add_argument(
        "--out-json",
        default=os.path.join(GC2026_ROOT, "data/processed/frame_playback_map.json"),
    )
    p.add_argument("--cg-fps", type=int, default=15)
    p.add_argument("--source-fps", type=int, default=30)
    p.add_argument("--mode", default="even", choices=["even", "identity"])
    args = p.parse_args()
    if args.pairs_file:
        args.cg_list = args.pairs_file

    with open(args.cg_list, "r", encoding="utf-8") as f:
        cg_paths = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]

    mapping = build_playback_map(cg_paths, args.cg_fps, args.source_fps, args.mode)
    out = {
        "cg_list": args.cg_list,
        "cg_fps": args.cg_fps,
        "source_fps": args.source_fps,
        "mode": args.mode,
        "num_frames": len(mapping),
        "mapping": mapping,
    }
    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Written {args.out_json} ({len(mapping)} frames)")


if __name__ == "__main__":
    main()
