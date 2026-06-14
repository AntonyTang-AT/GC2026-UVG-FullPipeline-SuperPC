#!/usr/bin/env python3
"""Full Pipeline stage 1: reconstruct consumer-grade PLY from RGBD (or .bag via cwipc)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Optional

import numpy as np
from PIL import Image
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from uvg_io import (  # noqa: E402
    cg_to_rgbd_color_path,
    find_bag_files,
    find_rgbd_intrinsics,
    load_pinhole_intrinsics,
    parse_frame_id,
    rgbd_color_to_depth_path,
    write_ply_xyz_rgb,
)


def read_depth_array(path: str) -> np.ndarray:
    img = Image.open(path)
    arr = np.asarray(img)
    if arr.ndim == 3:
        arr = arr[:, :, 0]
    return arr.astype(np.float32)


def reconstruct_frame_open3d(
    color_path: str,
    depth_path: str,
    intrinsics_path: Optional[str],
    depth_scale: float,
    depth_trunc_mm: float,
) -> tuple[np.ndarray, np.ndarray]:
    import open3d as o3d

    color = o3d.io.read_image(color_path)
    depth = o3d.io.read_image(depth_path)
    color_arr = np.asarray(color)
    h, w = color_arr.shape[0], color_arr.shape[1]
    fx, fy, cx, cy = load_pinhole_intrinsics(intrinsics_path, w, h)
    intrinsic = o3d.camera.PinholeCameraIntrinsic(int(w), int(h), fx, fy, cx, cy)
    # Open3D outputs metric coordinates when depth_scale converts mm depth to meters.
    depth_trunc_m = float(depth_trunc_mm) / 1000.0
    rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
        color,
        depth,
        depth_scale=float(depth_scale),
        depth_trunc=depth_trunc_m,
        convert_rgb_to_intensity=False,
    )
    pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd, intrinsic)
    pts_m = np.asarray(pcd.points, dtype=np.float32)
    valid_idx = np.where(np.isfinite(pts_m).all(axis=1) & (pts_m[:, 2] > 0.1))[0]
    pcd = pcd.select_by_index(valid_idx)
    pcd.transform([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]])
    xyz_m = np.asarray(pcd.points, dtype=np.float32)
    rgb = np.asarray(pcd.colors, dtype=np.float32)
    xyz = xyz_m * 1000.0
    return xyz, rgb


def try_cwipc_from_bag(bag_path: str, out_dir: str, count: int) -> bool:
    cwipc = shutil.which("cwipc")
    if not cwipc:
        return False
    os.makedirs(out_dir, exist_ok=True)
    cmd = [cwipc, "copy", "--playback", bag_path, "--count", str(count), out_dir]
    try:
        subprocess.run(cmd, check=True, timeout=3600)
        return any(f.endswith(".ply") for f in os.listdir(out_dir))
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def main() -> None:
    p = argparse.ArgumentParser(description="RGBD/bag -> CG-format PLY for Full Pipeline")
    p.add_argument("--cg-list", required=True, help="Reference CG paths (defines frames and output names)")
    p.add_argument("--out-root", required=True, help="Output root; mirrors sequence/CG_15fps naming")
    p.add_argument("--depth-scale", type=float, default=1000.0, help="Depth units to meters (mm=1000)")
    p.add_argument("--depth-trunc-mm", type=float, default=5000.0)
    p.add_argument("--max-samples", type=int, default=0)
    p.add_argument("--prefer-cwipc-bag", action="store_true", help="Try cwipc on .bag before RGBD images")
    args = p.parse_args()

    with open(args.cg_list, "r", encoding="utf-8") as f:
        cg_paths = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if args.max_samples > 0:
        cg_paths = cg_paths[:args.max_samples]

    records = []
    missing_rgbd = 0
    ok = 0

    for cg_path in tqdm(cg_paths, desc="rgbd_to_cg"):
        seq = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(cg_path)))))
        out_path = os.path.join(args.out_root, seq, os.path.basename(cg_path))
        if os.path.isfile(out_path):
            ok += 1
            continue

        seq_root = cg_path.split("consumer-grade_capture_system/CG/")[0]
        rgbd_root = os.path.join(seq_root, "consumer-grade_capture_system", "RGBD")

        if args.prefer_cwipc_bag:
            bags = find_bag_files(seq_root)
            if bags:
                tmp = os.path.join(args.out_root, ".cwipc_tmp", seq)
                if try_cwipc_from_bag(bags[0], tmp, 1):
                    plies = sorted([f for f in os.listdir(tmp) if f.endswith(".ply")])
                    if plies:
                        os.makedirs(os.path.dirname(out_path), exist_ok=True)
                        shutil.copy2(os.path.join(tmp, plies[0]), out_path)
                        ok += 1
                        continue

        color_path = cg_to_rgbd_color_path(cg_path)
        if not color_path or not os.path.isfile(color_path):
            missing_rgbd += 1
            continue
        depth_path = rgbd_color_to_depth_path(color_path)
        if not depth_path or not os.path.isfile(depth_path):
            missing_rgbd += 1
            continue
        stem = os.path.splitext(os.path.basename(color_path))[0]
        intrinsics = find_rgbd_intrinsics(rgbd_root, stem)
        try:
            xyz, rgb = reconstruct_frame_open3d(
                color_path,
                depth_path,
                intrinsics,
                args.depth_scale,
                args.depth_trunc_mm,
            )
        except Exception as exc:
            print(f"[WARN] reconstruct failed {cg_path}: {exc}")
            missing_rgbd += 1
            continue
        if xyz.shape[0] < 100:
            missing_rgbd += 1
            continue
        write_ply_xyz_rgb(out_path, xyz, rgb)
        records.append(
            {
                "frame_id": parse_frame_id(cg_path),
                "cg_ref": cg_path,
                "out_path": out_path,
                "color_path": color_path,
                "depth_path": depth_path,
                "points": int(xyz.shape[0]),
            }
        )
        ok += 1

    meta = {
        "out_root": args.out_root,
        "requested": len(cg_paths),
        "written": ok,
        "missing_rgbd": missing_rgbd,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    meta_path = os.path.join(args.out_root, "rgbd_to_cg_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"summary": meta, "records": records}, f, indent=2)
    print(json.dumps(meta, indent=2))
    if ok == 0:
        raise SystemExit(
            "No frames reconstructed. Download RGBD: bash scripts/download_full_pipeline_data.sh"
        )


if __name__ == "__main__":
    main()
