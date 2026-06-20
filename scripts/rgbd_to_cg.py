#!/usr/bin/env python3
"""Full Pipeline stage 1: RGBD/bag -> consumer-grade CG PLY (cwipc primary, Open3D fallback)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from typing import Optional

import numpy as np
from PIL import Image
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from uvg_frame_map import cg_frame_id_to_playback_index  # noqa: E402
from uvg_io import (  # noqa: E402
    apply_open3d_transform_chain,
    apply_transform_xyz,
    cg_to_rgbd_color_path,
    compose_open3d_camera_to_world_m,
    find_bag_files,
    find_camera_config,
    find_rgbd_intrinsics,
    find_transform_matrix,
    load_camera_config_entries,
    load_pinhole_intrinsics,
    load_transform_matrix,
    merge_xyz_rgb_voxel,
    parse_frame_id,
    read_ply_xyz_rgb,
    rgbd_color_to_depth_path,
    write_ply_xyz_rgb,
)


def read_depth_array(path: str) -> np.ndarray:
    img = Image.open(path)
    arr = np.asarray(img)
    if arr.ndim == 3:
        arr = arr[:, :, 0]
    return arr.astype(np.float32)


def reconstruct_rgbd_open3d_raw(
    color_path: str,
    depth_path: str,
    intrinsics_path: Optional[str],
    depth_scale: float,
    depth_trunc_mm: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Open3D RGBD -> points in camera optical frame (meters), colors 0-1."""
    import open3d as o3d

    color = o3d.io.read_image(color_path)
    depth = o3d.io.read_image(depth_path)
    color_arr = np.asarray(color)
    h, w = color_arr.shape[0], color_arr.shape[1]
    fx, fy, cx, cy = load_pinhole_intrinsics(intrinsics_path, w, h)
    intrinsic = o3d.camera.PinholeCameraIntrinsic(int(w), int(h), fx, fy, cx, cy)
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
    xyz_m = np.asarray(pcd.points, dtype=np.float32)
    rgb = np.asarray(pcd.colors, dtype=np.float32)
    return xyz_m, rgb


def reconstruct_frame_open3d(
    color_path: str,
    depth_path: str,
    intrinsics_path: Optional[str],
    depth_scale: float,
    depth_trunc_mm: float,
    seq_root: str,
    transform_mode: str = "legacy",
    camera_index: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    xyz_m, rgb = reconstruct_rgbd_open3d_raw(
        color_path, depth_path, intrinsics_path, depth_scale, depth_trunc_mm,
    )
    xyz_mm = apply_open3d_transform_chain(
        xyz_m, seq_root, transform_mode=transform_mode, camera_index=camera_index,
    )
    return xyz_mm, rgb


def reconstruct_multicam_from_bags(
    seq_root: str,
    playback_index: int,
    depth_scale: float,
    depth_trunc_mm: float,
    transform_mode: str,
    merge_voxel_mm: float = 3.0,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Reconstruct one frame from all bags; fuse with voxel downsample (mm)."""
    from export_rosbag_rgbd import image_bytes_to_array, parse_ros1_image, read_topic_frames

    bags = find_bag_files(seq_root)
    if not bags:
        return None
    entries = load_camera_config_entries(seq_root)
    xyz_list: list[np.ndarray] = []
    rgb_list: list[np.ndarray] = []
    rgbd_root = os.path.join(seq_root, "consumer-grade_capture_system", "RGBD")
    intrinsics = find_rgbd_intrinsics(rgbd_root)

    for cam_idx, bag in enumerate(bags):
        needed = {playback_index}
        try:
            colors = read_topic_frames(bag, "Color_0/image/data", playback_index, needed)
            depths = read_topic_frames(bag, "Depth_0/image/data", playback_index, needed)
        except Exception as exc:
            print(f"[WARN] bag read failed {bag}: {exc}")
            continue
        if playback_index not in colors or playback_index not in depths:
            continue
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            color_path = os.path.join(tmp, "color.png")
            depth_path = os.path.join(tmp, "depth.png")
            Image.fromarray(colors[playback_index]).save(color_path)
            Image.fromarray(depths[playback_index]).save(depth_path)
            try:
                xyz_m, rgb = reconstruct_rgbd_open3d_raw(
                    color_path, depth_path, intrinsics, depth_scale, depth_trunc_mm,
                )
            except Exception:
                continue
        if xyz_m.shape[0] < 50:
            continue
        xyz_mm = apply_open3d_transform_chain(
            xyz_m, seq_root, transform_mode=transform_mode, camera_index=cam_idx,
        )
        xyz_list.append(xyz_mm)
        rgb_list.append(rgb)

    if not xyz_list:
        return None
    if len(xyz_list) == 1:
        return xyz_list[0], rgb_list[0]
    return merge_xyz_rgb_voxel(xyz_list, rgb_list, voxel_size=float(merge_voxel_mm))


def reconstruct_multicam_tsdf_from_bags(
    seq_root: str,
    playback_index: int,
    depth_scale: float,
    depth_trunc_mm: float,
    transform_mode: str,
    tsdf_voxel_mm: float = 3.0,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Fuse 8-camera RGBD with Open3D ScalableTSDFVolume; output in mm."""
    import open3d as o3d
    from export_rosbag_rgbd import read_topic_frames

    bags = find_bag_files(seq_root)
    if not bags:
        return None
    rgbd_root = os.path.join(seq_root, "consumer-grade_capture_system", "RGBD")
    intrinsics_path = find_rgbd_intrinsics(rgbd_root)
    depth_trunc_m = float(depth_trunc_mm) / 1000.0
    voxel_m = max(float(tsdf_voxel_mm) / 1000.0, 0.001)
    volume = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=voxel_m,
        sdf_trunc=4.0 * voxel_m,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8,
    )
    integrated = 0

    for cam_idx, bag in enumerate(bags):
        needed = {playback_index}
        try:
            colors = read_topic_frames(bag, "Color_0/image/data", playback_index, needed)
            depths = read_topic_frames(bag, "Depth_0/image/data", playback_index, needed)
        except Exception as exc:
            print(f"[WARN] tsdf bag read failed {bag}: {exc}")
            continue
        if playback_index not in colors or playback_index not in depths:
            continue
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            color_path = os.path.join(tmp, "color.png")
            depth_path = os.path.join(tmp, "depth.png")
            Image.fromarray(colors[playback_index]).save(color_path)
            Image.fromarray(depths[playback_index]).save(depth_path)
            color = o3d.io.read_image(color_path)
            depth = o3d.io.read_image(depth_path)
            color_arr = np.asarray(color)
            h, w = color_arr.shape[0], color_arr.shape[1]
            fx, fy, cx, cy = load_pinhole_intrinsics(intrinsics_path, w, h)
            intrinsic = o3d.camera.PinholeCameraIntrinsic(int(w), int(h), fx, fy, cx, cy)
            rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                color,
                depth,
                depth_scale=float(depth_scale),
                depth_trunc=depth_trunc_m,
                convert_rgb_to_intensity=False,
            )
            c2w = compose_open3d_camera_to_world_m(seq_root, transform_mode, cam_idx)
            w2c = np.linalg.inv(c2w)
            volume.integrate(rgbd, intrinsic, w2c.astype(np.float64))
            integrated += 1

    if integrated == 0:
        return None
    pcd = volume.extract_point_cloud()
    if len(pcd.points) < 50:
        return None
    xyz_mm = (np.asarray(pcd.points, dtype=np.float32) * 1000.0)
    rgb = np.asarray(pcd.colors, dtype=np.float32)
    return xyz_mm, rgb


CWIPC_PLAYBACK_RELAXED = ".cwipc_playback_relaxed.json"
CWIPC_MIN_POINTS = 1000


def resolve_cwipc_binary() -> str:
    for candidate in (
        os.environ.get("CWIPC_BIN"),
        shutil.which("cwipc"),
        "/root/miniconda3/bin/cwipc",
    ):
        if candidate and os.path.isfile(candidate):
            return candidate
    return "cwipc"


def relax_cwipc_playback_config(cfg: dict) -> dict:
    """UVG height/radius filters strip almost all points during offline bag playback."""
    import copy

    c = copy.deepcopy(cfg)
    flt = c.setdefault("filtering", {})
    flt["do_threshold"] = False
    flt["do_spatial"] = False
    proc = c.setdefault("processing", {})
    proc["height_min"] = 0.0
    proc["height_max"] = 10.0
    proc["radius_filter"] = 0.0
    proc["depth_x_erosion"] = 0
    proc["depth_y_erosion"] = 0
    return c


def ensure_cwipc_playback_config(
    seq_root: str,
    camera_config_src: Optional[str] = None,
    profile: str = "relaxed",
) -> Optional[str]:
    """Write playback config next to camera config (required by cwipc path resolution)."""
    src = camera_config_src or find_camera_config(seq_root)
    if not src:
        return None
    cam_dir = os.path.dirname(os.path.abspath(src))
    dst = os.path.join(cam_dir, CWIPC_PLAYBACK_RELAXED)
    with open(src, encoding="utf-8") as f:
        cfg = json.load(f)
    from cwipc_filter_profiles import apply_profile

    playback_cfg = apply_profile(cfg, profile)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(playback_cfg, f, indent=2)
    return dst


def describe_cwipc_playback_api(config_path: str, playback_index: int) -> str:
    return (
        f"python3.12 -c \"from cwipc.realsense2 import cwipc_realsense2_playback; "
        f"cap=cwipc_realsense2_playback({config_path!r}); "
        f"# skip to 30fps index {playback_index}\""
    )


def cwipc_pc_to_xyz_rgb(pc, seq_root: str) -> tuple[np.ndarray, np.ndarray]:
    mat = pc.get_numpy_matrix(onlyGeometry=False)
    xyz_mm = (mat[:, :3].astype(np.float32) * 1000.0)
    rgb = (mat[:, 3:6] / 255.0).astype(np.float32)
    tpath = find_transform_matrix(seq_root)
    if tpath:
        xyz_mm = apply_transform_xyz(xyz_mm, load_transform_matrix(tpath))
    return xyz_mm, rgb


def grab_cwipc_playback_frame(
    config_path: str,
    playback_index: int,
    min_points: int = CWIPC_MIN_POINTS,
):
    from cwipc import realsense2

    cap = realsense2.cwipc_realsense2_playback(config_path)
    try:
        good = -1
        for _ in range(playback_index + 24):
            if not cap.available(True):
                continue
            pc = cap.get()
            if pc is None:
                continue
            if pc.count() < min_points:
                pc.free()
                continue
            good += 1
            if good == playback_index:
                return pc
            pc.free()
    finally:
        cap.free()
    return None


class CwipcSequenceStreamer:
    """Reuse one 8-camera playback session; advance sequentially (O(frames) not O(frames^2))."""

    def __init__(self, config_path: str, seq_root: str, min_points: int = CWIPC_MIN_POINTS):
        from cwipc import realsense2

        self.config_path = config_path
        self.seq_root = seq_root
        self.min_points = min_points
        self._cap = realsense2.cwipc_realsense2_playback(config_path)
        self._good_index = -1

    def close(self) -> None:
        if self._cap is not None:
            self._cap.free()
            self._cap = None

    def __del__(self) -> None:
        self.close()

    def _advance(self):
        for _ in range(48):
            if not self._cap.available(True):
                continue
            pc = self._cap.get()
            if pc is None:
                continue
            if pc.count() < self.min_points:
                pc.free()
                continue
            self._good_index += 1
            return pc
        return None

    def grab(self, playback_index: int) -> Optional[tuple[np.ndarray, np.ndarray]]:
        if playback_index < self._good_index:
            raise ValueError(
                f"cwipc stream out of order: need index {playback_index}, already at {self._good_index}"
            )
        while self._good_index < playback_index:
            pc = self._advance()
            if pc is None:
                return None
            pc.free()
        pc = self._advance()
        if pc is None:
            return None
        try:
            return cwipc_pc_to_xyz_rgb(pc, self.seq_root)
        finally:
            pc.free()


def reconstruct_frame_cwipc(
    seq_root: str,
    playback_index: int,
    tmp_dir: str,
    dry_run: bool = False,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    bags = find_bag_files(seq_root)
    if not bags:
        return None
    cfg = ensure_cwipc_playback_config(seq_root)
    if not cfg:
        return None
    if dry_run:
        print("[dry-run]", describe_cwipc_playback_api(cfg, playback_index))
        return None
    try:
        pc = grab_cwipc_playback_frame(cfg, playback_index)
        if pc is None:
            return None
        result = cwipc_pc_to_xyz_rgb(pc, seq_root)
        pc.free()
        return result
    except Exception as exc:
        print(f"[WARN] cwipc playback failed: {exc}")
        return None


def try_open3d_path(
    cg_path: str,
    seq_root: str,
    depth_scale: float,
    depth_trunc_mm: float,
    transform_mode: str,
    camera_index: int,
    multi_camera: bool,
    merge_voxel_mm: float,
    playback_index: int,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    if multi_camera:
        return reconstruct_multicam_from_bags(
            seq_root,
            playback_index,
            depth_scale,
            depth_trunc_mm,
            transform_mode,
            merge_voxel_mm=merge_voxel_mm,
        )

    rgbd_root = os.path.join(seq_root, "consumer-grade_capture_system", "RGBD")
    color_path = cg_to_rgbd_color_path(cg_path)
    if not color_path or not os.path.isfile(color_path):
        return None
    depth_path = rgbd_color_to_depth_path(color_path)
    if not depth_path or not os.path.isfile(depth_path):
        return None
    stem = os.path.splitext(os.path.basename(color_path))[0]
    intrinsics = find_rgbd_intrinsics(rgbd_root, stem)
    return reconstruct_frame_open3d(
        color_path,
        depth_path,
        intrinsics,
        depth_scale,
        depth_trunc_mm,
        seq_root,
        transform_mode=transform_mode,
        camera_index=camera_index,
    )


def load_stage1_params(seq: str, config_path: Optional[str] = None) -> dict:
    """Per-sequence Stage1 params from stage1_config.json."""
    defaults = {
        "backend": os.environ.get("RGBD_TO_CG_BACKEND", "open3d"),
        "transform_mode": os.environ.get("RGBD_TRANSFORM_MODE", "legacy"),
        "depth_scale": float(os.environ.get("RGBD_DEPTH_SCALE", "1000")),
        "frame_map_mode": "even",
        "multi_camera": False,
        "merge_voxel_mm": 3.0,
        "cwipc_filter_profile": os.environ.get("CWIPC_FILTER_PROFILE", "official"),
    }
    path = config_path or os.environ.get(
        "STAGE1_CONFIG",
        os.path.join(GC2026_ROOT, "output/remediation/stage1_config.json"),
    )
    if not os.path.isfile(path):
        return defaults
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    out = dict(cfg.get("default", {}))
    out.update(cfg.get("sequences", {}).get(seq, {}))
    for k in ("backend", "transform_mode", "depth_scale", "frame_map_mode", "multi_camera", "merge_voxel_mm", "cwipc_filter_profile"):
        if k not in out:
            out[k] = defaults.get(k)
    return out


def _load_coord_corrections_cached(path: Optional[str]) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    if not hasattr(_load_coord_corrections_cached, "_cache"):
        _load_coord_corrections_cached._cache = {}  # type: ignore[attr-defined]
    cache: dict = _load_coord_corrections_cached._cache  # type: ignore[attr-defined]
    if path not in cache:
        from coord_correction import load_coord_corrections

        cache[path] = load_coord_corrections(path)
    return cache[path]


def maybe_apply_coord_correction(
    xyz: np.ndarray,
    seq: str,
    coord_corrections_path: Optional[str],
) -> np.ndarray:
    if not coord_corrections_path:
        return xyz
    from coord_correction import apply_coord_correction, get_sequence_correction

    corrections = _load_coord_corrections_cached(coord_corrections_path)
    T = get_sequence_correction(seq, corrections)
    if T is None:
        return xyz
    return apply_coord_correction(xyz, T)


def reconstruct_for_backend(
    backend: str,
    cg_path: str,
    seq_root: str,
    playback_index: int,
    seq_params: dict,
    depth_trunc_mm: float,
    camera_index: int,
    tmp_dir: str,
    dry_run: bool = False,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Dispatch Stage1 reconstruction by backend name."""
    depth_scale = float(seq_params.get("depth_scale", 1000))
    transform_mode = str(seq_params.get("transform_mode", "legacy"))
    merge_voxel = float(seq_params.get("merge_voxel_mm", 3.0))
    multi_camera = bool(seq_params.get("multi_camera", False))

    if backend == "cwipc":
        return reconstruct_frame_cwipc(seq_root, playback_index, tmp_dir, dry_run=dry_run)

    if backend in ("open3d_cwipc_mc", "fusion"):
        return reconstruct_multicam_from_bags(
            seq_root,
            playback_index,
            depth_scale,
            depth_trunc_mm,
            "cwipc_coords",
            merge_voxel_mm=merge_voxel,
        )

    if backend in ("open3d_tsdf", "open3d_tsdf_mc"):
        return reconstruct_multicam_tsdf_from_bags(
            seq_root,
            playback_index,
            depth_scale,
            depth_trunc_mm,
            transform_mode,
            tsdf_voxel_mm=merge_voxel,
        )

    if backend == "open3d" or backend.startswith("open3d"):
        use_multi = multi_camera or backend == "open3d_multi" or backend == "open3d_tsdf"
        return try_open3d_path(
            cg_path,
            seq_root,
            depth_scale,
            depth_trunc_mm,
            transform_mode,
            camera_index,
            use_multi,
            merge_voxel,
            playback_index,
        )

    if backend == "auto":
        for candidate in ("open3d", "cwipc"):
            result = reconstruct_for_backend(
                candidate,
                cg_path,
                seq_root,
                playback_index,
                seq_params,
                depth_trunc_mm,
                camera_index,
                tmp_dir,
                dry_run=dry_run,
            )
            if result is not None:
                return result
        return None

    return try_open3d_path(
        cg_path,
        seq_root,
        depth_scale,
        depth_trunc_mm,
        transform_mode,
        camera_index,
        multi_camera,
        merge_voxel,
        playback_index,
    )


def _group_cg_jobs(
    cg_paths: list[str],
    out_root: str,
    args,
) -> dict[str, list[dict]]:
    """Group frames by sequence, sorted by playback_index for cwipc streaming."""
    from collections import defaultdict

    by_seq: dict[str, list[dict]] = defaultdict(list)
    for cg_path in cg_paths:
        seq = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(cg_path)))))
        out_path = os.path.join(out_root, seq, os.path.basename(cg_path))
        seq_root = cg_path.split("consumer-grade_capture_system/CG/")[0]
        frame_id = parse_frame_id(cg_path)
        seq_params = load_stage1_params(seq, args.stage1_config if os.path.isfile(args.stage1_config) else None)
        fmap = str(seq_params.get("frame_map_mode", args.frame_map_mode))
        playback_index = cg_frame_id_to_playback_index(frame_id, mode=fmap)
        by_seq[seq].append(
            {
                "cg_path": cg_path,
                "out_path": out_path,
                "seq_root": seq_root,
                "frame_id": frame_id,
                "playback_index": playback_index,
                "seq_params": seq_params,
                "fmap": fmap,
                "backend": str(
                    seq_params.get("backend", args.backend if args.backend != "hybrid" else "open3d_cwipc_mc")
                ),
            }
        )
    for seq in by_seq:
        by_seq[seq].sort(key=lambda j: j["playback_index"])
    return by_seq


def _process_cwipc_streaming(
    by_seq: dict[str, list[dict]],
    args,
    records: list,
    dry_run: bool,
) -> tuple[int, int]:
    ok, missing = 0, 0
    for seq, jobs in by_seq.items():
        override_cc = getattr(args, "cwipc_camera_config", None) or jobs[0]["seq_params"].get("cwipc_camera_config")
        profile = str(jobs[0]["seq_params"].get("cwipc_filter_profile", getattr(args, "cwipc_filter_profile", "official")))
        if dry_run:
            cfg = ensure_cwipc_playback_config(
                jobs[0]["seq_root"],
                override_cc,
                profile=profile,
            )
            for job in jobs:
                print(
                    f"[dry-run] seq={seq} frame={job['frame_id']} "
                    f"playback_index={job['playback_index']} config={cfg}"
                )
                ok += 1
            continue

        override_cc = getattr(args, "cwipc_camera_config", None) or jobs[0]["seq_params"].get("cwipc_camera_config")
        profile = str(jobs[0]["seq_params"].get("cwipc_filter_profile", getattr(args, "cwipc_filter_profile", "official")))
        cfg = ensure_cwipc_playback_config(
            jobs[0]["seq_root"],
            override_cc,
            profile=profile,
        )
        if not cfg:
            missing += len(jobs)
            continue

        streamer = CwipcSequenceStreamer(cfg, jobs[0]["seq_root"])
        try:
            for job in tqdm(jobs, desc=f"cwipc:{seq}"):
                if os.path.isfile(job["out_path"]) and not args.force:
                    ok += 1
                    continue
                try:
                    result = streamer.grab(job["playback_index"])
                except Exception as exc:
                    print(f"[WARN] cwipc stream {job['cg_path']}: {exc}")
                    result = None
                if result is None:
                    missing += 1
                    continue
                xyz, rgb = result
                if xyz.shape[0] < 100:
                    missing += 1
                    continue
                xyz = maybe_apply_coord_correction(xyz, seq, args.coord_corrections)
                os.makedirs(os.path.dirname(job["out_path"]), exist_ok=True)
                write_ply_xyz_rgb(job["out_path"], xyz, rgb)
                sp = job["seq_params"]
                records.append(
                    {
                        "frame_id": job["frame_id"],
                        "playback_index": job["playback_index"],
                        "cg_ref": job["cg_path"],
                        "out_path": job["out_path"],
                        "backend": "cwipc",
                        "transform_mode": str(sp.get("transform_mode", args.transform_mode)),
                        "depth_scale": float(sp.get("depth_scale", args.depth_scale)),
                        "frame_map_mode": job["fmap"],
                        "multi_camera": False,
                        "points": int(xyz.shape[0]),
                    }
                )
                ok += 1
        finally:
            streamer.close()
    return ok, missing


def _process_hybrid_by_seq(
    by_seq: dict[str, list[dict]],
    args,
    records: list,
) -> tuple[int, int]:
    """Per-sequence backend from stage1_config (PGDR / hybrid mode)."""
    ok, missing = 0, 0
    for seq, jobs in by_seq.items():
        seq_backend = jobs[0]["backend"]
        if seq_backend == "cwipc":
            o, m = _process_cwipc_streaming({seq: jobs}, args, records, dry_run=False)
            ok += o
            missing += m
            continue

        for job in tqdm(jobs, desc=f"{seq_backend}:{seq}"):
            if os.path.isfile(job["out_path"]) and not args.force:
                ok += 1
                continue
            tmp = os.path.join(args.out_root, ".cwipc_tmp", seq, job["frame_id"])
            try:
                result = reconstruct_for_backend(
                    seq_backend,
                    job["cg_path"],
                    job["seq_root"],
                    job["playback_index"],
                    job["seq_params"],
                    args.depth_trunc_mm,
                    args.camera_index,
                    tmp,
                    dry_run=False,
                )
            except Exception as exc:
                print(f"[WARN] hybrid {seq_backend} failed {job['cg_path']}: {exc}")
                result = None
            if result is None:
                missing += 1
                continue
            xyz, rgb = result
            if xyz.shape[0] < 100:
                missing += 1
                continue
            xyz = maybe_apply_coord_correction(xyz, seq, args.coord_corrections)
            os.makedirs(os.path.dirname(job["out_path"]), exist_ok=True)
            write_ply_xyz_rgb(job["out_path"], xyz, rgb)
            sp = job["seq_params"]
            records.append(
                {
                    "frame_id": job["frame_id"],
                    "playback_index": job["playback_index"],
                    "cg_ref": job["cg_path"],
                    "out_path": job["out_path"],
                    "backend": seq_backend,
                    "transform_mode": str(sp.get("transform_mode", args.transform_mode)),
                    "depth_scale": float(sp.get("depth_scale", args.depth_scale)),
                    "frame_map_mode": job["fmap"],
                    "multi_camera": bool(sp.get("multi_camera", False)),
                    "points": int(xyz.shape[0]),
                }
            )
            ok += 1
    return ok, missing


def main():
    p = argparse.ArgumentParser(description="RGBD/bag -> CG-format PLY for Full Pipeline")
    p.add_argument("--cg-list", required=True, help="Reference CG paths (defines frames and output names)")
    p.add_argument("--out-root", default=None, help="Output root; mirrors sequence/CG_15fps naming")
    p.add_argument("--depth-scale", type=float, default=float(os.environ.get("RGBD_DEPTH_SCALE", "1000")))
    p.add_argument("--depth-trunc-mm", type=float, default=5000.0)
    p.add_argument("--max-samples", type=int, default=0)
    p.add_argument(
        "--backend",
        default=os.environ.get("RGBD_TO_CG_BACKEND", "auto"),
        choices=["auto", "cwipc", "open3d", "open3d_tsdf", "hybrid", "open3d_cwipc_mc", "fusion"],
        help="hybrid=per-seq backend; open3d_tsdf=8cam TSDF fusion; fusion=Open3D 8cam+cwipc_coords",
    )
    p.add_argument("--frame-map-mode", default="even", choices=["even", "identity"])
    p.add_argument(
        "--transform-mode",
        default=os.environ.get("RGBD_TRANSFORM_MODE", "legacy"),
        help="Coordinate chain: legacy|seq_only|cwipc_coords|...",
    )
    p.add_argument("--camera-index", type=int, default=0)
    p.add_argument("--multi-camera", action="store_true", help="Fuse all 8 bags per frame")
    p.add_argument("--merge-voxel-mm", type=float, default=3.0)
    p.add_argument("--force", action="store_true", help="Overwrite existing PLY")
    p.add_argument(
        "--stage1-config",
        default=os.environ.get("STAGE1_CONFIG", os.path.join(GC2026_ROOT, "output/remediation/stage1_config.json")),
        help="JSON with default + per-sequence transform/depth_scale",
    )
    p.add_argument("--dry-run", action="store_true", help="Print cwipc commands / paths only")
    p.add_argument(
        "--coord-corrections",
        default=os.environ.get(
            "COORD_CORRECTIONS",
            os.path.join(GC2026_ROOT, "output/remediation/coord_corrections.json"),
        ),
        help="JSON with per-sequence HE-calibrated ΔT (applied post-recon if file exists)",
    )
    p.add_argument(
        "--no-coord-corrections",
        action="store_true",
        help="Disable HE coordinate correction even if default JSON exists",
    )
    p.add_argument(
        "--cwipc-camera-config",
        default=None,
        help="Override camera_config.json for cwipc playback (bags must be reachable from its directory)",
    )
    p.add_argument(
        "--cwipc-filter-profile",
        default=os.environ.get("CWIPC_FILTER_PROFILE", "official"),
        choices=["official", "relaxed", "mild"],
        help="CWIPC depth filter profile for playback config",
    )
    args = p.parse_args()
    if args.no_coord_corrections:
        args.coord_corrections = None
    if not args.out_root:
        if args.dry_run:
            args.out_root = os.path.join(GC2026_ROOT, "output", "rgbd_to_cg_dry_run")
        else:
            p.error("--out-root is required unless --dry-run")

    with open(args.cg_list, "r", encoding="utf-8") as f:
        cg_paths = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if args.max_samples > 0:
        cg_paths = cg_paths[:args.max_samples]

    records = []
    missing = 0
    ok = 0

    use_cwipc_stream = args.backend == "cwipc" and not args.multi_camera
    use_hybrid = args.backend == "hybrid"

    if use_hybrid:
        by_seq = _group_cg_jobs(cg_paths, args.out_root, args)
        ok, missing = _process_hybrid_by_seq(by_seq, args, records)
    elif use_cwipc_stream:
        by_seq = _group_cg_jobs(cg_paths, args.out_root, args)
        ok, missing = _process_cwipc_streaming(by_seq, args, records, args.dry_run)
    else:
        for cg_path in tqdm(cg_paths, desc="rgbd_to_cg"):
            seq = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(cg_path)))))
            out_path = os.path.join(args.out_root, seq, os.path.basename(cg_path))
            if os.path.isfile(out_path) and not args.dry_run and not args.force:
                ok += 1
                continue

            seq_root = cg_path.split("consumer-grade_capture_system/CG/")[0]
            frame_id = parse_frame_id(cg_path)
            seq_params = load_stage1_params(seq, args.stage1_config if os.path.isfile(args.stage1_config) else None)
            fmap = str(seq_params.get("frame_map_mode", args.frame_map_mode))
            playback_index = cg_frame_id_to_playback_index(frame_id, mode=fmap)
            depth_scale = float(seq_params.get("depth_scale", args.depth_scale))
            transform_mode = str(seq_params.get("transform_mode", args.transform_mode))
            tmp = os.path.join(args.out_root, ".cwipc_tmp", seq, frame_id)

            result: Optional[tuple[np.ndarray, np.ndarray]] = None
            backend_used = ""

            if args.backend in ("open3d_cwipc_mc", "fusion"):
                result = reconstruct_for_backend(
                    args.backend,
                    cg_path,
                    seq_root,
                    playback_index,
                    {**seq_params, "multi_camera": True, "transform_mode": "cwipc_coords"},
                    args.depth_trunc_mm,
                    args.camera_index,
                    tmp,
                    dry_run=args.dry_run,
                )
                backend_used = args.backend
            elif args.backend in ("auto", "cwipc") and not args.multi_camera:
                result = reconstruct_frame_cwipc(seq_root, playback_index, tmp, dry_run=args.dry_run)
                if args.dry_run:
                    cfg = ensure_cwipc_playback_config(seq_root)
                    print(
                        f"[dry-run] seq={seq} frame={frame_id} playback_index={playback_index} "
                        f"api=cwipc_realsense2_playback "
                        f"config={cfg or find_camera_config(seq_root)} "
                        f"bags_dir={os.path.dirname(cfg) if cfg else 'MISSING'} "
                        f"transform={find_transform_matrix(seq_root)}"
                    )
                    ok += 1
                    continue
                if result is not None:
                    backend_used = "cwipc"

            elif args.backend == "open3d_tsdf":
                result = reconstruct_for_backend(
                    "open3d_tsdf",
                    cg_path,
                    seq_root,
                    playback_index,
                    {**seq_params, "transform_mode": transform_mode},
                    args.depth_trunc_mm,
                    args.camera_index,
                    tmp,
                    dry_run=args.dry_run,
                )
                if result is not None:
                    backend_used = "open3d_tsdf"

            if result is None and args.backend in ("auto", "open3d"):
                try:
                    result = try_open3d_path(
                        cg_path,
                        seq_root,
                        depth_scale,
                        args.depth_trunc_mm,
                        transform_mode,
                        args.camera_index,
                        args.multi_camera,
                        args.merge_voxel_mm,
                        playback_index,
                    )
                    if result is not None:
                        backend_used = "open3d" + ("_multi" if args.multi_camera else "")
                except Exception as exc:
                    print(f"[WARN] open3d failed {cg_path}: {exc}")

            if result is None:
                missing += 1
                continue

            xyz, rgb = result
            if xyz.shape[0] < 100:
                missing += 1
                continue
            xyz = maybe_apply_coord_correction(xyz, seq, args.coord_corrections)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            write_ply_xyz_rgb(out_path, xyz, rgb)
            records.append(
                {
                    "frame_id": frame_id,
                    "playback_index": playback_index,
                    "cg_ref": cg_path,
                    "out_path": out_path,
                    "backend": backend_used,
                    "transform_mode": transform_mode,
                    "depth_scale": depth_scale,
                    "frame_map_mode": fmap,
                    "multi_camera": args.multi_camera,
                    "points": int(xyz.shape[0]),
                }
            )
            ok += 1

    meta = {
        "out_root": args.out_root,
        "backend": args.backend,
        "cwipc_streaming": use_cwipc_stream,
        "frame_map_mode": args.frame_map_mode,
        "transform_mode": args.transform_mode,
        "camera_index": args.camera_index,
        "multi_camera": args.multi_camera,
        "merge_voxel_mm": args.merge_voxel_mm,
        "depth_scale": args.depth_scale,
        "dry_run": args.dry_run,
        "requested": len(cg_paths),
        "written": ok,
        "missing": missing,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    meta_path = os.path.join(args.out_root, "rgbd_to_cg_meta.json")
    if not args.dry_run:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"summary": meta, "records": records}, f, indent=2)
    print(json.dumps(meta, indent=2))
    if ok == 0 and not args.dry_run:
        raise SystemExit(
            "No frames reconstructed. Download RGBD/raw or use --dry-run to inspect paths."
        )


if __name__ == "__main__":
    main()
