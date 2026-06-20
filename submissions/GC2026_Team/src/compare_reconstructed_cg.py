#!/usr/bin/env python3
"""Compare reconstructed CG PLYs against official CG (v1/v2)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional

import numpy as np
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from evaluate_uvg import chamfer_symmetric_cuda, _get_cuda_chamfer, chamfer_symmetric_numpy  # noqa: E402
from uvg_io import default_cg_version, parse_frame_id, read_ply_xyz, UVG_ROOT_NAME, official_cg_path  # noqa: E402


def recon_path_from_cg(
    cg_path: str,
    recon_root: str,
    recon_version: Optional[str] = None,
    raw_root: Optional[str] = None,
) -> str:
    if recon_version:
        if raw_root is None:
            raw_root = recon_root
            if raw_root.endswith(UVG_ROOT_NAME):
                raw_root = os.path.dirname(raw_root)
        marker = f"/{UVG_ROOT_NAME}/"
        if marker in cg_path:
            seq = cg_path.split(marker, 1)[1].split("/")[0]
        else:
            seq = os.path.basename(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(cg_path))))
            )
        frame_id = parse_frame_id(cg_path)
        resolved = official_cg_path(raw_root, seq, frame_id, recon_version)
        if resolved:
            return resolved

    if f"/{UVG_ROOT_NAME}/" in cg_path:
        rel = cg_path.split(f"/{UVG_ROOT_NAME}/", 1)[1]
        nested = os.path.join(recon_root, rel)
        if os.path.isfile(nested):
            return nested

    seq = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(cg_path)))))
    return os.path.join(recon_root, seq, os.path.basename(cg_path))


def main() -> None:
    p = argparse.ArgumentParser(description="Compare reconstructed vs official CG")
    p.add_argument("--recon-root", required=True)
    p.add_argument(
        "--pairs-file",
        default=os.path.join(GC2026_ROOT, "data/processed/val_pairs_cgv2.txt"),
    )
    p.add_argument("--official-version", default=default_cg_version(), choices=["v1", "v2"])
    p.add_argument(
        "--recon-version",
        default=None,
        choices=["v1", "v2"],
        help="Resolve recon from official CG version (e.g. v1 vs v2 smoke test)",
    )
    p.add_argument("--n-samples", type=int, default=20000)
    p.add_argument("--max-load-points", type=int, default=100000)
    p.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    p.add_argument("--out-json", default=None)
    p.add_argument("--max-samples", type=int, default=0)
    args = p.parse_args()

    chamfer_fn = chamfer_symmetric_cuda if args.device == "cuda" else chamfer_symmetric_numpy
    if args.device == "cuda" and _get_cuda_chamfer() is None:
        chamfer_fn = chamfer_symmetric_numpy

    pairs_path = args.pairs_file
    if not os.path.isfile(pairs_path):
        pairs_path = os.path.join(GC2026_ROOT, "data/processed/val_pairs.txt")

    with open(pairs_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if args.max_samples > 0:
        lines = lines[:args.max_samples]

    rng = np.random.RandomState(21)
    max_load = args.max_load_points if args.max_load_points > 0 else 0
    records = []
    cd_list = []
    ratio_list = []

    for line in tqdm(lines, desc="compare_cg"):
        parts = line.split("\t")
        official_path = parts[0]
        recon_path = recon_path_from_cg(
            official_path,
            args.recon_root,
            recon_version=args.recon_version,
        )
        if not os.path.isfile(recon_path):
            continue
        if not os.path.isfile(official_path):
            continue

        off_xyz = read_ply_xyz(official_path, max_points=max_load, rng=rng)
        rec_xyz = read_ply_xyz(recon_path, max_points=max_load, rng=rng)
        m = chamfer_fn(rec_xyz, off_xyz, args.n_samples, rng)
        cd_list.append(m["cd_l1"])
        n_off, n_rec = off_xyz.shape[0], rec_xyz.shape[0]
        ratio = n_rec / max(n_off, 1)
        ratio_list.append(ratio)

        seq = official_path.split("/UVG-CWI-DQPC/")[1].split("/")[0]
        records.append(
            {
                "sequence": seq,
                "frame_id": parse_frame_id(official_path),
                "official_path": official_path,
                "recon_path": recon_path,
                "cd_l1": m["cd_l1"],
                "n_official": n_off,
                "n_recon": n_rec,
                "point_ratio": ratio,
            }
        )

    summary = {
        "recon_root": args.recon_root,
        "pairs_file": pairs_path,
        "official_version": args.official_version,
        "recon_version": args.recon_version,
        "num_evaluated": len(records),
        "mean_cd_l1": float(np.mean(cd_list)) if cd_list else None,
        "mean_point_ratio": float(np.mean(ratio_list)) if ratio_list else None,
        "n_samples": args.n_samples,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    out = args.out_json or os.path.join(args.recon_root, "compare_official_cg.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f, indent=2)
    print(json.dumps(summary, indent=2))
    print(f"Written: {out}")


if __name__ == "__main__":
    main()
