#!/usr/bin/env python3
"""Export RGBD color/depth PNGs from local ROS-format RealSense .bag files.

Output layout matches official RGBD zip (Open3D / map_rgbd_pairs / rgbd_to_cg).
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

import numpy as np
from PIL import Image
from rosbags.rosbag1 import Reader
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from uvg_frame_map import cg_frame_id_to_playback_index  # noqa: E402
from uvg_io import (  # noqa: E402
    cg_to_rgbd_color_path,
    find_bag_files,
    iter_frame_pairs,
    list_sequences,
    parse_frame_id,
)


def parse_ros1_string(raw: bytes, off: int) -> tuple[bytes, int]:
    n = struct.unpack_from("<I", raw, off)[0]
    off += 4
    return raw[off : off + n], off + n


def parse_float64_array(raw: bytes, off: int) -> tuple[list[float], int]:
    n = struct.unpack_from("<I", raw, off)[0]
    off += 4
    vals = struct.unpack_from("<" + "d" * n, raw, off)
    return list(vals), off + 8 * n


def parse_ros1_image(raw: bytes) -> tuple[int, int, str, int, bytes]:
    off = 0
    off += 4  # seq
    off += 8  # stamp
    _, off = parse_ros1_string(raw, off)  # frame_id
    h = struct.unpack_from("<I", raw, off)[0]
    off += 4
    w = struct.unpack_from("<I", raw, off)[0]
    off += 4
    enc_b, off = parse_ros1_string(raw, off)
    off += 1  # is_bigendian
    step = struct.unpack_from("<I", raw, off)[0]
    off += 4
    dlen = struct.unpack_from("<I", raw, off)[0]
    off += 4
    data = raw[off : off + dlen]
    return h, w, enc_b.decode(), step, data


def parse_camera_info(raw: bytes) -> dict:
    off = 0
    off += 4
    off += 8
    _, off = parse_ros1_string(raw, off)
    height = struct.unpack_from("<I", raw, off)[0]
    off += 4
    width = struct.unpack_from("<I", raw, off)[0]
    off += 4
    _, off = parse_ros1_string(raw, off)  # distortion_model
    _, off = parse_float64_array(raw, off)  # D
    k, _ = parse_float64_array(raw, off)
    return {
        "width": int(width),
        "height": int(height),
        "fx": float(k[0]),
        "fy": float(k[4]),
        "cx": float(k[2]),
        "cy": float(k[5]),
        "intrinsic_matrix": k,
    }


def rgbd_stem_from_cg(cg_path: str) -> str:
    name = os.path.basename(cg_path)
    return name.replace("_CG_", "_RGBD_").replace(".ply", "")


def rgbd_paths_for_cg(cg_path: str) -> tuple[str, str]:
    seq_root = cg_path.split("consumer-grade_capture_system/CG/")[0]
    stem = rgbd_stem_from_cg(cg_path)
    color = os.path.join(
        seq_root, "consumer-grade_capture_system", "RGBD", "color", "15fps", stem + ".png"
    )
    depth = os.path.join(
        seq_root, "consumer-grade_capture_system", "RGBD", "depth", "15fps", stem + ".png"
    )
    return color, depth


def intrinsics_path(seq_root: str) -> str:
    return os.path.join(seq_root, "consumer-grade_capture_system", "RGBD", "intrinsics.json")


def image_bytes_to_array(h: int, w: int, enc: str, step: int, data: bytes) -> np.ndarray:
    if enc == "rgb8":
        row = np.frombuffer(data, dtype=np.uint8).reshape(h, step)
        rgb = row[:, : w * 3].reshape(h, w, 3)
        return rgb
    if enc in ("mono16", "16UC1"):
        row = np.frombuffer(data, dtype=np.uint16).reshape(h, step // 2)
        return row[:, :w]
    raise ValueError(f"Unsupported encoding: {enc}")


def read_first_camera_info(bag_path: str) -> dict | None:
    with Reader(bag_path) as reader:
        conns = [c for c in reader.connections if c.topic.endswith("Color_0/info/camera_info")]
        if not conns:
            return None
        for _, _, raw in reader.messages(connections=[conns[0]]):
            try:
                return parse_camera_info(raw)
            except Exception:
                return None
    return None


def read_topic_frames(
    bag_path: str,
    topic_suffix: str,
    max_index: int,
    needed: set[int] | None = None,
) -> dict[int, np.ndarray]:
    """Read selected playback indices only; decode skipped for other frames."""
    out: dict[int, np.ndarray] = {}
    needed = needed if needed is not None else set(range(max_index + 1))
    idx = -1
    with Reader(bag_path) as reader:
        conn = [c for c in reader.connections if c.topic.endswith(topic_suffix)][0]
        for _, _, raw in reader.messages(connections=[conn]):
            idx += 1
            if idx > max_index:
                break
            if idx not in needed:
                continue
            h, w, enc, step, data = parse_ros1_image(raw)
            out[idx] = image_bytes_to_array(h, w, enc, step, data)
    return out


def export_needed_frames_streaming(
    bag_path: str,
    needed: dict[int, tuple[str, str]],
    intrinsics_out: str,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Export needed playback indices; decode only those frames (low memory)."""
    if not needed:
        return 0, 0

    max_idx = max(needed)
    needed_set = set(needed)
    if dry_run:
        print(f"[export] dry-run bag={bag_path} frames={len(needed)} max_index={max_idx}")
        return len(needed), 0

    os.makedirs(os.path.dirname(intrinsics_out), exist_ok=True)
    if not os.path.isfile(intrinsics_out):
        cam_info = read_first_camera_info(bag_path)
        if cam_info:
            intr = {
                "width": cam_info["width"],
                "height": cam_info["height"],
                "fx": cam_info["fx"],
                "fy": cam_info["fy"],
                "cx": cam_info["cx"],
                "cy": cam_info["cy"],
                "source": "bag_camera_info",
            }
        else:
            intr = DEFAULT_INTRINSICS.copy()
            intr["source"] = "default"
        with open(intrinsics_out, "w", encoding="utf-8") as f:
            json.dump(intr, f, indent=2)

    colors = read_topic_frames(bag_path, "Color_0/image/data", max_idx, needed_set)
    depths = read_topic_frames(bag_path, "Depth_0/image/data", max_idx, needed_set)

    written = 0
    for idx, (color_out, depth_out) in needed.items():
        color_arr = colors.get(idx)
        depth_arr = depths.get(idx)
        if color_arr is None or depth_arr is None:
            continue
        os.makedirs(os.path.dirname(color_out), exist_ok=True)
        os.makedirs(os.path.dirname(depth_out), exist_ok=True)
        Image.fromarray(color_arr).save(color_out, compress_level=1)
        Image.fromarray(depth_arr).save(depth_out, compress_level=1)
        written += 1
        del colors[idx]
        del depths[idx]

    return written, len(needed) - written


def _export_bag_worker(args: tuple[str, dict[int, tuple[str, str]], str, bool]) -> tuple[str, int, int]:
    bag_path, needed, intr_out, dry_run = args
    w, m = export_needed_frames_streaming(bag_path, needed, intr_out, dry_run=dry_run)
    return os.path.basename(bag_path), w, m


DEFAULT_INTRINSICS = {
    "width": 1280,
    "height": 720,
    "fx": 908.739,
    "fy": 907.052,
    "cx": 638.914,
    "cy": 367.912,
}


def collect_cg_paths(raw_root: str, sequences: list[str], cg_version: str = "v2") -> list[str]:
    pairs = iter_frame_pairs(raw_root, sequences, cg_version=cg_version)
    return [p.cg_path for p in pairs]


def main() -> None:
    p = argparse.ArgumentParser(description="Export RGBD PNGs from ROS .bag files")
    p.add_argument("--raw-root", default=os.path.join(GC2026_ROOT, "data/raw"))
    p.add_argument("--sequences", nargs="*", default=None)
    p.add_argument("--cg-list", default=None, help="Only export frames listed in this CG path file")
    p.add_argument("--cg-version", default="v2", choices=["v1", "v2"])
    p.add_argument("--frame-map-mode", default="even", choices=["even", "identity"])
    p.add_argument("--bag-index", type=int, default=0, help="Which sorted .bag to read (default: first)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="Re-export even if PNG exists")
    p.add_argument(
        "--jobs",
        type=int,
        default=int(os.environ.get("EXPORT_JOBS", "0")),
        help="Parallel bag workers (default: min(bags, cpu_count))",
    )
    args = p.parse_args()
    if args.jobs <= 0:
        args.jobs = min(os.cpu_count() or 4, 8)

    if args.cg_list:
        with open(args.cg_list, "r", encoding="utf-8") as f:
            cg_paths = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        if args.sequences:
            seqs = args.sequences
        else:
            seqs = sorted(
                {
                    p.split("/UVG-CWI-DQPC/")[1].split("/")[0]
                    for p in cg_paths
                    if "/UVG-CWI-DQPC/" in p
                }
            )
    else:
        seqs = args.sequences or list_sequences(args.raw_root)
        cg_paths = collect_cg_paths(args.raw_root, seqs, cg_version=args.cg_version)

    by_bag: dict[str, dict[int, tuple[str, str]]] = {}
    skipped = 0
    for cg_path in cg_paths:
        if "consumer-grade_capture_system/CG/" not in cg_path:
            continue
        if not args.force:
            existing = cg_to_rgbd_color_path(cg_path)
            if existing and os.path.isfile(existing):
                depth = existing.replace("/color/", "/depth/")
                if os.path.isfile(depth):
                    skipped += 1
                    continue
        seq_root = cg_path.split("consumer-grade_capture_system/CG/")[0]
        bags = find_bag_files(seq_root)
        if not bags:
            continue
        bag = bags[min(args.bag_index, len(bags) - 1)]
        frame_id = parse_frame_id(cg_path)
        idx = cg_frame_id_to_playback_index(frame_id, mode=args.frame_map_mode)
        color_out, depth_out = rgbd_paths_for_cg(cg_path)
        by_bag.setdefault(bag, {})[idx] = (color_out, depth_out)

    total_needed = sum(len(v) for v in by_bag.values())
    print(f"[export_rosbag_rgbd] sequences={seqs} bags={len(by_bag)} frames={total_needed} skipped={skipped} jobs={args.jobs}")

    exported = 0
    missing = 0
    jobs = min(args.jobs, max(1, len(by_bag)))
    tasks = []
    for bag, needed in sorted(by_bag.items()):
        seq_root = bag.split("consumer-grade_capture_system/camera_output/")[0]
        intr_out = intrinsics_path(seq_root)
        tasks.append((bag, needed, intr_out, args.dry_run))

    if jobs <= 1 or len(tasks) <= 1:
        for bag, needed, intr_out, dry in tasks:
            w, m = export_needed_frames_streaming(bag, needed, intr_out, dry_run=dry)
            exported += w
            missing += m
            print(f"[export_rosbag_rgbd] {os.path.basename(bag)} written={w} missing={m}")
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(_export_bag_worker, t): t[0] for t in tasks}
            for fut in as_completed(futures):
                name, w, m = fut.result()
                exported += w
                missing += m
                print(f"[export_rosbag_rgbd] {name} written={w} missing={m}")

    meta = {
        "sequences": seqs,
        "bags": len(by_bag),
        "frames_needed": total_needed,
        "exported": exported,
        "missing": missing,
        "skipped_existing": skipped,
        "frame_map_mode": args.frame_map_mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = os.path.join(GC2026_ROOT, "data/processed/rosbag_rgbd_export.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"[export_rosbag_rgbd] meta -> {meta_path}")
    if missing > 0 and not args.dry_run:
        print(f"[export_rosbag_rgbd] WARN: {missing} frames not exported")


if __name__ == "__main__":
    main()
