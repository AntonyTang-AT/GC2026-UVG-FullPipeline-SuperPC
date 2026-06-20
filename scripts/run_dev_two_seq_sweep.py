#!/usr/bin/env python3
"""Fast method sweep on TicTacToe + VictoryHeart only (dev gate before full 2155).

Usage:
  python3 scripts/run_dev_two_seq_sweep.py --quick-frames 15
  python3 scripts/run_dev_two_seq_sweep.py --full-seq   # all val frames per seq
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402

DEV_SEQS = ("TicTacToe", "VictoryHeart")
GATE_SOFT = 350.0
GATE_IDEAL = 200.0


def sample_frames(cg_list: str, seq: str, n: int) -> list[str]:
    paths = []
    with open(cg_list, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and f"/{seq}/" in ln:
                paths.append(ln)
    if n > 0:
        paths = paths[:n]
    return paths


def run_variant(
    tag: str,
    cg_paths: list[str],
    out_root: str,
    backend: str,
    extra: list[str],
    py: str,
) -> dict:
    os.makedirs(out_root, exist_ok=True)
    lst = os.path.join(out_root, "_cg.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")
    cmd = [
        py,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list",
        lst,
        "--out-root",
        out_root,
        "--backend",
        backend,
        "--force",
        *extra,
    ]
    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"tag": tag, "error": (exc.stderr or exc.stdout or str(exc))[:800]}
    pairs = recon_official_pairs(out_root, [(p, p) for p in cg_paths])
    m = mean_chamfer_pairs(pairs, n_samples=5000)
    by_seq: dict[str, list[float]] = {}
    # per-seq needs individual eval
    result = {"tag": tag, "recon_vs_official": m, "out_root": out_root}
    for seq in DEV_SEQS:
        sp = [p for p in cg_paths if f"/{seq}/" in p]
        if not sp:
            continue
        pp = recon_official_pairs(out_root, [(p, p) for p in sp])
        ms = mean_chamfer_pairs(pp, n_samples=5000)
        result[f"{seq}_cd"] = ms.get("mean_cd_l1")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Dev sweep TT+VH methods")
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--quick-frames", type=int, default=15)
    p.add_argument("--full-seq", action="store_true")
    p.add_argument("--gate-soft", type=float, default=GATE_SOFT)
    p.add_argument("--gate-ideal", type=float, default=GATE_IDEAL)
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/dev_two_seq_sweep.json"))
    args = p.parse_args()

    py_o3d = os.environ.get("PY_OPEN3D", "python3.12")
    py_cw = os.environ.get("PY_CWIPC", "python3.12")
    n = 0 if args.full_seq else args.quick_frames

    all_paths: list[str] = []
    for seq in DEV_SEQS:
        all_paths.extend(sample_frames(args.cg_list, seq, n))

    sweep_root = os.path.join(GC2026_ROOT, "output/remediation/dev_sweep")
    variants = [
        ("M0_tt_8cam", "open3d", py_o3d, [
            "--transform-mode", "seq_only", "--depth-scale", "5000",
            "--multi-camera", "--merge-voxel-mm", "3.0",
        ]),
        ("M0_tt_8cam_v2", "open3d", py_o3d, [
            "--transform-mode", "seq_only", "--depth-scale", "5000",
            "--multi-camera", "--merge-voxel-mm", "2.0",
        ]),
        ("M1_tt_tsdf_v2", "open3d_tsdf", py_o3d, [
            "--transform-mode", "seq_only", "--depth-scale", "5000",
            "--merge-voxel-mm", "2.0",
        ]),
        ("M1_tt_tsdf_v3", "open3d_tsdf", py_o3d, [
            "--transform-mode", "seq_only", "--depth-scale", "5000",
            "--merge-voxel-mm", "3.0",
        ]),
        ("M0_vh_cwipc_v2", "cwipc", py_cw, ["--merge-voxel-mm", "2.0"]),
        ("M0_vh_cwipc_v3", "cwipc", py_cw, ["--merge-voxel-mm", "3.0"]),
        ("M2_vh_o3d_cwipc_ds5000", "open3d", py_o3d, [
            "--transform-mode", "cwipc_coords", "--depth-scale", "5000",
            "--multi-camera", "--merge-voxel-mm", "3.0",
        ]),
        ("M2_vh_o3d_cwipc_ds1000", "open3d", py_o3d, [
            "--transform-mode", "cwipc_coords", "--depth-scale", "1000",
            "--multi-camera", "--merge-voxel-mm", "3.0",
        ]),
        ("M2_tt_cwipc_coords_8cam", "open3d", py_o3d, [
            "--transform-mode", "cwipc_coords", "--depth-scale", "5000",
            "--multi-camera", "--merge-voxel-mm", "3.0",
        ]),
    ]

    # Split: TT-only and VH-only path lists for per-seq variants
    tt_paths = [p for p in all_paths if "/TicTacToe/" in p]
    vh_paths = [p for p in all_paths if "/VictoryHeart/" in p]

    results = []
    for tag, backend, py, extra in variants:
        if tag.startswith("M0_tt") or tag.startswith("M2_tt") or tag.startswith("M1_tt"):
            paths = tt_paths
        elif tag.startswith("M0_vh") or tag.startswith("M2_vh"):
            paths = vh_paths
        else:
            paths = all_paths
        if not paths:
            continue
        out = os.path.join(sweep_root, tag)
        print(f"[dev_sweep] {tag} n={len(paths)}", flush=True)
        results.append(run_variant(tag, paths, out, backend, extra, py))

    ranked = sorted(
        [r for r in results if r.get("recon_vs_official", {}).get("mean_cd_l1") is not None],
        key=lambda x: x["recon_vs_official"]["mean_cd_l1"],
    )

    # Best combined estimate: min TT cd + min VH cd weighted
    best_tt = min((r for r in results if r.get("TicTacToe_cd")), key=lambda x: x.get("TicTacToe_cd", 1e9), default=None)
    best_vh = min((r for r in results if r.get("VictoryHeart_cd")), key=lambda x: x.get("VictoryHeart_cd", 1e9), default=None)
    est_overall = None
    if best_tt and best_vh:
        est_overall = (
            best_tt["TicTacToe_cd"] * 165 + best_vh["VictoryHeart_cd"] * 197
        ) / 362

    report = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "n_frames_per_seq": len(tt_paths),
        "gate_soft_mm": args.gate_soft,
        "gate_ideal_mm": args.gate_ideal,
        "pass_soft": est_overall is not None and est_overall < args.gate_soft,
        "pass_ideal": est_overall is not None and est_overall < args.gate_ideal,
        "estimated_hybrid_overall_mm": est_overall,
        "best_tt_variant": best_tt,
        "best_vh_variant": best_vh,
        "results": results,
        "ranked": [{"tag": r["tag"], "cd": r["recon_vs_official"]["mean_cd_l1"]} for r in ranked],
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps({
        "estimated_overall": est_overall,
        "pass_350": report["pass_soft"],
        "pass_200": report["pass_ideal"],
        "best_tt": best_tt.get("tag") if best_tt else None,
        "best_vh": best_vh.get("tag") if best_vh else None,
        "out": args.out_json,
    }, indent=2))


if __name__ == "__main__":
    main()
