#!/usr/bin/env python3
"""Gate evaluation for CWIPC-Native pipeline (primary: recon vs HE)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from diagnose_stage1 import build_official_pairs, mean_chamfer_pairs, recon_he_pairs, recon_official_pairs  # noqa: E402
from eval_s312_gate import eval_enh_vs_he, resolve_enh_path  # noqa: E402

VAL_SEQS = ("TicTacToe", "VictoryHeart")
PGDR_BASELINE_HE = {"overall": None, "TicTacToe": None, "VictoryHeart": None}


def load_json(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def per_seq_metrics(recon_root: str, cg_paths: list[str], n_samples: int, vs_he: bool) -> dict:
    pairs_file = os.path.join(GC2026_ROOT, "data/processed/val_pairs_cgv2.txt")
    off_pairs = build_official_pairs(pairs_file, max_samples=0)
    cg_set = set(cg_paths)
    off_pairs = [(c, h) for c, h in off_pairs if c in cg_set]
    if vs_he:
        pairs = recon_he_pairs(recon_root, off_pairs)
    else:
        pairs = recon_official_pairs(recon_root, [(c, c) for c, _ in off_pairs])
    m = mean_chamfer_pairs(pairs, n_samples=n_samples)
    by_seq: dict[str, list[float]] = defaultdict(list)
    rng_pairs = pairs
    import numpy as np
    from evaluate_uvg import chamfer_symmetric_kdtree
    from uvg_io import read_ply_xyz

    rng = np.random.RandomState(21)
    for recon, ref in rng_pairs:
        if not os.path.isfile(recon) or not os.path.isfile(ref):
            continue
        a = read_ply_xyz(recon, max_points=100000, rng=rng)
        b = read_ply_xyz(ref, max_points=100000, rng=rng)
        cd = chamfer_symmetric_kdtree(a, b, n_samples, rng)["cd_l1"]
        for seq in VAL_SEQS:
            if f"/{seq}/" in recon:
                by_seq[seq].append(cd)
                break
    return {
        "overall": m.get("mean_cd_l1"),
        "mean_accuracy_l1": m.get("mean_accuracy_l1"),
        "mean_completeness_l1": m.get("mean_completeness_l1"),
        "num_evaluated": m.get("num_evaluated", 0),
        "per_sequence": {k: float(sum(v) / len(v)) for k, v in by_seq.items()},
    }


def gate_recon(metrics_he: dict, baseline_he: dict, min_improve_pct: float = 2.0) -> dict:
    cur = metrics_he.get("overall")
    base = baseline_he.get("overall")
    if cur is None or base is None:
        return {"pass": False, "reason": "missing_overall"}
    improve_pct = (base - cur) / base * 100 if base > 0 else 0
    seq_improved = any(
        metrics_he.get("per_sequence", {}).get(s, 1e9) < baseline_he.get("per_sequence", {}).get(s, 1e9)
        for s in VAL_SEQS
        if s in metrics_he.get("per_sequence", {}) and s in baseline_he.get("per_sequence", {})
    )
    return {
        "pass": improve_pct >= min_improve_pct or seq_improved,
        "improve_pct_vs_baseline": improve_pct,
        "improved_any_seq": seq_improved,
        "overall_he": cur,
        "baseline_overall_he": base,
    }


def sample_val362(cg_list: str, n_per_seq: int) -> list[str]:
    tt, vh, all_p = [], [], []
    with open(cg_list, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            all_p.append(ln)
            if "/TicTacToe/" in ln:
                tt.append(ln)
            elif "/VictoryHeart/" in ln:
                vh.append(ln)
    if n_per_seq <= 0:
        return all_p
    return tt[:n_per_seq] + vh[:n_per_seq]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--recon-root", required=True)
    p.add_argument("--enh-root", default=None)
    p.add_argument("--baseline-recon-root", default=os.path.join(GC2026_ROOT, "output/remediation/stage1_pgdr_val362"))
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--max-frames", type=int, default=0)
    p.add_argument("--n-samples", type=int, default=5000)
    p.add_argument("--out-json", default=None)
    args = p.parse_args()

    cg_paths = sample_val362(args.cg_list, args.max_frames // 2 if args.max_frames > 0 else 0)
    if args.max_frames <= 0:
        cg_paths = sample_val362(args.cg_list, 0)

    baseline_he = per_seq_metrics(args.baseline_recon_root, cg_paths, args.n_samples, vs_he=True)
    metrics_he = per_seq_metrics(args.recon_root, cg_paths, args.n_samples, vs_he=True)
    metrics_off = per_seq_metrics(args.recon_root, cg_paths, args.n_samples, vs_he=False)

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recon_root": args.recon_root,
        "n_frames": len(cg_paths),
        "recon_vs_he": metrics_he,
        "recon_vs_official": metrics_off,
        "baseline_recon_vs_he": baseline_he,
        "gate_recon": gate_recon(metrics_he, baseline_he),
    }

    if args.enh_root:
        enh_m = eval_enh_vs_he(args.enh_root, cg_paths, args.n_samples, args.recon_root)
        report["enh_vs_he"] = enh_m
        report["gate_enh"] = {
            "pass": enh_m.get("mean_enh_cd_l1") is not None and enh_m["mean_enh_cd_l1"] < 200.0,
            "mean_enh_cd_l1": enh_m.get("mean_enh_cd_l1"),
            "target_lt": 200.0,
        }

    out = args.out_json or os.path.join(
        GC2026_ROOT, "output/cwipc_native/native_gate.json"
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    passed = report["gate_recon"].get("pass", False)
    print(json.dumps({"out": out, "pass_recon": passed, "overall_he": metrics_he.get("overall")}, indent=2))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
