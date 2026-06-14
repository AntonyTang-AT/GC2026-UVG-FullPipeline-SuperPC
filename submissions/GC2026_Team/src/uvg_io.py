"""Shared I/O helpers for UVG-CWI-DQPC data and colored point clouds."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import open3d as o3d

UVG_ROOT_NAME = "UVG-CWI-DQPC"
CG_REL = "consumer-grade_capture_system/CG/15fps"
HE_REL = "high-end_capture_system/HE/15fps"
RGBD_REL = "consumer-grade_capture_system/RGBD"

FRAME_RE = re.compile(r"_(\d{4})\.ply$", re.IGNORECASE)


@dataclass(frozen=True)
class FramePair:
    sequence: str
    frame_id: str
    cg_path: str
    he_path: Optional[str]


def parse_frame_id(ply_path: str) -> str:
    match = FRAME_RE.search(ply_path)
    if not match:
        raise ValueError(f"Cannot parse frame id from path: {ply_path}")
    return match.group(1)


def cg_to_he_path(cg_path: str) -> str:
    """Map CG ply path to paired HE ply path (different capture-system folders)."""
    if "_CG_" not in cg_path:
        raise ValueError(f"Not a CG path: {cg_path}")
    he_path = cg_path.replace("_CG_", "_HE_", 1)
    he_path = he_path.replace("consumer-grade_capture_system/CG/", "high-end_capture_system/HE/", 1)
    return he_path


def list_sequences(raw_root: str) -> List[str]:
    uvg_root = os.path.join(raw_root, UVG_ROOT_NAME)
    if not os.path.isdir(uvg_root):
        raise FileNotFoundError(f"UVG root not found: {uvg_root}")
    sequences = []
    for name in sorted(os.listdir(uvg_root)):
        path = os.path.join(uvg_root, name)
        if not os.path.isdir(path):
            continue
        cg_dir = os.path.join(path, CG_REL)
        if os.path.isdir(cg_dir):
            sequences.append(name)
    return sequences


def iter_frame_pairs(raw_root: str, sequences: Optional[List[str]] = None) -> List[FramePair]:
    uvg_root = os.path.join(raw_root, UVG_ROOT_NAME)
    seqs = sequences or list_sequences(raw_root)
    pairs: List[FramePair] = []
    for seq in seqs:
        cg_dir = os.path.join(uvg_root, seq, CG_REL)
        if not os.path.isdir(cg_dir):
            continue
        for fname in sorted(os.listdir(cg_dir)):
            if not fname.endswith(".ply"):
                continue
            cg_path = os.path.join(cg_dir, fname)
            he_path = cg_to_he_path(cg_path)
            if not os.path.isfile(he_path):
                he_path = None
            frame_id = parse_frame_id(cg_path)
            pairs.append(FramePair(sequence=seq, frame_id=frame_id, cg_path=cg_path, he_path=he_path))
    return pairs


def read_ply_xyz(path: str, max_points: int = 0, rng: Optional[np.random.RandomState] = None) -> np.ndarray:
    """Read XYZ from PLY (plyfile, faster than open3d for large clouds)."""
    from plyfile import PlyData

    ply = PlyData.read(path)
    vertex = ply["vertex"]
    xyz = np.column_stack(
        [vertex["x"], vertex["y"], vertex["z"]],
    ).astype(np.float32)
    if xyz.shape[0] == 0:
        raise ValueError(f"Empty point cloud: {path}")
    if max_points > 0 and xyz.shape[0] > max_points:
        if rng is None:
            rng = np.random.RandomState(0)
        idx = rng.choice(xyz.shape[0], size=max_points, replace=False)
        xyz = xyz[idx]
    return xyz


def read_ply_xyz_rgb(
    path: str,
    max_points: int = 0,
    rng: Optional[np.random.RandomState] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    pc = o3d.io.read_point_cloud(path)
    xyz = np.asarray(pc.points, dtype=np.float32)
    if xyz.shape[0] == 0:
        raise ValueError(f"Empty point cloud: {path}")
    colors = np.asarray(pc.colors, dtype=np.float32)
    if colors.shape[0] != xyz.shape[0]:
        colors = np.zeros((xyz.shape[0], 3), dtype=np.float32)
    if max_points > 0 and xyz.shape[0] > max_points:
        if rng is None:
            rng = np.random.RandomState(0)
        idx = rng.choice(xyz.shape[0], size=max_points, replace=False)
        xyz = xyz[idx]
        colors = colors[idx]
    return xyz, colors


def write_ply_xyz_rgb(path: str, xyz: np.ndarray, rgb: np.ndarray) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    pc = o3d.geometry.PointCloud()
    pc.points = o3d.utility.Vector3dVector(xyz.astype(np.float64))
    rgb_clipped = np.clip(rgb, 0.0, 1.0)
    pc.colors = o3d.utility.Vector3dVector(rgb_clipped.astype(np.float64))
    o3d.io.write_point_cloud(path, pc, write_ascii=False)


def merge_xyz_rgb_voxel(
    xyz_list: list[np.ndarray],
    rgb_list: list[np.ndarray],
    voxel_size: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Merge colored clouds; voxel_size in same units as coordinates (UVG uses mm)."""
    pc = o3d.geometry.PointCloud()
    for xyz, rgb in zip(xyz_list, rgb_list):
        if xyz.shape[0] == 0:
            continue
        part = o3d.geometry.PointCloud()
        part.points = o3d.utility.Vector3dVector(xyz.astype(np.float64))
        part.colors = o3d.utility.Vector3dVector(np.clip(rgb, 0.0, 1.0).astype(np.float64))
        pc += part
    if len(pc.points) == 0:
        raise ValueError("merge_xyz_rgb_voxel: empty input")
    if voxel_size > 0:
        pc = pc.voxel_down_sample(voxel_size)
    return np.asarray(pc.points, dtype=np.float32), np.asarray(pc.colors, dtype=np.float32)


def filter_cg_outliers(xyz: np.ndarray, rgb: np.ndarray, nb_neighbors: int = 20, std_ratio: float = 2.0) -> Tuple[np.ndarray, np.ndarray]:
    """Light statistical outlier removal on consumer-grade input."""
    pc = o3d.geometry.PointCloud()
    pc.points = o3d.utility.Vector3dVector(xyz.astype(np.float64))
    pc.colors = o3d.utility.Vector3dVector(np.clip(rgb, 0.0, 1.0).astype(np.float64))
    pc_clean, _ = pc.remove_statistical_outlier(nb_neighbors=nb_neighbors, std_ratio=std_ratio)
    return np.asarray(pc_clean.points, dtype=np.float32), np.asarray(pc_clean.colors, dtype=np.float32)


def rgbd_color_to_depth_path(color_path: str) -> Optional[str]:
    """Map RGBD color image to paired depth image."""
    if not color_path:
        return None
    color_dir = os.path.dirname(color_path)
    stem = os.path.splitext(os.path.basename(color_path))[0]
    parent = os.path.dirname(color_dir)
    for sub in ("depth", "depth_aligned", "aligned_depth"):
        for ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
            cand = os.path.join(parent, sub, stem + ext)
            if os.path.isfile(cand):
                return cand
            cand15 = os.path.join(parent, sub, "15fps", stem + ext)
            if os.path.isfile(cand15):
                return cand15
    for sub in ("depth", "depth_aligned", "aligned_depth"):
        dpath = os.path.join(parent, sub)
        if not os.path.isdir(dpath):
            continue
        for root, _, files in os.walk(dpath):
            for fname in files:
                if stem in fname and fname.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
                    return os.path.join(root, fname)
    return None


def find_rgbd_intrinsics(rgbd_root: str, stem: str = "") -> Optional[str]:
    search_roots = [rgbd_root, os.path.join(rgbd_root, "calibration"), os.path.join(rgbd_root, "calib")]
    names = [f"{stem}_intrinsics.json", "intrinsics.json", "camera_intrinsics.json"]
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for name in names:
            p = os.path.join(root, name)
            if os.path.isfile(p):
                return p
        for fname in os.listdir(root):
            if "intrinsic" in fname.lower() and fname.endswith((".json", ".npy", ".txt")):
                return os.path.join(root, fname)
    return None


def load_pinhole_intrinsics(path: Optional[str], width: int, height: int) -> tuple[float, float, float, float]:
    if path and os.path.isfile(path):
        if path.endswith(".json"):
            import json

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "fx" in data:
                return float(data["fx"]), float(data["fy"]), float(data["cx"]), float(data["cy"])
            if "intrinsic_matrix" in data:
                m = data["intrinsic_matrix"]
                return float(m[0]), float(m[4]), float(m[2]), float(m[5])
            if "color_intrinsics" in data:
                c = data["color_intrinsics"]
                return float(c["fx"]), float(c["fy"]), float(c["cx"]), float(c["cy"])
    fx = fy = 645.0 * (width / 1280.0)
    return fx, fy, width * 0.5, height * 0.5


def find_bag_files(seq_root: str) -> list[str]:
    bags: list[str] = []
    cg_root = os.path.join(seq_root, "consumer-grade_capture_system")
    if not os.path.isdir(cg_root):
        return bags
    for root, _, files in os.walk(cg_root):
        for fname in files:
            if fname.lower().endswith(".bag"):
                bags.append(os.path.join(root, fname))
    return sorted(bags)


def cg_to_rgbd_color_path(cg_path: str) -> Optional[str]:
    """Map CG ply to RGBD color frame when RGBD tree is installed."""
    if "_CG_" not in cg_path or "consumer-grade_capture_system/CG/" not in cg_path:
        return None
    seq_root = cg_path.split("consumer-grade_capture_system/CG/")[0]
    cg_dir = os.path.dirname(cg_path)
    frame_id = parse_frame_id(cg_path)
    ply_name = os.path.basename(cg_path)
    stem = ply_name.replace("_CG_", "_RGBD_").replace(".ply", "")

    search_dirs = [
        os.path.join(seq_root, "consumer-grade_capture_system", "RGBD", "color", "15fps"),
        os.path.join(seq_root, "consumer-grade_capture_system", "RGBD", "color"),
        os.path.join(seq_root, "consumer-grade_capture_system", "RGBD", "15fps"),
        os.path.join(seq_root, "consumer-grade_capture_system", "RGBD"),
        os.path.join(cg_dir.replace("/CG/", "/RGBD/"), "color"),
        cg_dir.replace("/CG/", "/RGBD/"),
    ]
    names = [stem, ply_name.replace("_CG_", "_RGBD_").replace(".ply", "")]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for name in names:
            for ext in (".png", ".jpg", ".jpeg"):
                candidate = os.path.join(d, name + ext)
                if os.path.isfile(candidate):
                    return candidate
        # frame index fallback
        for fname in os.listdir(d):
            if frame_id in fname and fname.lower().endswith((".png", ".jpg", ".jpeg")):
                return os.path.join(d, fname)
    return None


def transfer_colors_knn(
    src_xyz: np.ndarray,
    src_rgb: np.ndarray,
    dst_xyz: np.ndarray,
    k: int = 1,
) -> np.ndarray:
    """Assign colors to dst points from nearest src points (CPU, scipy-free)."""
    from sklearn.neighbors import NearestNeighbors

    if src_xyz.shape[0] == 0:
        return np.zeros((dst_xyz.shape[0], 3), dtype=np.float32)
    nn = NearestNeighbors(n_neighbors=min(k, src_xyz.shape[0]), algorithm="auto")
    nn.fit(src_xyz)
    _, indices = nn.kneighbors(dst_xyz, return_distance=True)
    if k == 1:
        return src_rgb[indices[:, 0]].astype(np.float32)
    weights = np.ones_like(indices, dtype=np.float32)
    gathered = src_rgb[indices]
    return (gathered * weights).sum(axis=1) / weights.sum(axis=1)
