#!/usr/bin/env python3
"""Synthetic unit test: rgbd_to_cg outputs millimeter coordinates."""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from rgbd_to_cg import reconstruct_frame_open3d  # noqa: E402


def main() -> None:
    w, h = 64, 48
    fx, fy, cx, cy = 500.0, 500.0, w / 2, h / 2
    z_m = 1.0
    depth_mm = int(z_m * 1000)

    color = np.zeros((h, w, 3), dtype=np.uint8)
    color[:, :, 0] = 200
    color[:, :, 1] = 100
    color[:, :, 2] = 50
    depth = np.full((h, w), depth_mm, dtype=np.uint16)

    intrinsics = {
        "width": w,
        "height": h,
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
    }

    with tempfile.TemporaryDirectory() as tmp:
        color_path = os.path.join(tmp, "color.png")
        depth_path = os.path.join(tmp, "depth.png")
        intr_path = os.path.join(tmp, "intrinsics.json")
        Image.fromarray(color).save(color_path)
        Image.fromarray(depth).save(depth_path)
        with open(intr_path, "w") as f:
            import json

            json.dump(intrinsics, f)

        xyz, rgb = reconstruct_frame_open3d(
            color_path,
            depth_path,
            intr_path,
            depth_scale=1000.0,
            depth_trunc_mm=5000.0,
            seq_root=tmp,
        )

    assert xyz.shape[0] > 100, f"too few points: {xyz.shape[0]}"
    z_mean = float(np.mean(xyz[:, 2]))
    z_abs = abs(z_mean)
    assert 800.0 < z_abs < 1200.0, f"z mean {z_mean} (abs {z_abs}) not ~1000 mm"
    assert z_abs > 100.0, "coordinates likely still in meters"

    print(f"[test_rgbd_to_cg_units] OK points={xyz.shape[0]} z_mean_mm={z_mean:.1f}")


if __name__ == "__main__":
    main()
