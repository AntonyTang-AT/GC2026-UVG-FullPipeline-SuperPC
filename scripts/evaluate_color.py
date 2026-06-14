#!/usr/bin/env python3
"""Evaluate color PSNR between enhanced PLY and HE reference (Y channel proxy)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
from evaluate_uvg import enh_path_from_cg  # noqa: E402
from uvg_io import cg_to_he_path, parse_frame_id  # noqa: E402


def rgb_to_y(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    return 0.299 * r + 0.587 * g + 0.114 * b


def read_ply_xyz_rgb_fast(path: str, max_points: int, rng: np.random.RandomState) -> tuple[np.ndarray, np.ndarray]:
    from plyfile import PlyData

    ply = PlyData.read(path)
    vertex = ply["vertex"]
    xyz = np.column_stack([vertex["x"], vertex["y"], vertex["z"]]).astype(np.float32)
    if "red" in vertex:
        rgb = np.column_stack([vertex["red"], vertex["green"], vertex["blue"]]).astype(np.float32) / 255.0
    else:
        rgb = np.zeros((xyz.shape[0], 3), dtype=np.float32)
    if max_points > 0 and xyz.shape[0] > max_points:
        idx = rng.choice(xyz.shape[0], max_points, replace=False)
        xyz, rgb = xyz[idx], rgb[idx]
    return xyz, rgb


def knn_transfer_colors(src_xyz: np.ndarray, src_rgb: np.ndarray, dst_xyz: np.ndarray, k: int = 1) -> np.ndarray:
    d = np.linalg.norm(dst_xyz[:, None, :] - src_xyz[None, :, :], axis=2)
    if k == 1:
        idx = d.argmin(axis=1)
        return src_rgb[idx]
    idx = np.argpartition(d, kth=min(k, d.shape[1] - 1), axis=1)[:, :k]
    weights = 1.0 / (d[:, :k] + 1e-8)
    weights /= weights.sum(axis=1, keepdims=True)
    return np.einsum("ij,ijk->ik", weights, src_rgb[idx])


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a - b) ** 2))
    if mse <= 1e-12:
        return 99.0
    return 10.0 * np.log10(255.0 ** 2 / mse)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pairs-file", default=os.path.join(GC2026_ROOT, "data/processed/val_pairs.txt"))
    p.add_argument("--enhanced-root", required=True)
    p.add_argument("--n-samples", type=int, default=2000, help="HE points for PSNR (keep small for speed)")
    p.add_argument("--max-load-points", type=int, default=10000)
    p.add_argument("--out-json", default=None)
    p.add_argument("--seed", type=int, default=21)
    args = p.parse_args()

    rng = np.random.RandomState(args.seed)
    with open(args.pairs_file, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]

    records = []
    psnr_vals = []

    for line in tqdm(lines, desc="color_psnr"):
        parts = line.split("\t")
        cg_path = parts[0]
        he_path = parts[1] if len(parts) > 1 and parts[1] else cg_to_he_path(cg_path)
        enh_path = enh_path_from_cg(cg_path, args.enhanced_root)
        if not os.path.isfile(he_path) or not os.path.isfile(enh_path):
            continue

        he_xyz, he_rgb = read_ply_xyz_rgb_fast(he_path, args.max_load_points, rng)
        enh_xyz, enh_rgb = read_ply_xyz_rgb_fast(enh_path, args.max_load_points, rng)

        n = min(args.n_samples, he_xyz.shape[0], enh_xyz.shape[0])
        he_idx = rng.choice(he_xyz.shape[0], n, replace=False)
        enh_idx = rng.choice(enh_xyz.shape[0], n, replace=False)

        he_y = rgb_to_y(he_rgb[he_idx])
        enh_on_he = knn_transfer_colors(enh_xyz, enh_rgb, he_xyz[he_idx])
        enh_y = rgb_to_y(enh_on_he)
        val = psnr(he_y, enh_y)
        psnr_vals.append(val)
        records.append({"frame_id": parse_frame_id(cg_path), "psnr_y": val, "enh_path": enh_path})

    summary = {
        "enhanced_root": args.enhanced_root,
        "num_evaluated": len(records),
        "mean_psnr_y": float(np.mean(psnr_vals)) if psnr_vals else None,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    out = args.out_json or os.path.join(args.enhanced_root, "color_evaluation.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
