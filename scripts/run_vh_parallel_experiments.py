#!/usr/bin/env python3
"""Parallel VH experiments targeting TT-like CD (~530mm). Focus: cwipc + corrections."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from coord_correction import icp_rigid_transform  # noqa: E402
from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402
from uvg_io import read_ply_xyz  # noqa: E402

SEQ = "VictoryHeart"
PY_CW = os.environ.get("PY_CWIPC", "python3.12")
TT_TARGET_CD = 532.0

# tag, rgbd_to_cg extra args, coord json path (None=default vh, "none"=disable)
PARALLEL_VARIANTS = [
    ("G0_cwipc_raw", ["--merge-voxel-mm", "2.0", "--no-coord-corrections"], "none"),
    ("G1_cwipc_vh_he", ["--merge-voxel-mm", "2.0"], None),
    (
        "G2_cwipc_train_global_he",
        ["--merge-voxel-mm", "2.0"],
        os.path.join(GC2026_ROOT, "output/remediation/coord_corrections_train_global.json"),
    ),
    ("G3_cwipc_v15_raw", ["--merge-voxel-mm", "1.5", "--no-coord-corrections"], "none"),
    ("G4_cwipc_v25_vh_he", ["--merge-voxel-mm", "2.5"], None),
]


def sample_vh(cg_list: str, n: int) -> list[str]:
    paths = []
    with open(cg_list, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and f"/{SEQ}/" in ln:
                paths.append(ln)
    return paths if n <= 0 else paths[:n]


def eval_icp_upper_bound(recon_root: str, cg_paths: list[str], n_samples: int = 5000) -> dict:
    """Dev-only: apply per-frame ICP(recon→official) then measure CD (upper bound)."""
    rng = np.random.RandomState(21)
    cd_list, gains = [], []
    for cg in cg_paths:
        recon = recon_path_from_cg(cg, recon_root)
        if not os.path.isfile(recon) or not os.path.isfile(cg):
            continue
        recon_xyz = read_ply_xyz(recon, max_points=80000, rng=rng)
        off_xyz = read_ply_xyz(cg, max_points=80000, rng=rng)
        from evaluate_uvg import chamfer_symmetric_kdtree

        before = chamfer_symmetric_kdtree(recon_xyz, off_xyz, n_samples, rng)["cd_l1"]
        T, _meta = icp_rigid_transform(recon_xyz, off_xyz, max_corr=800.0)
        aligned = (recon_xyz @ T[:3, :3].T) + T[:3, 3]
        after = chamfer_symmetric_kdtree(aligned, off_xyz, n_samples, rng)["cd_l1"]
        cd_list.append(after)
        gains.append(before - after)
    if not cd_list:
        return {"num_evaluated": 0}
    return {
        "num_evaluated": len(cd_list),
        "mean_cd_l1": float(np.mean(cd_list)),
        "mean_icp_gain_mm": float(np.mean(gains)),
        "note": "dev-only upper bound (ICP to official CG)",
    }


def run_one(
    tag: str,
    cg_paths: list[str],
    extra: list[str],
    coord_mode: str | None,
    sweep_root: str,
) -> dict:
    out_root = os.path.join(sweep_root, tag)
    os.makedirs(out_root, exist_ok=True)
    lst = os.path.join(out_root, "_cg.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")
    cmd = [
        PY_CW,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list", lst,
        "--out-root", out_root,
        "--backend", "cwipc",
        "--force",
        *extra,
    ]
    if coord_mode == "none":
        if "--no-coord-corrections" not in extra:
            cmd.append("--no-coord-corrections")
    elif isinstance(coord_mode, str) and coord_mode not in ("none",) and os.path.isfile(coord_mode):
        cmd.extend(["--coord-corrections", coord_mode])
    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"tag": tag, "error": (exc.stderr or exc.stdout or str(exc))[:800]}
    official_pairs = [(p, p) for p in cg_paths]
    m = mean_chamfer_pairs(recon_official_pairs(out_root, official_pairs), n_samples=5000)
    icp_ub = {"skipped": True}
    return {
        "tag": tag,
        "recon_vs_official": m,
        "icp_upper_bound": icp_ub,
        "coord_mode": coord_mode,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--quick-frames", type=int, default=30)
    p.add_argument("--full-seq", action="store_true")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--icp-upper-bound", action="store_true", help="Slow dev-only ICP upper bound on best variant")
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/vh_parallel_experiments.json"))
    args = p.parse_args()

    n = 0 if args.full_seq else args.quick_frames
    cg_paths = sample_vh(args.cg_list, n)
    sweep_root = os.path.join(GC2026_ROOT, "output/remediation/vh_parallel")

    results = []
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {
            ex.submit(run_one, tag, cg_paths, extra, cc, sweep_root): tag
            for tag, extra, cc in PARALLEL_VARIANTS
        }
        for fut in as_completed(futs):
            tag = futs[fut]
            print(f"[vh_parallel] done {tag}", flush=True)
            results.append(fut.result())

    ranked = sorted(
        [r for r in results if r.get("recon_vs_official", {}).get("mean_cd_l1")],
        key=lambda x: x["recon_vs_official"]["mean_cd_l1"],
    )
    best = ranked[0] if ranked else None
    best_cd = best["recon_vs_official"]["mean_cd_l1"] if best else None

    if args.icp_upper_bound and best:
        icp_ub = eval_icp_upper_bound(
            os.path.join(sweep_root, best["tag"]),
            cg_paths[: min(10, len(cg_paths))],
        )
        best["icp_upper_bound"] = icp_ub

    icp_ranked = []

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sequence": SEQ,
        "n_frames": len(cg_paths),
        "tt_target_cd_mm": TT_TARGET_CD,
        "pass_tt_target": best_cd is not None and best_cd <= TT_TARGET_CD,
        "best": best,
        "best_icp_upper_bound": icp_ranked[0] if icp_ranked else None,
        "ranked": [
            {
                "tag": r["tag"],
                "cd": r["recon_vs_official"]["mean_cd_l1"],
                "accuracy": r["recon_vs_official"].get("mean_accuracy_l1"),
                "completeness": r["recon_vs_official"].get("mean_completeness_l1"),
                "icp_ub_cd": r.get("icp_upper_bound", {}).get("mean_cd_l1"),
                "icp_gain_mm": r.get("icp_upper_bound", {}).get("mean_icp_gain_mm"),
            }
            for r in ranked
        ],
        "results": results,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({
        "best": best["tag"] if best else None,
        "best_cd": best_cd,
        "best_icp_ub": best.get("icp_upper_bound", {}).get("mean_cd_l1") if best else None,
        "tt_target": TT_TARGET_CD,
        "pass": report["pass_tt_target"],
        "out": args.out_json,
    }, indent=2))


if __name__ == "__main__":
    main()
