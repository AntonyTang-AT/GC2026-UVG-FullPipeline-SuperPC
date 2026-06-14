#!/usr/bin/env python3
"""Temporal stability: adjacent-frame Chamfer variance on val sequences."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
from evaluate_uvg import chamfer_symmetric_cuda, enh_path_from_cg, _get_cuda_chamfer  # noqa: E402
from uvg_io import read_ply_xyz  # noqa: E402

FRAME_RE = re.compile(r"_(\d{4})\.ply$", re.IGNORECASE)


def seq_from_cg(cg_path: str) -> str:
    return os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(cg_path)))))


def frame_num(path: str) -> int:
    m = FRAME_RE.search(path)
    return int(m.group(1)) if m else -1


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only.txt"))
    p.add_argument("--enhanced-root", required=True)
    p.add_argument("--n-samples", type=int, default=10000)
    p.add_argument("--out-json", default=None)
    p.add_argument("--seed", type=int, default=21)
    args = p.parse_args()

    rng = np.random.RandomState(args.seed)
    chamfer_fn = chamfer_symmetric_cuda if _get_cuda_chamfer() else None
    if chamfer_fn is None:
        from evaluate_uvg import chamfer_symmetric_numpy
        chamfer_fn = chamfer_symmetric_numpy

    with open(args.cg_list, "r", encoding="utf-8") as f:
        cg_paths = [ln.strip() for ln in f if ln.strip()]

    by_seq: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for cg in cg_paths:
        enh = enh_path_from_cg(cg, args.enhanced_root)
        if os.path.isfile(enh):
            by_seq[seq_from_cg(cg)].append((frame_num(cg), enh))

    pair_dists = []
    records = []
    for seq, items in sorted(by_seq.items()):
        items.sort(key=lambda x: x[0])
        for i in range(len(items) - 1):
            f0, p0 = items[i]
            f1, p1 = items[i + 1]
            if f1 != f0 + 1:
                continue
            xyz0 = read_ply_xyz(p0, max_points=100000, rng=rng)
            xyz1 = read_ply_xyz(p1, max_points=100000, rng=rng)
            m = chamfer_fn(xyz0, xyz1, args.n_samples, rng)
            pair_dists.append(m["cd_l1"])
            records.append({"sequence": seq, "frame0": f0, "frame1": f1, "cd_l1": m["cd_l1"]})

    summary = {
        "enhanced_root": args.enhanced_root,
        "num_pairs": len(pair_dists),
        "mean_adjacent_cd_l1": float(np.mean(pair_dists)) if pair_dists else None,
        "std_adjacent_cd_l1": float(np.std(pair_dists)) if pair_dists else None,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    out = args.out_json or os.path.join(args.enhanced_root, "temporal_stability.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
