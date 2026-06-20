#!/usr/bin/env python3
"""Dev-only upper bound: per-sequence ICP correction to official CG (not for submission)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from coord_correction import apply_coord_correction, estimate_sequence_correction_from_he  # noqa: E402
from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402
from uvg_io import read_ply_xyz_rgb, write_ply_xyz_rgb  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--recon-root", required=True)
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--sequences", nargs="+", default=["TicTacToe", "VictoryHeart"])
    p.add_argument("--max-frames", type=int, default=15)
    p.add_argument("--out-root", required=True)
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/icp_official_upper_bound.json"))
    args = p.parse_args()

    with open(args.cg_list, encoding="utf-8") as f:
        all_cg = [ln.strip() for ln in f if ln.strip()]

    results = []
    for seq in args.sequences:
        cg_paths = [p for p in all_cg if f"/{seq}/" in p][: args.max_frames]
        pairs = [
            (recon_path_from_cg(cg, args.recon_root), cg)
            for cg in cg_paths
        ]
        est = estimate_sequence_correction_from_he(pairs, method="icp", max_corr=500.0)
        seq_out = os.path.join(args.out_root, seq)
        for cg in cg_paths:
            src = recon_path_from_cg(cg, args.recon_root)
            dst = recon_path_from_cg(cg, seq_out)
            if not os.path.isfile(src):
                continue
            xyz, rgb = read_ply_xyz_rgb(src)
            T = __import__("numpy").array(est["matrix"], dtype=float)
            xyz2 = apply_coord_correction(xyz, T)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            write_ply_xyz_rgb(dst, xyz2, rgb)

        m = mean_chamfer_pairs(recon_official_pairs(seq_out, [(c, c) for c in cg_paths]))
        results.append({"sequence": seq, "icp_to_official_upper_bound": m, "correction": est})

    weights = {"TicTacToe": 165, "VictoryHeart": 197}
    num = den = 0
    for r in results:
        cd = r["icp_to_official_upper_bound"].get("mean_cd_l1")
        if cd is not None:
            w = weights.get(r["sequence"], 1)
            num += cd * w
            den += w
    est = num / den if den else None

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "warning": "DEV ONLY — uses official CG for ICP; not valid for submission",
        "estimated_hybrid_upper_bound_mm": est,
        "sequences": results,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"upper_bound_overall": est, "sequences": results}, indent=2)[:3000])


if __name__ == "__main__":
    main()
