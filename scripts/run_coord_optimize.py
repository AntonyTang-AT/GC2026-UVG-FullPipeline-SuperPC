#!/usr/bin/env python3
"""Estimate HE-based coord corrections on train/dev seqs; apply and evaluate vs official CG."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from coord_correction import (  # noqa: E402
    apply_coord_correction,
    estimate_sequence_correction_from_he,
    get_sequence_correction,
    load_coord_corrections,
)
from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402
from uvg_io import cg_to_he_path, read_ply_xyz, read_ply_xyz_rgb, write_ply_xyz_rgb  # noqa: E402


def sample_cg(cg_list: str, seq: str, n: int) -> list[str]:
    out = []
    with open(cg_list, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and f"/{seq}/" in ln:
                out.append(ln)
    return out if n <= 0 else out[:n]


def rebuild_sequence(
    seq: str,
    cg_paths: list[str],
    out_root: str,
    py: str,
    extra_args: list[str],
) -> None:
    os.makedirs(out_root, exist_ok=True)
    lst = os.path.join(out_root, "_cg.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")
    cmd = [
        py,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list", lst,
        "--out-root", out_root,
        "--force",
        *extra_args,
    ]
    subprocess.run(cmd, check=True, cwd=GC2026_ROOT)


def apply_corrections_to_root(
    recon_root: str,
    cg_paths: list[str],
    corrections: dict,
    out_root: str,
) -> None:
    for cg in cg_paths:
        seq = cg.split("/UVG-CWI-DQPC/")[1].split("/")[0]
        T = get_sequence_correction(seq, corrections)
        if T is None:
            continue
        src = recon_path_from_cg(cg, recon_root)
        dst = recon_path_from_cg(cg, out_root)
        if not os.path.isfile(src):
            continue
        xyz_full, rgb = read_ply_xyz_rgb(src)
        xyz_corr = apply_coord_correction(xyz_full, T)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        write_ply_xyz_rgb(dst, xyz_corr, rgb)


def main() -> None:
    p = argparse.ArgumentParser(description="HE coord correction estimate + apply")
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--sequences", nargs="+", default=["TicTacToe", "VictoryHeart"])
    p.add_argument("--calib-frames", type=int, default=10, help="Frames to estimate ΔT")
    p.add_argument("--eval-frames", type=int, default=15, help="Frames to evaluate after correction")
    p.add_argument("--method", choices=["icp", "centroid"], default="icp")
    p.add_argument("--corrections-json", default=os.path.join(GC2026_ROOT, "output/remediation/coord_corrections.json"))
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/coord_optimize_result.json"))
    p.add_argument("--skip-rebuild", action="store_true")
    args = p.parse_args()

    py_o3d = os.environ.get("PY_OPEN3D", "python3.12")
    py_cw = os.environ.get("PY_CWIPC", "python3.12")
    base_root = os.path.join(GC2026_ROOT, "output/remediation/coord_opt_base")
    corr_root = os.path.join(GC2026_ROOT, "output/remediation/coord_opt_corrected")

    seq_configs = {
        "TicTacToe": (py_o3d, [
            "--backend", "open3d",
            "--transform-mode", "seq_only",
            "--depth-scale", "5000",
            "--multi-camera",
            "--merge-voxel-mm", "2.0",
        ]),
        "VictoryHeart": (py_cw, [
            "--backend", "cwipc",
            "--merge-voxel-mm", "2.0",
        ]),
    }

    all_corrections: dict = {"sequences": {}, "meta": {"method": args.method, "source": "HE_dev_calibration"}}
    eval_results = []

    for seq in args.sequences:
        calib_paths = sample_cg(args.cg_list, seq, args.calib_frames)
        eval_paths = sample_cg(args.cg_list, seq, max(args.eval_frames, args.calib_frames))
        if not calib_paths:
            continue

        py, extra = seq_configs.get(seq, (py_o3d, ["--backend", "open3d"]))
        seq_base = base_root

        if not args.skip_rebuild:
            print(f"[coord_opt] rebuild {seq} n={len(eval_paths)}", flush=True)
            rebuild_sequence(seq, eval_paths, seq_base, py, extra)

        calib_pairs = [
            (recon_path_from_cg(cg, seq_base), cg_to_he_path(cg))
            for cg in calib_paths
        ]
        est = estimate_sequence_correction_from_he(calib_pairs, method=args.method)
        all_corrections["sequences"][seq] = est
        print(f"[coord_opt] {seq} ΔT n_calib={est.get('n_frames')} trans={est.get('translation_mm')}", flush=True)

        seq_corr = corr_root
        apply_corrections_to_root(seq_base, eval_paths, all_corrections["sequences"], seq_corr)

        pairs_before = recon_official_pairs(seq_base, [(c, c) for c in eval_paths])
        pairs_after = recon_official_pairs(seq_corr, [(c, c) for c in eval_paths])
        m_before = mean_chamfer_pairs(pairs_before, n_samples=5000)
        m_after = mean_chamfer_pairs(pairs_after, n_samples=5000)
        eval_results.append({
            "sequence": seq,
            "n_eval": len(eval_paths),
            "before_vs_official": m_before,
            "after_he_correction_vs_official": m_after,
            "delta_cd_mm": (
                float(m_before["mean_cd_l1"] - m_after["mean_cd_l1"])
                if m_before.get("mean_cd_l1") and m_after.get("mean_cd_l1")
                else None
            ),
            "correction": est,
        })

    os.makedirs(os.path.dirname(args.corrections_json), exist_ok=True)
    with open(args.corrections_json, "w", encoding="utf-8") as f:
        json.dump(all_corrections, f, indent=2)

    est_overall = None
    if eval_results:
        weights = {"TicTacToe": 165, "VictoryHeart": 197}
        num = den = 0
        for r in eval_results:
            cd = r["after_he_correction_vs_official"].get("mean_cd_l1")
            if cd is not None:
                w = weights.get(r["sequence"], 1)
                num += cd * w
                den += w
        if den:
            est_overall = num / den

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": args.method,
        "estimated_hybrid_overall_after_correction_mm": est_overall,
        "pass_350": est_overall is not None and est_overall < 350,
        "sequences": eval_results,
        "corrections_path": args.corrections_json,
    }
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps({
        "est_overall_after": est_overall,
        "pass_350": report["pass_350"],
        "sequences": [
            {"seq": r["sequence"],
             "before": r["before_vs_official"].get("mean_cd_l1"),
             "after": r["after_he_correction_vs_official"].get("mean_cd_l1"),
             "delta": r["delta_cd_mm"]}
            for r in eval_results
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
