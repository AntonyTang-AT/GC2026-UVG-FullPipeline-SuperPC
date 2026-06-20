#!/usr/bin/env python3
"""ICP upper-bound diagnostic: recon aligned to official CG (not for production)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import open3d as o3d

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from evaluate_uvg import chamfer_symmetric_kdtree  # noqa: E402
from uvg_io import read_ply_xyz  # noqa: E402


def icp_cd(recon_path: str, official_path: str, n_samples: int = 5000) -> dict:
    rng = np.random.RandomState(21)
    rec = read_ply_xyz(recon_path, max_points=100000, rng=rng)
    off = read_ply_xyz(official_path, max_points=100000, rng=rng)

    src = o3d.geometry.PointCloud()
    src.points = o3d.utility.Vector3dVector(rec.astype(np.float64))
    tgt = o3d.geometry.PointCloud()
    tgt.points = o3d.utility.Vector3dVector(off.astype(np.float64))

    reg = o3d.pipelines.registration.registration_icp(
        src,
        tgt,
        max_correspondence_distance=500.0,
        init=np.eye(4),
        estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPoint(),
    )
    src.transform(reg.transformation)
    aligned = np.asarray(src.points, dtype=np.float32)
    before = chamfer_symmetric_kdtree(rec, off, n_samples, rng)
    after = chamfer_symmetric_kdtree(aligned, off, n_samples, rng)
    return {
        "cd_before": before["cd_l1"],
        "cd_after_icp": after["cd_l1"],
        "fitness": float(reg.fitness),
        "rmse": float(reg.inlier_rmse),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--recon-root", default=os.path.join(GC2026_ROOT, "output/full_pipeline_val_cg"))
    p.add_argument("--max-frames", type=int, default=20)
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/icp_upper_bound.json"))
    args = p.parse_args()

    with open(args.cg_list, "r", encoding="utf-8") as f:
        cg_paths = [ln.strip() for ln in f if ln.strip()][: args.max_frames]

    records = []
    for cg in cg_paths:
        recon = recon_path_from_cg(cg, args.recon_root)
        if not os.path.isfile(recon) or not os.path.isfile(cg):
            continue
        try:
            m = icp_cd(recon, cg)
            records.append({"cg_path": cg, **m})
        except Exception as exc:
            records.append({"cg_path": cg, "error": str(exc)})

    cds_before = [r["cd_before"] for r in records if "cd_before" in r]
    cds_after = [r["cd_after_icp"] for r in records if "cd_after_icp" in r]
    report = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "recon_root": args.recon_root,
        "n_evaluated": len(records),
        "mean_cd_before": float(np.mean(cds_before)) if cds_before else None,
        "mean_cd_after_icp": float(np.mean(cds_after)) if cds_after else None,
        "records": records,
        "interpretation": (
            "Large drop after ICP implies geometry content is usable but coordinate chain is wrong. "
            "Small drop implies depth/content mismatch with official CG."
        ),
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2)[:2000])


if __name__ == "__main__":
    main()
