#!/usr/bin/env python3
"""Coordinate correction: estimate rigid ΔT from HE (dev) and apply to recon point clouds."""
from __future__ import annotations

import json
import os
from typing import Optional

import numpy as np
import open3d as o3d

from uvg_io import read_ply_xyz  # noqa: E402


def apply_o3d_transform(xyz: np.ndarray, T_col: np.ndarray) -> np.ndarray:
    """Apply Open3D column-vector 4x4 rigid transform."""
    pc = o3d.geometry.PointCloud()
    pc.points = o3d.utility.Vector3dVector(xyz.astype(np.float64))
    pc.transform(T_col.astype(np.float64))
    return np.asarray(pc.points, dtype=np.float32)


def icp_rigid_transform(
    source: np.ndarray,
    target: np.ndarray,
    max_corr: float = 500.0,
    max_points: int = 50000,
) -> tuple[np.ndarray, dict]:
    """ICP source→target; returns Open3D column 4x4."""
    rng = np.random.RandomState(21)
    src_pts = source
    tgt_pts = target
    if src_pts.shape[0] > max_points:
        idx = rng.choice(src_pts.shape[0], max_points, replace=False)
        src_pts = src_pts[idx]
    if tgt_pts.shape[0] > max_points:
        idx = rng.choice(tgt_pts.shape[0], max_points, replace=False)
        tgt_pts = tgt_pts[idx]

    src_pcd = o3d.geometry.PointCloud()
    src_pcd.points = o3d.utility.Vector3dVector(src_pts.astype(np.float64))
    tgt_pcd = o3d.geometry.PointCloud()
    tgt_pcd.points = o3d.utility.Vector3dVector(tgt_pts.astype(np.float64))

    reg = o3d.pipelines.registration.registration_icp(
        src_pcd,
        tgt_pcd,
        max_correspondence_distance=max_corr,
        init=np.eye(4),
        estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPoint(),
    )
    T = reg.transformation.astype(np.float64)
    return T, {"fitness": float(reg.fitness), "inlier_rmse": float(reg.inlier_rmse)}


def centroid_translation(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    delta = target.mean(axis=0) - source.mean(axis=0)
    T = np.eye(4, dtype=np.float64)
    T[:3, 3] = delta.astype(np.float64)
    return T


def average_rigid_transforms(transforms: list[np.ndarray]) -> np.ndarray:
    if not transforms:
        return np.eye(4, dtype=np.float64)
    if len(transforms) == 1:
        return transforms[0].astype(np.float64)
    trans = np.median([T[:3, 3] for T in transforms], axis=0)
    dists = [np.linalg.norm(T[:3, 3] - trans) for T in transforms]
    best = transforms[int(np.argmin(dists))]
    out = np.eye(4, dtype=np.float64)
    out[:3, :3] = best[:3, :3]
    out[:3, 3] = trans
    return out


def recon_to_he_path(recon_path: str) -> Optional[str]:
    if "_CG_" not in recon_path:
        return None
    he = recon_path.replace("_CG_", "_HE_", 1).replace(
        "consumer-grade_capture_system/CG/", "high-end_capture_system/HE/", 1
    )
    return he if os.path.isfile(he) else None


def load_coord_corrections(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("sequences", data)


def get_sequence_correction(seq: str, corrections: dict) -> Optional[np.ndarray]:
    entry = corrections.get(seq)
    if not entry:
        return None
    mat = entry.get("matrix") or entry.get("delta_T")
    if mat is None:
        return None
    arr = np.array(mat, dtype=np.float64)
    if arr.shape == (16,):
        arr = arr.reshape(4, 4)
    return arr if arr.shape == (4, 4) else None


def apply_coord_correction(xyz: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return apply_o3d_transform(xyz, matrix)


def estimate_sequence_correction_from_he(
    recon_he_pairs: list[tuple[str, str]],
    method: str = "icp",
    max_corr: float = 500.0,
) -> dict:
    """Estimate ΔT from (recon_path, he_path) pairs (development only)."""
    transforms: list[np.ndarray] = []
    metas: list[dict] = []
    for recon_path, he_path in recon_he_pairs:
        if not he_path or not os.path.isfile(he_path) or not os.path.isfile(recon_path):
            continue
        rng = np.random.RandomState(21)
        recon = read_ply_xyz(recon_path, max_points=80000, rng=rng)
        he = read_ply_xyz(he_path, max_points=80000, rng=rng)
        if method == "centroid":
            T = centroid_translation(recon, he)
            meta = {"method": "centroid"}
        else:
            T, meta = icp_rigid_transform(recon, he, max_corr=max_corr)
            meta["method"] = "icp"
        transforms.append(T)
        metas.append({"recon": recon_path, "he": he_path, **meta})

    if not transforms:
        return {"error": "no_valid_pairs", "n_frames": 0}

    T_avg = average_rigid_transforms(transforms)
    return {
        "n_frames": len(transforms),
        "method": method,
        "matrix": T_avg.tolist(),
        "translation_mm": [float(x) for x in T_avg[:3, 3]],
        "per_frame": metas,
    }
