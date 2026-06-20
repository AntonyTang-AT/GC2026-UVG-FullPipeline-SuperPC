#!/usr/bin/env python3
"""Evaluate Full Pipeline: recon CG baseline + ENH output vs HE GT."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from evaluate_uvg import (  # noqa: E402
    _get_cuda_chamfer,
    chamfer_symmetric_cuda,
    chamfer_symmetric_kdtree,
    chamfer_symmetric_numpy,
)
from uvg_io import cg_to_he_path, parse_frame_id, read_ply_xyz  # noqa: E402


def enh_path_from_recon_cg(recon_cg_path: str, enhanced_root: str) -> str:
    seq = os.path.basename(os.path.dirname(recon_cg_path))
    fname = os.path.basename(recon_cg_path).replace("_CG_", "_ENH_", 1)
    return os.path.join(enhanced_root, seq, fname)


def he_path_from_recon(recon_path: str) -> str:
    seq = os.path.basename(os.path.dirname(recon_path))
    fname = os.path.basename(recon_path).replace("_CG_", "_HE_", 1)
    return os.path.join(
        GC2026_ROOT,
        "data/raw/UVG-CWI-DQPC",
        seq,
        "high-end_capture_system/HE/15fps",
        fname,
    )


def load_pairs(recon_list: str, pairs_file: str | None) -> list[tuple[str, str]]:
    if pairs_file and os.path.isfile(pairs_file):
        lines = []
        with open(pairs_file, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                parts = ln.split("\t")
                recon = parts[0]
                he = parts[1] if len(parts) > 1 and parts[1] else he_path_from_recon(recon)
                lines.append((recon, he))
        return lines

    pairs: list[tuple[str, str]] = []
    with open(recon_list, "r", encoding="utf-8") as f:
        for ln in f:
            recon = ln.strip()
            if not recon or recon.startswith("#"):
                continue
            he = he_path_from_recon(recon)
            pairs.append((recon, he))
    return pairs


def parse_args():
    p = argparse.ArgumentParser(description="Evaluate recon CG + ENH vs HE for Full Pipeline")
    p.add_argument(
        "--recon-list",
        default=os.path.join(GC2026_ROOT, "output/full_pipeline_cg/reconstructed_cg_list.txt"),
        help="One recon CG path per line",
    )
    p.add_argument(
        "--pairs-file",
        default="",
        help="Optional tab-separated recon_cg\\tHE paths (overrides --recon-list HE derivation)",
    )
    p.add_argument("--enhanced-root", required=True)
    p.add_argument("--max-samples", type=int, default=0)
    p.add_argument("--n-samples", type=int, default=20000)
    p.add_argument("--max-load-points", type=int, default=100000)
    p.add_argument("--device", default="cpu", choices=["cuda", "cpu"])
    p.add_argument("--seed", type=int, default=21)
    p.add_argument("--out-json", default=None)
    return p.parse_args()


def main():
    args = parse_args()
    rng = np.random.RandomState(args.seed)
    if args.device == "cuda":
        chamfer_fn = chamfer_symmetric_cuda
        if _get_cuda_chamfer() is None:
            chamfer_fn = chamfer_symmetric_kdtree
    else:
        chamfer_fn = chamfer_symmetric_kdtree

    max_load = args.max_load_points if args.max_load_points > 0 else 0
    pairs = load_pairs(args.recon_list, args.pairs_file or None)
    if args.max_samples > 0:
        pairs = pairs[: args.max_samples]

    records = []
    recon_cd, enh_cd = [], []

    for recon_path, he_path in tqdm(pairs, desc="eval_recon_pipeline"):
        enh_path = enh_path_from_recon_cg(recon_path, args.enhanced_root)
        if not os.path.isfile(he_path):
            continue
        if not os.path.isfile(recon_path):
            continue
        if not os.path.isfile(enh_path):
            continue

        recon_xyz = read_ply_xyz(recon_path, max_points=max_load, rng=rng)
        he_xyz = read_ply_xyz(he_path, max_points=max_load, rng=rng)
        enh_xyz = read_ply_xyz(enh_path, max_points=max_load, rng=rng)

        m_recon = chamfer_fn(recon_xyz, he_xyz, args.n_samples, rng)
        m_enh = chamfer_fn(enh_xyz, he_xyz, args.n_samples, rng)
        recon_cd.append(m_recon["cd_l1"])
        enh_cd.append(m_enh["cd_l1"])

        records.append(
            {
                "frame_id": parse_frame_id(recon_path),
                "recon_path": recon_path,
                "he_path": he_path,
                "enh_path": enh_path,
                "recon_cd_l1": m_recon["cd_l1"],
                "recon_cd_l2": m_recon["cd_l2"],
                "recon_accuracy_l1": m_recon["accuracy_l1"],
                "recon_completeness_l1": m_recon["completeness_l1"],
                "enh_cd_l1": m_enh["cd_l1"],
                "enh_cd_l2": m_enh["cd_l2"],
                "enh_accuracy_l1": m_enh["accuracy_l1"],
                "enh_completeness_l1": m_enh["completeness_l1"],
                "delta_cd_l1": m_recon["cd_l1"] - m_enh["cd_l1"],
            }
        )

    summary = {
        "recon_list": args.recon_list,
        "pairs_file": args.pairs_file or None,
        "enhanced_root": args.enhanced_root,
        "num_evaluated": len(records),
        "mean_recon_cd_l1": float(np.mean(recon_cd)) if recon_cd else None,
        "mean_enh_cd_l1": float(np.mean(enh_cd)) if enh_cd else None,
        "mean_improvement_cd_l1": float(np.mean(recon_cd) - np.mean(enh_cd)) if recon_cd else None,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    out = args.out_json or os.path.join(args.enhanced_root, "evaluation_recon_pipeline.json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f, indent=2)
    print(json.dumps(summary, indent=2))
    print(f"Written: {out}")


if __name__ == "__main__":
    main()
