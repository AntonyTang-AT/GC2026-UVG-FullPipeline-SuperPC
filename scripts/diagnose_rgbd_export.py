#!/usr/bin/env python3
"""Forensics: ROS bag export vs expected RGBD layout (read-only)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
from PIL import Image
from rosbags.rosbag1 import Reader

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from export_rosbag_rgbd import DEFAULT_INTRINSICS, parse_camera_info, read_first_camera_info  # noqa: E402
from uvg_frame_map import cg_frame_id_to_playback_index  # noqa: E402
from uvg_io import (  # noqa: E402
    cg_to_rgbd_color_path,
    find_bag_files,
    find_rgbd_intrinsics,
    parse_frame_id,
    rgbd_color_to_depth_path,
)


def bag_header_type(path: str) -> str:
    with open(path, "rb") as f:
        head = f.read(64)
    if head.startswith(b"#ROSBAG"):
        return "rosbag_v2"
    if head.startswith(b"RealSense"):
        return "realsense_native"
    return f"unknown:{head[:16]!r}"


def bag_topics(path: str) -> list[dict]:
    out = []
    with Reader(path) as reader:
        for c in reader.connections:
            out.append({"topic": c.topic, "msgtype": c.msgtype, "msgcount": c.msgcount})
    return out


def depth_stats(path: str) -> dict:
    arr = np.asarray(Image.open(path))
    if arr.ndim == 3:
        arr = arr[:, :, 0]
    nz = arr[arr > 0]
    return {
        "shape": list(arr.shape),
        "dtype": str(arr.dtype),
        "min": int(arr.min()),
        "max": int(arr.max()),
        "nonzero_mean": float(nz.mean()) if nz.size else 0.0,
        "nonzero_pct": float(100.0 * nz.size / arr.size),
    }


def implied_depth_scale_mm(stats: dict) -> dict:
    """Rough check: if depth is mm, mean ~500-3000; if raw 16-bit units, much larger."""
    m = stats.get("nonzero_mean", 0)
    return {
        "if_mm_units": m / 1000.0,
        "if_scale_1000": m / 1000.0,
        "if_scale_5000": m / 5000.0,
        "if_scale_65535": m / 65535.0,
    }


def analyze_sequence(seq_root: str, cg_samples: list[str], frame_map: str) -> dict:
    seq = os.path.basename(seq_root.rstrip("/"))
    bags = find_bag_files(seq_root)
    rgbd_root = os.path.join(seq_root, "consumer-grade_capture_system", "RGBD")
    intr_path = find_rgbd_intrinsics(rgbd_root)
    intr_file = json.load(open(intr_path)) if intr_path and os.path.isfile(intr_path) else {}

    bag_info = []
    for i, bag in enumerate(bags[:3]):
        info = read_first_camera_info(bag)
        bag_info.append(
            {
                "index": i,
                "path": bag,
                "header": bag_header_type(bag),
                "topics": bag_topics(bag)[:8],
                "camera_info_K": info.get("intrinsic_matrix") if info else None,
            }
        )

    frame_checks = []
    for cg in cg_samples[:5]:
        fid = parse_frame_id(cg)
        pidx = cg_frame_id_to_playback_index(fid, mode=frame_map)
        color = cg_to_rgbd_color_path(cg)
        depth = rgbd_color_to_depth_path(color) if color else None
        entry = {
            "frame_id": fid,
            "playback_index": pidx,
            "color_exists": bool(color and os.path.isfile(color)),
            "depth_exists": bool(depth and os.path.isfile(depth)),
        }
        if depth and os.path.isfile(depth):
            ds = depth_stats(depth)
            entry["depth_stats"] = ds
            entry["depth_scale_hint"] = implied_depth_scale_mm(ds)
        frame_checks.append(entry)

    return {
        "sequence": seq,
        "n_bags": len(bags),
        "intrinsics_file": intr_path,
        "intrinsics_vs_default": {
            "file": {k: intr_file.get(k) for k in ("fx", "fy", "cx", "cy", "width", "height")},
            "default": DEFAULT_INTRINSICS,
            "match_default": all(
                abs(float(intr_file.get(k, 0)) - float(DEFAULT_INTRINSICS[k])) < 0.01
                for k in ("fx", "fy", "cx", "cy")
            ) if intr_file else None,
        },
        "bags_sample": bag_info,
        "frame_checks": frame_checks,
        "conclusion_hint": (
            "Official RGBD zip provides ROS bags only; PNGs are from export_rosbag_rgbd. "
            "Compare bag camera_info vs intrinsics.json and depth value ranges."
        ),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sequences", nargs="*", default=["TicTacToe", "VictoryHeart", "BlueSpeech"])
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--frame-map-mode", default="even")
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/rgbd_export_forensics.json"))
    args = p.parse_args()

    by_seq: dict[str, list[str]] = {}
    with open(args.cg_list, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or "/UVG-CWI-DQPC/" not in ln:
                continue
            seq = ln.split("/UVG-CWI-DQPC/")[1].split("/")[0]
            if args.sequences and seq not in args.sequences:
                continue
            by_seq.setdefault(seq, []).append(ln)

    results = []
    for seq in args.sequences:
        if seq not in by_seq:
            continue
        seq_root = by_seq[seq][0].split("consumer-grade_capture_system/CG/")[0]
        results.append(analyze_sequence(seq_root, by_seq[seq], args.frame_map_mode))

    report = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "frame_map_mode": args.frame_map_mode,
        "sequences": results,
        "global_note": (
            "No official pre-rendered PNG in RGBD zip; all PNG from rosbag export. "
            "Bags are RealSense SDK ROSBAG V2 (librealsense-readable); cwipc needs "
            "cwipc_realsense2_playback(camera_config.json), not --playback bag.bag."
        ),
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"out": args.out_json, "n_seq": len(results)}, indent=2))


if __name__ == "__main__":
    main()
