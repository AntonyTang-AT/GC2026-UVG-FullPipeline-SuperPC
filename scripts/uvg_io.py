"""Shared I/O helpers for UVG-CWI-DQPC data and colored point clouds."""
from __future__ import annotations

import json
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
CGV2_MARKERS = ("v2-0", "_v2_", "CGv2")

# Open3D RealSense optical frame: flip Y and Z before UVG transform (meters).
OPEN3D_RGBD_FLIP_4X4 = np.array(
    [[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]],
    dtype=np.float64,
)


def is_cgv2_filename(fname: str) -> bool:
    low = fname.lower()
    if any(m in low for m in CGV2_MARKERS):
        return True
    # Official CGv2_15 install: Seq_UVG-CWI-DQPC_CG_15_0_<len>_<frame>.ply
    return "_cg_15_0_" in low


def default_cg_version() -> str:
    return os.environ.get("UVG_CG_VERSION", "v2").strip().lower()


def resolve_cg_dir(seq_root: str, version: Optional[str] = None) -> str:
    return os.path.join(seq_root, CG_REL)


def list_cg_ply_files(cg_dir: str, version: str = "v2") -> List[str]:
    if not os.path.isdir(cg_dir):
        return []
    version = version.lower()
    out: List[str] = []
    for fname in sorted(os.listdir(cg_dir)):
        if not fname.endswith(".ply"):
            continue
        is_v2 = is_cgv2_filename(fname)
        if version == "v2" and is_v2:
            out.append(fname)
        elif version == "v1" and not is_v2:
            out.append(fname)
        elif version == "all":
            out.append(fname)
    return out


def official_cg_path(
    raw_root: str,
    sequence: str,
    frame_id: str,
    version: Optional[str] = None,
) -> Optional[str]:
    version = (version or default_cg_version()).lower()
    cg_dir = os.path.join(raw_root, UVG_ROOT_NAME, sequence, CG_REL)
    if not os.path.isdir(cg_dir):
        return None
    for fname in list_cg_ply_files(cg_dir, version):
        if fname.endswith(f"_{frame_id}.ply"):
            return os.path.join(cg_dir, fname)
    for fname in list_cg_ply_files(cg_dir, version):
        if f"_{frame_id}.ply" in fname or fname.endswith(f"{frame_id}.ply"):
            return os.path.join(cg_dir, fname)
    return None


def find_transform_matrix(seq_root: str) -> Optional[str]:
    seq_name = os.path.basename(seq_root.rstrip("/"))
    candidates = [
        os.path.join(seq_root, f"{seq_name}_transform_matrix.json"),
        os.path.join(seq_root, "transform_matrix.json"),
    ]
    cg_sys = os.path.join(seq_root, "consumer-grade_capture_system")
    candidates.append(os.path.join(cg_sys, f"{seq_name}_transform_matrix.json"))
    for p in candidates:
        if os.path.isfile(p):
            return p
    for root, _, files in os.walk(seq_root):
        for fname in files:
            if "transform_matrix" in fname.lower() and fname.endswith(".json"):
                return os.path.join(root, fname)
    return None


def find_camera_config(seq_root: str) -> Optional[str]:
    seq_name = os.path.basename(seq_root.rstrip("/"))
    candidates = [
        os.path.join(seq_root, f"{seq_name}_camera_config.json"),
        os.path.join(seq_root, f"{seq_name}_cameraconfig.json"),
        os.path.join(seq_root, "camera_config.json"),
        os.path.join(seq_root, "cameraconfig.json"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    for root, _, files in os.walk(seq_root):
        for fname in files:
            low = fname.lower()
            if ("camera_config" in low or "cameraconfig" in low) and fname.endswith(".json"):
                return os.path.join(root, fname)
    return None


def load_transform_matrix(path: str) -> np.ndarray:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        mat = np.array(data, dtype=np.float64)
    elif isinstance(data, dict):
        for key in ("transform_matrix", "matrix", "transform", "4x4"):
            if key in data:
                mat = np.array(data[key], dtype=np.float64)
                break
        else:
            raise ValueError(f"No matrix field in {path}")
    else:
        raise ValueError(f"Unexpected transform JSON: {path}")
    if mat.shape == (16,):
        mat = mat.reshape(4, 4)
    if mat.shape != (4, 4):
        raise ValueError(f"Expected 4x4 matrix in {path}, got {mat.shape}")
    return mat


def apply_transform_xyz(xyz: np.ndarray, matrix: np.ndarray, row_vector: bool = True) -> np.ndarray:
    """Apply 4x4 rigid transform. Default: row vectors, p' = p @ R.T + t."""
    mat = np.asarray(matrix, dtype=np.float64)
    if mat.shape != (4, 4):
        raise ValueError(f"matrix must be 4x4, got {mat.shape}")
    pts = np.asarray(xyz, dtype=np.float64)
    if row_vector:
        rot = mat[:3, :3]
        trans = mat[:3, 3]
        return (pts @ rot.T + trans).astype(np.float32)
    ones = np.ones((pts.shape[0], 1), dtype=np.float64)
    hom = np.hstack([pts, ones])
    out = (mat @ hom.T).T[:, :3]
    return out.astype(np.float32)


def apply_transform_to_ply(in_path: str, out_path: str, matrix: np.ndarray) -> None:
    xyz, rgb = read_ply_xyz_rgb(in_path)
    xyz_t = apply_transform_xyz(xyz, matrix)
    write_ply_xyz_rgb(out_path, xyz_t, rgb)


def open3d_optical_flip_matrix_mm() -> np.ndarray:
    """4x4: flip Y/Z in meters then scale to mm in homogeneous coords."""
    flip_m = OPEN3D_RGBD_FLIP_4X4.copy()
    scale = np.diag([1000.0, 1000.0, 1000.0, 1.0])
    return scale @ flip_m


def apply_uvg_pipeline_transform(xyz_mm: np.ndarray, seq_root: str) -> np.ndarray:
    """Apply optional sequence transform_matrix after Open3D optical-frame output (mm)."""
    tpath = find_transform_matrix(seq_root)
    if tpath:
        mat = load_transform_matrix(tpath)
        return apply_transform_xyz(xyz_mm, mat)
    return xyz_mm


def load_camera_config_entries(seq_root: str) -> list[dict]:
    """Return camera entries from sequence camera_config.json."""
    path = find_camera_config(seq_root)
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "camera" in data:
        return list(data["camera"])
    if isinstance(data, list):
        return data
    return []


def load_camera_trafo(seq_root: str, camera_index: int = 0) -> Optional[np.ndarray]:
    entries = load_camera_config_entries(seq_root)
    if not entries or camera_index >= len(entries):
        return None
    trafo = entries[camera_index].get("trafo")
    if trafo is None:
        return None
    mat = np.array(trafo, dtype=np.float64)
    if mat.shape == (16,):
        mat = mat.reshape(4, 4)
    return mat if mat.shape == (4, 4) else None


def apply_open3d_optical_flip_m(xyz_m: np.ndarray) -> np.ndarray:
    """Flip Y/Z in meter space (Open3D optical -> standard camera frame)."""
    return apply_transform_xyz(xyz_m, OPEN3D_RGBD_FLIP_4X4)


def compose_open3d_camera_to_world_m(
    seq_root: str,
    transform_mode: str = "seq_only",
    camera_index: int = 0,
) -> np.ndarray:
    """4x4: Open3D camera frame (m) -> world (m). Matches apply_open3d_transform_chain."""
    mode = transform_mode.strip().lower()
    flip = OPEN3D_RGBD_FLIP_4X4.astype(np.float64)
    chain = flip.copy()

    if mode in ("legacy", "t0", "default"):
        return chain

    if mode in ("t4", "camera_only"):
        cam = load_camera_trafo(seq_root, camera_index)
        if cam is not None:
            chain = cam.astype(np.float64) @ chain
        return chain

    if mode in ("t5", "seq_only"):
        tpath = find_transform_matrix(seq_root)
        if tpath:
            chain = load_transform_matrix(tpath).astype(np.float64) @ chain
        return chain

    if mode in ("cwipc_coords", "cwipc_style"):
        cam = load_camera_trafo(seq_root, camera_index)
        if cam is not None:
            chain = cam.astype(np.float64) @ chain
        tpath = find_transform_matrix(seq_root)
        if tpath:
            chain = load_transform_matrix(tpath).astype(np.float64) @ chain
        return chain

    cam = load_camera_trafo(seq_root, camera_index)
    if cam is not None:
        chain = cam.astype(np.float64) @ chain
    tpath = find_transform_matrix(seq_root)
    if tpath:
        chain = load_transform_matrix(tpath).astype(np.float64) @ chain
    return chain


def transform_matrix_translation_is_mm(matrix: np.ndarray) -> bool:
    """Heuristic: UVG seq transform t in mm if max|t|>10 (meters otherwise). TT is ~0.2m; others ~80-370mm."""
    mat = np.asarray(matrix, dtype=np.float64)
    if mat.shape == (16,):
        mat = mat.reshape(4, 4)
    return float(np.max(np.abs(mat[:3, 3]))) > 10.0


def apply_open3d_transform_chain(
    xyz_m: np.ndarray,
    seq_root: str,
    transform_mode: str = "chain_meters",
    camera_index: int = 0,
) -> np.ndarray:
    """Apply coordinate chain; input/output in mm for UVG PLY."""
    mode = transform_mode.strip().lower()
    pts_m = np.asarray(xyz_m, dtype=np.float64)

    if mode in ("legacy", "t0", "default"):
        pts_m = apply_open3d_optical_flip_m(pts_m)
        xyz_mm = (pts_m * 1000.0).astype(np.float32)
        return apply_uvg_pipeline_transform(xyz_mm, seq_root)

    if mode in ("t3", "flip_mm_homogeneous"):
        pts_m = apply_open3d_optical_flip_m(pts_m)
        hom = np.hstack([pts_m, np.ones((pts_m.shape[0], 1), dtype=np.float64)])
        out = (open3d_optical_flip_matrix_mm() @ hom.T).T[:, :3]
        return out.astype(np.float32)

    pts_m = apply_open3d_optical_flip_m(pts_m)

    if mode in ("t4", "camera_only"):
        cam = load_camera_trafo(seq_root, camera_index)
        if cam is not None:
            pts_m = apply_transform_xyz(pts_m.astype(np.float32), cam).astype(np.float64)
        return (pts_m * 1000.0).astype(np.float32)

    if mode in ("t5", "seq_only"):
        tpath = find_transform_matrix(seq_root)
        if tpath:
            mat = load_transform_matrix(tpath)
            if transform_matrix_translation_is_mm(mat):
                xyz_mm = apply_transform_xyz((pts_m * 1000.0).astype(np.float32), mat)
                return xyz_mm
            pts_m = apply_transform_xyz(pts_m.astype(np.float32), mat).astype(np.float64)
        return (pts_m * 1000.0).astype(np.float32)

    if mode in ("seq_only_auto", "seq_auto"):
        tpath = find_transform_matrix(seq_root)
        if tpath:
            mat = load_transform_matrix(tpath)
            if transform_matrix_translation_is_mm(mat):
                return apply_transform_xyz((pts_m * 1000.0).astype(np.float32), mat)
            pts_m = apply_transform_xyz(pts_m.astype(np.float32), mat).astype(np.float64)
        return (pts_m * 1000.0).astype(np.float32)

    # cwipc-style: optical flip -> per-camera trafo (m) -> seq transform -> mm
    if mode in ("cwipc_coords", "cwipc_style"):
        cam = load_camera_trafo(seq_root, camera_index)
        if cam is not None:
            pts_m = apply_transform_xyz(pts_m.astype(np.float32), cam).astype(np.float64)
        tpath = find_transform_matrix(seq_root)
        if tpath:
            mat = load_transform_matrix(tpath)
            if transform_matrix_translation_is_mm(mat):
                xyz_mm = apply_transform_xyz((pts_m * 1000.0).astype(np.float32), mat)
                return xyz_mm
            pts_m = apply_transform_xyz(pts_m.astype(np.float32), mat).astype(np.float64)
        return (pts_m * 1000.0).astype(np.float32)

    # T1 / chain_meters (default fix): camera trafo -> sequence transform -> mm
    cam = load_camera_trafo(seq_root, camera_index)
    if cam is not None:
        pts_m = apply_transform_xyz(pts_m.astype(np.float32), cam).astype(np.float64)

    if mode in ("t2", "chain_mm_translate"):
        tpath = find_transform_matrix(seq_root)
        if tpath:
            mat = load_transform_matrix(tpath).copy()
            mat[:3, 3] *= 1000.0
            xyz_mm = apply_transform_xyz((pts_m * 1000.0).astype(np.float32), mat)
            return xyz_mm

    tpath = find_transform_matrix(seq_root)
    if tpath:
        pts_m = apply_transform_xyz(pts_m.astype(np.float32), load_transform_matrix(tpath)).astype(np.float64)

    return (pts_m * 1000.0).astype(np.float32)


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


def list_sequences(raw_root: str, cg_version: Optional[str] = None) -> List[str]:
    uvg_root = os.path.join(raw_root, UVG_ROOT_NAME)
    if not os.path.isdir(uvg_root):
        raise FileNotFoundError(f"UVG root not found: {uvg_root}")
    version = cg_version or default_cg_version()
    sequences = []
    for name in sorted(os.listdir(uvg_root)):
        path = os.path.join(uvg_root, name)
        if not os.path.isdir(path):
            continue
        cg_dir = os.path.join(path, CG_REL)
        if not os.path.isdir(cg_dir):
            continue
        if list_cg_ply_files(cg_dir, version):
            sequences.append(name)
    return sequences


def iter_frame_pairs(
    raw_root: str,
    sequences: Optional[List[str]] = None,
    cg_version: Optional[str] = None,
) -> List[FramePair]:
    uvg_root = os.path.join(raw_root, UVG_ROOT_NAME)
    version = cg_version or default_cg_version()
    seqs = sequences or list_sequences(raw_root, cg_version=version)
    pairs: List[FramePair] = []
    for seq in seqs:
        cg_dir = os.path.join(uvg_root, seq, CG_REL)
        if not os.path.isdir(cg_dir):
            continue
        for fname in list_cg_ply_files(cg_dir, version):
            cg_path = os.path.join(cg_dir, fname)
            he_path = cg_to_he_path(cg_path)
            if not os.path.isfile(he_path):
                he_path = None
            frame_id = parse_frame_id(cg_path)
            pairs.append(FramePair(sequence=seq, frame_id=frame_id, cg_path=cg_path, he_path=he_path))
    return pairs


def _ply_prop_size(typ: str) -> int:
    return {
        "char": 1, "uchar": 1, "int8": 1, "uint8": 1,
        "short": 2, "ushort": 2, "int16": 2, "uint16": 2,
        "int": 4, "uint": 4, "int32": 4, "uint32": 4,
        "float": 4, "double": 8,
    }.get(typ, 0)


def _parse_ply_vertex_layout(path: str) -> tuple[int, int, int, list[tuple[str, str]]]:
    """Return vertex count, header end byte offset, stride, and (type, name) properties."""
    n_verts = 0
    fmt = None
    props: list[tuple[str, str]] = []
    header_end = 0
    with open(path, "rb") as f:
        first = f.readline().decode("ascii", errors="ignore").strip()
        if first != "ply":
            raise ValueError(f"Not a PLY file: {path}")
        while True:
            line = f.readline().decode("ascii", errors="ignore").strip()
            if line.startswith("format "):
                fmt = line.split()[1]
            elif line.startswith("element vertex "):
                n_verts = int(line.split()[2])
            elif line.startswith("property "):
                parts = line.split()
                if len(parts) >= 3:
                    props.append((parts[1], parts[2]))
            elif line == "end_header":
                header_end = f.tell()
                break
    if fmt != "binary_little_endian" or n_verts <= 0 or not props:
        return 0, 0, 0, []
    stride = sum(_ply_prop_size(t) for t, _ in props)
    if stride <= 0 or not all(n in {p[1] for p in props} for n in ("x", "y", "z")):
        return 0, 0, 0, []
    return n_verts, header_end, stride, props


def _read_ply_xyz_sampled(
    path: str,
    header_end: int,
    stride: int,
    props: list[tuple[str, str]],
    n_verts: int,
    max_points: int,
    rng: np.random.RandomState,
) -> np.ndarray:
    import struct

    offsets: dict[str, int] = {}
    off = 0
    type_by_name = {name: typ for typ, name in props}
    for typ, name in props:
        offsets[name] = off
        off += _ply_prop_size(typ)

    def read_xyz(row: bytes) -> tuple[float, float, float]:
        vals = []
        for axis in ("x", "y", "z"):
            typ = type_by_name[axis]
            if typ == "double":
                vals.append(struct.unpack_from("<d", row, offsets[axis])[0])
            elif typ == "float":
                vals.append(struct.unpack_from("<f", row, offsets[axis])[0])
            else:
                raise ValueError(f"Unsupported PLY axis type: {typ}")
        return vals[0], vals[1], vals[2]

    sample_n = min(max_points, n_verts)
    idx = rng.choice(n_verts, size=sample_n, replace=False)
    xyz = np.empty((sample_n, 3), dtype=np.float32)
    with open(path, "rb") as f:
        for i, vi in enumerate(idx):
            f.seek(header_end + int(vi) * stride)
            row = f.read(stride)
            x, y, z = read_xyz(row)
            xyz[i] = (x, y, z)
    return xyz


def read_ply_xyz(path: str, max_points: int = 0, rng: Optional[np.random.RandomState] = None) -> np.ndarray:
    """Read XYZ from PLY; subsample without loading the full cloud when max_points is set."""
    if rng is None:
        rng = np.random.RandomState(0)
    n_verts, header_end, stride, props = _parse_ply_vertex_layout(path)
    if n_verts > 0 and max_points > 0:
        return _read_ply_xyz_sampled(path, header_end, stride, props, n_verts, max_points, rng)

    from plyfile import PlyData

    ply = PlyData.read(path)
    vertex = ply["vertex"]
    xyz = np.column_stack(
        [vertex["x"], vertex["y"], vertex["z"]],
    ).astype(np.float32)
    if xyz.shape[0] == 0:
        raise ValueError(f"Empty point cloud: {path}")
    if max_points > 0 and xyz.shape[0] > max_points:
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
    rgbd_root = os.path.dirname(parent) if os.path.basename(parent) in ("color", "15fps") else parent
    if os.path.basename(parent) == "color":
        rgbd_root = os.path.dirname(parent)
    candidates = []
    for sub in ("depth", "depth_aligned", "aligned_depth"):
        candidates.extend(
            [
                os.path.join(parent, sub, stem + ext)
                for ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff")
            ]
        )
        candidates.extend(
            [
                os.path.join(parent, sub, "15fps", stem + ext)
                for ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff")
            ]
        )
        if os.path.basename(parent) == "color":
            candidates.extend(
                [
                    os.path.join(rgbd_root, sub, "15fps", stem + ext)
                    for ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff")
                ]
            )
            candidates.extend(
                [
                    os.path.join(rgbd_root, sub, stem + ext)
                    for ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff")
                ]
            )
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    for sub in ("depth", "depth_aligned", "aligned_depth"):
        dpath = os.path.join(parent, sub)
        if not os.path.isdir(dpath):
            dpath = os.path.join(rgbd_root, sub)
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
