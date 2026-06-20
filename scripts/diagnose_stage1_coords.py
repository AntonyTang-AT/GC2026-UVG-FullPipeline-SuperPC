#!/usr/bin/env python3
"""Compare Stage1 coordinate transform variants on a val subset."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from diagnose_stage1 import mean_chamfer_pairs, recon_he_pairs, recon_official_pairs, build_official_pairs  # noqa: E402
from uvg_io import read_ply_xyz  # noqa: E402


TRANSFORM_VARIANTS = [
    ("T0", "legacy"),
    ("T1", "chain_meters"),
    ("T2", "chain_mm_translate"),
    ("T3", "flip_mm_homogeneous"),
    ("T4", "camera_only"),
    ("T5", "seq_only"),
]


def cloud_stats_from_cg(cg_path: str, recon_root: str) -> dict:
    recon = recon_path_from_cg(cg_path, recon_root)
    off = read_ply_xyz(cg_path, max_points=50000)
    rec = read_ply_xyz(recon, max_points=50000)
    return {
        "centroid_delta": [float(x) for x in (rec.mean(0) - off.mean(0))],
        "recon_centroid": [float(x) for x in rec.mean(0)],
        "official_centroid": [float(x) for x in off.mean(0)],
    }


def run_variant(
    cg_paths: list[str],
    out_dir: str,
    transform_mode: str,
    depth_scale: float,
    frame_map: str,
    multi_camera: bool,
) -> dict:
    list_path = os.path.join(out_dir, "_cg_list.txt")
    os.makedirs(out_dir, exist_ok=True)
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")

    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list",
        list_path,
        "--out-root",
        out_dir,
        "--backend",
        "open3d",
        "--frame-map-mode",
        frame_map,
        "--depth-scale",
        str(depth_scale),
        "--transform-mode",
        transform_mode,
        "--force",
    ]
    if multi_camera:
        cmd.append("--multi-camera")

    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"error": (exc.stderr or exc.stdout or str(exc))[:800]}

    off_pairs = [(p, p) for p in cg_paths]
    ro = recon_official_pairs(out_dir, off_pairs)
    he_pairs = []
    for cg in cg_paths:
        from uvg_io import cg_to_he_path

        he = cg_to_he_path(cg)
        recon = recon_path_from_cg(cg, out_dir)
        if os.path.isfile(recon) and os.path.isfile(he):
            he_pairs.append((recon, he))

    m_ro = mean_chamfer_pairs(ro, n_samples=5000)
    m_rh = mean_chamfer_pairs(he_pairs, n_samples=5000)
    stats = cloud_stats_from_cg(cg_paths[0], out_dir) if cg_paths else {}
    return {
        "recon_vs_official": m_ro,
        "recon_vs_he": m_rh,
        "centroid_sample": stats,
        "sweep_root": out_dir,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--max-frames", type=int, default=20)
    p.add_argument("--depth-scale", type=float, default=1000.0)
    p.add_argument("--frame-map-mode", default="even")
    p.add_argument("--include-multi", action="store_true")
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/coord_probe.json"))
    args = p.parse_args()

    with open(args.cg_list, "r", encoding="utf-8") as f:
        cg_paths = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")][: args.max_frames]

    probe_root = os.path.join(GC2026_ROOT, "output/remediation/coord_probe")
    os.makedirs(probe_root, exist_ok=True)

    results = []
    for tag, mode in TRANSFORM_VARIANTS:
        out_dir = os.path.join(probe_root, tag)
        res = run_variant(cg_paths, out_dir, mode, args.depth_scale, args.frame_map_mode, False)
        results.append({"id": tag, "transform_mode": mode, **res})

    if args.include_multi:
        out_dir = os.path.join(probe_root, "B_multi")
        res = run_variant(
            cg_paths[: min(5, len(cg_paths))],
            out_dir,
            "chain_meters",
            args.depth_scale,
            args.frame_map_mode,
            True,
        )
        results.append({"id": "B_multi", "transform_mode": "chain_meters", "multi_camera": True, **res})

    ranked = sorted(
        [r for r in results if r.get("recon_vs_official", {}).get("mean_cd_l1") is not None],
        key=lambda x: x["recon_vs_official"]["mean_cd_l1"],
    )

    report = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "n_frames": len(cg_paths),
        "depth_scale": args.depth_scale,
        "frame_map_mode": args.frame_map_mode,
        "variants": results,
        "ranked_by_recon_vs_official": [
            {"id": r["id"], "mean_cd_l1": r["recon_vs_official"]["mean_cd_l1"]} for r in ranked
        ],
        "best": ranked[0] if ranked else None,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"best": report.get("best", {}).get("id"), "out": args.out_json}, indent=2))


if __name__ == "__main__":
    main()
