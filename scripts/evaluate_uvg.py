#!/usr/bin/env python3
"""Evaluate UVG enhanced point clouds against HE ground truth (and CG baseline)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

import numpy as np
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
SUPERPC_ROOT = os.path.join(GC2026_ROOT, "code", "SuperPC")
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, SUPERPC_ROOT)
from uvg_io import cg_to_he_path, read_ply_xyz, parse_frame_id  # noqa: E402

FRAME_RE = re.compile(r"_(\d{4})\.ply$", re.IGNORECASE)

_CUDA_CD = None


def _get_cuda_chamfer():
    global _CUDA_CD
    if _CUDA_CD is not None:
        return _CUDA_CD
    try:
        import torch
        from Chamfer3D.dist_chamfer_3D import chamfer_3DDist

        if not torch.cuda.is_available():
            return None
        _CUDA_CD = (torch, chamfer_3DDist())
        return _CUDA_CD
    except Exception:
        return None


def enh_path_from_cg(cg_path: str, enhanced_root: str) -> str:
    seq = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(cg_path)))))
    fname = os.path.basename(cg_path).replace("_CG_", "_ENH_", 1)
    return os.path.join(enhanced_root, seq, fname)


def subsample_xyz(xyz: np.ndarray, n: int, rng: np.random.RandomState) -> np.ndarray:
    n = min(n, xyz.shape[0])
    if xyz.shape[0] == n:
        return xyz
    idx = rng.choice(xyz.shape[0], size=n, replace=False)
    return xyz[idx]


def chamfer_symmetric_numpy(
    xyz_a: np.ndarray, xyz_b: np.ndarray, n_samples: int, rng: np.random.RandomState
) -> dict:
    a = subsample_xyz(xyz_a.astype(np.float64), n_samples, rng)
    b = subsample_xyz(xyz_b.astype(np.float64), n_samples, rng)
    d = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
    min_a = d.min(axis=1)
    min_b = d.min(axis=0)
    cd_l1 = 0.5 * (min_a.mean() + min_b.mean())
    cd_l2 = 0.5 * (np.mean(min_a ** 2) + np.mean(min_b ** 2))
    return {
        "cd_l1": float(cd_l1),
        "cd_l2": float(cd_l2),
        "accuracy_l1": float(min_a.mean()),
        "completeness_l1": float(min_b.mean()),
        "n_a": int(xyz_a.shape[0]),
        "n_b": int(xyz_b.shape[0]),
    }


def chamfer_symmetric_cuda(
    xyz_a: np.ndarray, xyz_b: np.ndarray, n_samples: int, rng: np.random.RandomState
) -> dict:
    cuda = _get_cuda_chamfer()
    if cuda is None:
        return chamfer_symmetric_numpy(xyz_a, xyz_b, n_samples, rng)
    torch, cd_module = cuda
    a = subsample_xyz(xyz_a, n_samples, rng)
    b = subsample_xyz(xyz_b, n_samples, rng)
    ta = torch.from_numpy(a).float().cuda().unsqueeze(0)
    tb = torch.from_numpy(b).float().cuda().unsqueeze(0)
    cd_p, cd_t, _, _ = cd_module(ta, tb)
    cd_l1 = (
        0.5 * (
            torch.sqrt(torch.clamp(cd_p, min=0.0)).mean()
            + torch.sqrt(torch.clamp(cd_t, min=0.0)).mean()
        )
    ).item()
    cd_l2 = 0.5 * (cd_p.mean().item() + cd_t.mean().item())
    acc_l1 = torch.sqrt(torch.clamp(cd_p, min=0.0)).mean().item()
    comp_l1 = torch.sqrt(torch.clamp(cd_t, min=0.0)).mean().item()
    return {
        "cd_l1": float(cd_l1),
        "cd_l2": float(cd_l2),
        "accuracy_l1": float(acc_l1),
        "completeness_l1": float(comp_l1),
        "n_a": int(xyz_a.shape[0]),
        "n_b": int(xyz_b.shape[0]),
    }


def parse_args():
    p = argparse.ArgumentParser(description="Evaluate enhanced PLY vs HE GT")
    p.add_argument("--pairs-file", default="/root/autodl-tmp/GC2026/data/processed/val_pairs.txt")
    p.add_argument("--enhanced-root", required=True, help="Root with per-sequence ENH PLY folders")
    p.add_argument("--max-samples", type=int, default=0)
    p.add_argument("--out-json", default=None)
    p.add_argument("--n-samples", type=int, default=20000, help="Points per cloud for Chamfer (match dense CG/HE)")
    p.add_argument("--max-load-points", type=int, default=100000, help="Cap points loaded per PLY (0=all)")
    p.add_argument("--device", default="cuda", choices=["cuda", "cpu"], help="Chamfer backend")
    p.add_argument("--seed", type=int, default=21)
    return p.parse_args()


def main():
    args = parse_args()
    rng = np.random.RandomState(args.seed)
    chamfer_fn = chamfer_symmetric_cuda if args.device == "cuda" else chamfer_symmetric_numpy
    if args.device == "cuda" and _get_cuda_chamfer() is None:
        print("[evaluate_uvg] CUDA Chamfer unavailable, falling back to numpy")
        chamfer_fn = chamfer_symmetric_numpy

    max_load = args.max_load_points if args.max_load_points > 0 else 0

    with open(args.pairs_file, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]

    if args.max_samples > 0:
        lines = lines[:args.max_samples]

    records = []
    cg_cd_l1, enh_cd_l1 = [], []
    cg_acc, enh_acc, cg_comp, enh_comp = [], [], [], []

    for line in tqdm(lines, desc="evaluate"):
        parts = line.split("\t")
        cg_path = parts[0]
        he_path = parts[1] if len(parts) > 1 and parts[1] else cg_to_he_path(cg_path)
        enh_path = enh_path_from_cg(cg_path, args.enhanced_root)

        if not os.path.isfile(he_path):
            continue
        if not os.path.isfile(enh_path):
            continue

        cg_xyz = read_ply_xyz(cg_path, max_points=max_load, rng=rng)
        he_xyz = read_ply_xyz(he_path, max_points=max_load, rng=rng)
        enh_xyz = read_ply_xyz(enh_path, max_points=max_load, rng=rng)

        m_cg = chamfer_fn(cg_xyz, he_xyz, args.n_samples, rng)
        m_enh = chamfer_fn(enh_xyz, he_xyz, args.n_samples, rng)
        cg_cd_l1.append(m_cg["cd_l1"])
        enh_cd_l1.append(m_enh["cd_l1"])
        cg_acc.append(m_cg["accuracy_l1"])
        enh_acc.append(m_enh["accuracy_l1"])
        cg_comp.append(m_cg["completeness_l1"])
        enh_comp.append(m_enh["completeness_l1"])

        records.append(
            {
                "frame_id": parse_frame_id(cg_path),
                "cg_path": cg_path,
                "he_path": he_path,
                "enh_path": enh_path,
                "cg_cd_l1": m_cg["cd_l1"],
                "cg_cd_l2": m_cg["cd_l2"],
                "cg_accuracy_l1": m_cg["accuracy_l1"],
                "cg_completeness_l1": m_cg["completeness_l1"],
                "enh_cd_l1": m_enh["cd_l1"],
                "enh_cd_l2": m_enh["cd_l2"],
                "enh_accuracy_l1": m_enh["accuracy_l1"],
                "enh_completeness_l1": m_enh["completeness_l1"],
                "delta_cd_l1": m_cg["cd_l1"] - m_enh["cd_l1"],
            }
        )

    summary = {
        "pairs_file": args.pairs_file,
        "enhanced_root": args.enhanced_root,
        "num_evaluated": len(records),
        "mean_cg_cd_l1": float(np.mean(cg_cd_l1)) if cg_cd_l1 else None,
        "mean_enh_cd_l1": float(np.mean(enh_cd_l1)) if enh_cd_l1 else None,
        "mean_improvement_cd_l1": float(np.mean(cg_cd_l1) - np.mean(enh_cd_l1)) if cg_cd_l1 else None,
        "mean_cg_accuracy_l1": float(np.mean(cg_acc)) if cg_acc else None,
        "mean_enh_accuracy_l1": float(np.mean(enh_acc)) if enh_acc else None,
        "mean_cg_completeness_l1": float(np.mean(cg_comp)) if cg_comp else None,
        "mean_enh_completeness_l1": float(np.mean(enh_comp)) if enh_comp else None,
        "mean_accuracy_l1": float(np.mean(enh_acc)) if enh_acc else None,
        "mean_completeness_l1": float(np.mean(enh_comp)) if enh_comp else None,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    out = args.out_json or os.path.join(args.enhanced_root, "evaluation_summary.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f, indent=2)

    print(json.dumps(summary, indent=2))
    print(f"Written: {out}")


if __name__ == "__main__":
    main()
