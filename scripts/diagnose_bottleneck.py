#!/usr/bin/env python3
"""Per-sequence Stage1 bottleneck diagnosis: which pipeline stage limits CD?

Stages probed (in memory, no full rebuild):
  - official_vs_he     : reference upper bound
  - single_cam         : 1 camera, seq_only (geometry + coord)
  - multi_voxel        : 8cam voxel merge
  - multi_tsdf         : 8cam TSDF fusion
  - cwipc              : cwipc playback path

For each stage vs official CG and vs HE:
  - CD, accuracy, completeness
  - ICP upper bound (coord residual) vs official / vs HE

Verdict maps dominant error to pipeline stage.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np
import open3d as o3d

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from diagnose_stage1 import mean_chamfer_pairs  # noqa: E402
from evaluate_uvg import chamfer_symmetric_kdtree  # noqa: E402
from rgbd_to_cg import (  # noqa: E402
    reconstruct_frame_cwipc,
    reconstruct_multicam_from_bags,
    reconstruct_multicam_tsdf_from_bags,
    try_open3d_path,
)
from uvg_frame_map import cg_frame_id_to_playback_index  # noqa: E402
from uvg_io import cg_to_he_path, parse_frame_id, read_ply_xyz  # noqa: E402


def icp_metrics(
    recon: np.ndarray,
    target: np.ndarray,
    n_samples: int = 5000,
    max_dist: float = 500.0,
) -> dict:
    rng = np.random.RandomState(21)
    before = chamfer_symmetric_kdtree(recon, target, n_samples, rng)
    src = o3d.geometry.PointCloud()
    src.points = o3d.utility.Vector3dVector(recon.astype(np.float64))
    tgt = o3d.geometry.PointCloud()
    tgt.points = o3d.utility.Vector3dVector(target.astype(np.float64))
    reg = o3d.pipelines.registration.registration_icp(
        src,
        tgt,
        max_correspondence_distance=max_dist,
        init=np.eye(4),
        estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPoint(),
    )
    src.transform(reg.transformation)
    aligned = np.asarray(src.points, dtype=np.float32)
    after = chamfer_symmetric_kdtree(aligned, target, n_samples, rng)
    return {
        "cd_before": float(before["cd_l1"]),
        "cd_after_icp": float(after["cd_l1"]),
        "coord_gain_mm": float(before["cd_l1"] - after["cd_l1"]),
        "accuracy_before": float(before["accuracy_l1"]),
        "completeness_before": float(before["completeness_l1"]),
        "fitness": float(reg.fitness),
    }


def eval_recon_vs_targets(
    xyz: np.ndarray,
    official_path: str,
    he_path: str | None,
    n_samples: int = 5000,
) -> dict:
    rng = np.random.RandomState(21)
    off = read_ply_xyz(official_path, max_points=100000, rng=rng)
    m_off = chamfer_symmetric_kdtree(xyz, off, n_samples, rng)
    out = {
        "n_points": int(xyz.shape[0]),
        "vs_official": {
            "cd_l1": float(m_off["cd_l1"]),
            "accuracy_l1": float(m_off["accuracy_l1"]),
            "completeness_l1": float(m_off["completeness_l1"]),
        },
        "icp_vs_official": icp_metrics(xyz, off, n_samples),
    }
    if he_path and os.path.isfile(he_path):
        he = read_ply_xyz(he_path, max_points=100000, rng=rng)
        m_he = chamfer_symmetric_kdtree(xyz, he, n_samples, rng)
        out["vs_he"] = {
            "cd_l1": float(m_he["cd_l1"]),
            "accuracy_l1": float(m_he["accuracy_l1"]),
            "completeness_l1": float(m_he["completeness_l1"]),
        }
        out["icp_vs_he"] = icp_metrics(xyz, he, n_samples)
    return out


def reconstruct_stage(
    stage: str,
    cg_path: str,
    seq_root: str,
    playback_index: int,
    depth_scale: float,
    transform_mode: str,
    merge_voxel_mm: float,
    tmp_dir: str,
) -> np.ndarray | None:
    depth_trunc = 5000.0
    if stage == "single_cam":
        r = try_open3d_path(
            cg_path, seq_root, depth_scale, depth_trunc, transform_mode,
            0, False, merge_voxel_mm, playback_index,
        )
    elif stage == "multi_voxel":
        r = reconstruct_multicam_from_bags(
            seq_root, playback_index, depth_scale, depth_trunc,
            transform_mode, merge_voxel_mm=merge_voxel_mm,
        )
    elif stage == "multi_tsdf":
        r = reconstruct_multicam_tsdf_from_bags(
            seq_root, playback_index, depth_scale, depth_trunc,
            transform_mode, tsdf_voxel_mm=merge_voxel_mm,
        )
    elif stage == "cwipc":
        r = reconstruct_frame_cwipc(seq_root, playback_index, tmp_dir, dry_run=False)
    else:
        return None
    if r is None:
        return None
    return r[0]


STAGE_CONFIGS = {
    "TicTacToe": [
        ("single_cam", {"depth_scale": 5000, "transform_mode": "seq_only", "merge_voxel_mm": 3.0, "multi": False}),
        ("multi_voxel", {"depth_scale": 5000, "transform_mode": "seq_only", "merge_voxel_mm": 2.0, "multi": True}),
        ("multi_voxel_v3", {"depth_scale": 5000, "transform_mode": "seq_only", "merge_voxel_mm": 3.0, "multi": True}),
        ("multi_tsdf_v2", {"depth_scale": 5000, "transform_mode": "seq_only", "merge_voxel_mm": 2.0, "multi": True}),
        ("multi_tsdf_v3", {"depth_scale": 5000, "transform_mode": "seq_only", "merge_voxel_mm": 3.0, "multi": True}),
        ("cwipc", {"depth_scale": 1000, "transform_mode": "cwipc_coords", "merge_voxel_mm": 2.0, "multi": False}),
    ],
    "VictoryHeart": [
        ("cwipc_v2", {"depth_scale": 1000, "transform_mode": "cwipc_coords", "merge_voxel_mm": 2.0, "multi": False}),
        ("cwipc_v3", {"depth_scale": 1000, "transform_mode": "cwipc_coords", "merge_voxel_mm": 3.0, "multi": False}),
        ("single_cam", {"depth_scale": 5000, "transform_mode": "seq_only", "merge_voxel_mm": 3.0, "multi": False}),
        ("multi_voxel", {"depth_scale": 5000, "transform_mode": "seq_only", "merge_voxel_mm": 2.0, "multi": True}),
        ("multi_tsdf_v2", {"depth_scale": 5000, "transform_mode": "seq_only", "merge_voxel_mm": 2.0, "multi": True}),
    ],
}


def infer_bottleneck(stage_summary: list[dict], ref_official_he: dict) -> dict:
    """Heuristic verdict from accuracy/completeness and ICP gains."""
    valid = [s for s in stage_summary if s.get("mean_cd_vs_official") is not None]
    if not valid:
        return {"verdict": "no_data"}

    best = min(valid, key=lambda x: x["mean_cd_vs_official"])
    worst_acc = max(valid, key=lambda x: x["mean_accuracy"])
    worst_comp = max(valid, key=lambda x: x["mean_completeness"])

    icp_gains = [(s["stage"], s.get("mean_icp_coord_gain", 0.0)) for s in valid]
    max_icp_stage, max_icp_gain = max(icp_gains, key=lambda x: x[1])

    acc_dom = best["mean_accuracy"] > best["mean_completeness"] * 1.2
    comp_dom = best["mean_completeness"] > best["mean_accuracy"] * 1.2

    if max_icp_gain > 150:
        primary = "coordinate_registration"
        detail = (
            f"ICP vs official 可降 {max_icp_gain:.0f}mm（{max_icp_stage}），"
            "主瓶颈在坐标/外参链，而非深度几何本身"
        )
    elif comp_dom:
        primary = "completeness_fusion"
        detail = (
            f"completeness ({best['mean_completeness']:.0f}mm) "
            f">> accuracy ({best['mean_accuracy']:.0f}mm)；"
            "缺表面/多视角融合不足，优先 TSDF/8cam/ densification"
        )
    elif acc_dom:
        primary = "accuracy_depth_coord"
        detail = (
            f"accuracy ({best['mean_accuracy']:.0f}mm) 主导；"
            "深度 scale / 外参 / 与官方 CG 坐标系不一致"
        )
    else:
        primary = "mixed_geometry_coord"
        detail = "accuracy 与 completeness 均衡偏高，需坐标+融合双线优化"

    he_cd = ref_official_he.get("mean_cd_l1")
    best_cd = best["mean_cd_vs_official"]
    gap_to_he_pipeline = float(best_cd - he_cd) if he_cd is not None else None

    return {
        "best_stage": best["stage"],
        "best_cd_vs_official": float(best_cd),
        "official_vs_he_cd": he_cd,
        "gap_best_vs_official_he": gap_to_he_pipeline,
        "worst_accuracy_stage": worst_acc["stage"],
        "worst_completeness_stage": worst_comp["stage"],
        "max_icp_coord_gain_mm": float(max_icp_gain),
        "max_icp_stage": max_icp_stage,
        "primary_bottleneck": primary,
        "detail_zh": detail,
    }


def stage_to_reconstruct_key(stage_name: str) -> str:
    if stage_name.startswith("cwipc"):
        return "cwipc"
    if stage_name.startswith("multi_tsdf"):
        return "multi_tsdf"
    if stage_name.startswith("multi_voxel"):
        return "multi_voxel"
    return stage_name


def diagnose_sequence(
    seq: str,
    cg_paths: list[str],
    n_samples: int = 5000,
) -> dict:
    frame_map = "even"
    stage_cfgs = STAGE_CONFIGS.get(seq, STAGE_CONFIGS["TicTacToe"])
    oh_list = [(cg, cg_to_he_path(cg)) for cg in cg_paths if os.path.isfile(cg_to_he_path(cg))]
    ref_official_he = mean_chamfer_pairs(oh_list, n_samples=n_samples)

    per_frame: list[dict] = []
    stage_agg: dict[str, list] = {cfg[0]: [] for cfg in stage_cfgs}

    with tempfile.TemporaryDirectory() as tmp:
        for cg_path in cg_paths:
            seq_root = cg_path.split("consumer-grade_capture_system/CG/")[0]
            frame_id = parse_frame_id(cg_path)
            playback_index = cg_frame_id_to_playback_index(frame_id, mode=frame_map)
            he_path = cg_to_he_path(cg_path)
            frame_rec = {"cg_path": cg_path, "frame_id": frame_id, "stages": {}}

            for stage_name, params in stage_cfgs:
                actual_stage = stage_to_reconstruct_key(stage_name)
                try:
                    xyz = reconstruct_stage(
                        actual_stage,
                        cg_path,
                        seq_root,
                        playback_index,
                        params["depth_scale"],
                        params["transform_mode"],
                        params["merge_voxel_mm"],
                        tmp,
                    )
                    if xyz is None or xyz.shape[0] < 50:
                        frame_rec["stages"][stage_name] = {"error": "empty_recon"}
                        continue
                    metrics = eval_recon_vs_targets(xyz, cg_path, he_path, n_samples)
                    metrics["stage"] = stage_name
                    frame_rec["stages"][stage_name] = metrics
                    stage_agg[stage_name].append(metrics)
                except Exception as exc:
                    frame_rec["stages"][stage_name] = {"error": str(exc)[:300]}
            per_frame.append(frame_rec)

    stage_summary = []
    for stage_name, _ in stage_cfgs:
        recs = stage_agg.get(stage_name, [])
        cds = [r["vs_official"]["cd_l1"] for r in recs if r.get("vs_official")]
        accs = [r["vs_official"]["accuracy_l1"] for r in recs if r.get("vs_official")]
        comps = [r["vs_official"]["completeness_l1"] for r in recs if r.get("vs_official")]
        icp_g = [r["icp_vs_official"]["coord_gain_mm"] for r in recs if r.get("icp_vs_official")]
        if not cds:
            continue
        stage_summary.append({
            "stage": stage_name,
            "n_ok": len(cds),
            "mean_cd_vs_official": float(np.mean(cds)),
            "mean_accuracy": float(np.mean(accs)),
            "mean_completeness": float(np.mean(comps)),
            "mean_icp_coord_gain": float(np.mean(icp_g)) if icp_g else 0.0,
        })

    stage_summary.sort(key=lambda x: x["mean_cd_vs_official"])
    verdict = infer_bottleneck(stage_summary, ref_official_he)

    return {
        "sequence": seq,
        "n_frames": len(cg_paths),
        "official_vs_he": ref_official_he,
        "stage_summary": stage_summary,
        "bottleneck": verdict,
        "per_frame": per_frame,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Stage1 bottleneck diagnosis per sequence")
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--sequences", nargs="+", default=["TicTacToe", "VictoryHeart"])
    p.add_argument("--max-frames", type=int, default=10)
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/bottleneck_diagnosis.json"))
    args = p.parse_args()

    with open(args.cg_list, encoding="utf-8") as f:
        all_paths = [ln.strip() for ln in f if ln.strip()]

    reports = []
    for seq in args.sequences:
        paths = [p for p in all_paths if f"/{seq}/" in p][: args.max_frames]
        if not paths:
            continue
        print(f"[bottleneck] {seq} n={len(paths)}", flush=True)
        reports.append(diagnose_sequence(seq, paths))

    out = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sequences": reports,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    for r in reports:
        b = r.get("bottleneck", {})
        print(
            f"\n=== {r['sequence']} ===\n"
            f"  official_vs_he: {r.get('official_vs_he', {}).get('mean_cd_l1', '?'):.1f} mm\n"
            f"  best_stage: {b.get('best_stage')} cd={b.get('best_cd_vs_official', '?'):.1f}\n"
            f"  bottleneck: {b.get('primary_bottleneck')}\n"
            f"  {b.get('detail_zh')}",
            flush=True,
        )
    print(f"\n[out] {args.out_json}", flush=True)


if __name__ == "__main__":
    main()
