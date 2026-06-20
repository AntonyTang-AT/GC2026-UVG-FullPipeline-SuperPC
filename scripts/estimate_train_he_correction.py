#!/usr/bin/env python3
"""Estimate global HE-ICP correction from train probe recons (for cross-seq transfer to VH)."""
from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from coord_correction import average_rigid_transforms, estimate_sequence_correction_from_he, icp_rigid_transform  # noqa: E402
from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from uvg_io import cg_to_he_path, read_ply_xyz  # noqa: E402

TRAIN_SEQS = [
    "BlueSpeech", "BlueVolley", "BouncingBlue", "FitFluencer", "GoodVision",
    "Mannequin", "OrangeKettlebell", "PinkNoir", "TrumanShow", "VirtualLife",
]
PROBE_ROOT = os.path.join(GC2026_ROOT, "output/remediation/probe")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/coord_corrections_train_global.json"))
    p.add_argument("--max-frames-per-seq", type=int, default=4)
    args = p.parse_args()

    all_T = []
    per_seq = {}
    for seq in TRAIN_SEQS:
        recon_root = os.path.join(PROBE_ROOT, seq, "D_cwipc")
        cg_list = os.path.join(GC2026_ROOT, "data/processed/train_cg_only_cgv2.txt")
        paths = []
        with open(cg_list, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln and f"/{seq}/" in ln:
                    paths.append(ln)
        paths = paths[: args.max_frames_per_seq]
        pairs = []
        for cg in paths:
            recon = recon_path_from_cg(cg, recon_root)
            he = cg_to_he_path(cg)
            if os.path.isfile(recon) and os.path.isfile(he):
                pairs.append((recon, he))
        if not pairs:
            continue
        est = estimate_sequence_correction_from_he(pairs, method="icp")
        if est.get("matrix"):
            import numpy as np
            all_T.append(np.array(est["matrix"], dtype=float))
            per_seq[seq] = est

    global_T = average_rigid_transforms(all_T).tolist() if all_T else None
    out = {
        "meta": {"source": "train_probe_D_cwipc", "n_sequences": len(per_seq), "method": "icp_to_he"},
        "global": {
            "matrix": global_T,
            "n_seq_used": len(all_T),
        },
        "per_sequence": per_seq,
        "sequences": {
            "VictoryHeart": {"matrix": global_T, "method": "train_global_transfer", "note": "apply global to VH"},
        },
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps({"out": args.out_json, "n_seq": len(all_T)}, indent=2))


if __name__ == "__main__":
    main()
