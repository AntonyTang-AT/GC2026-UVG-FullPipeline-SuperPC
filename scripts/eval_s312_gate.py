#!/usr/bin/env python3
"""S312 gate evaluation for TicTacToe + VictoryHeart (Val362)."""
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
from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402
from uvg_io import cg_to_he_path, read_ply_xyz  # noqa: E402
from evaluate_uvg import chamfer_symmetric_kdtree  # noqa: E402

import numpy as np

VAL_SEQS = ("TicTacToe", "VictoryHeart")
TT_BASELINE_CD = 532.7
CG_HE_BASELINE = 85.95
ENH_HE_BASELINE = 71.49


def load_cg_list(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


def per_seq_cd(recon_root: str, cg_paths: list[str], n_samples: int) -> dict:
    by_seq: dict[str, list[str]] = defaultdict(list)
    for p in cg_paths:
        for seq in VAL_SEQS:
            if f"/{seq}/" in p:
                by_seq[seq].append(p)
                break
    out = {}
    for seq, paths in by_seq.items():
        pairs = recon_official_pairs(recon_root, [(p, p) for p in paths])
        m = mean_chamfer_pairs(pairs, n_samples=n_samples)
        if m.get("mean_cd_l1") is not None:
            out[seq] = float(m["mean_cd_l1"])
    overall = []
    pairs_all = recon_official_pairs(recon_root, [(p, p) for p in cg_paths])
    m_all = mean_chamfer_pairs(pairs_all, n_samples=n_samples)
    return {
        "per_sequence": out,
        "overall": float(m_all["mean_cd_l1"]) if m_all.get("mean_cd_l1") else None,
        "num_evaluated": m_all.get("num_evaluated", 0),
    }


def _sequence_from_recon_cg(cg_path: str) -> str:
    marker = "/UVG-CWI-DQPC/"
    if marker in cg_path:
        return cg_path.split(marker, 1)[1].split("/")[0]
    parts = cg_path.replace("\\", "/").split("/")
    if len(parts) >= 2:
        return parts[-2]
    return ""


def resolve_enh_path(enh_root: str, recon_cg: str) -> str | None:
    seq = _sequence_from_recon_cg(recon_cg)
    fname = os.path.basename(recon_cg).replace("_CG_", "_ENH_", 1)
    candidates = [
        os.path.join(enh_root, seq, fname),
        os.path.join(enh_root, "output", fname),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def eval_enh_vs_he(
    enh_root: str,
    cg_paths: list[str],
    n_samples: int,
    recon_root: str | None = None,
) -> dict:
    rng = np.random.RandomState(21)
    cg_cd, enh_cd = [], []
    by_seq_cg: dict[str, list] = defaultdict(list)
    by_seq_enh: dict[str, list] = defaultdict(list)
    for off_cg in cg_paths:
        he = cg_to_he_path(off_cg)
        recon_cg = recon_path_from_cg(off_cg, recon_root) if recon_root else off_cg
        enh = resolve_enh_path(enh_root, recon_cg)
        if not os.path.isfile(he) or not enh:
            continue
        he_xyz = read_ply_xyz(he, max_points=100000, rng=rng)
        enh_xyz = read_ply_xyz(enh, max_points=100000, rng=rng)
        cg_xyz = read_ply_xyz(recon_cg, max_points=100000, rng=rng)
        m_enh = chamfer_symmetric_kdtree(enh_xyz, he_xyz, n_samples, rng)
        m_cg = chamfer_symmetric_kdtree(cg_xyz, he_xyz, n_samples, rng)
        enh_cd.append(m_enh["cd_l1"])
        cg_cd.append(m_cg["cd_l1"])
        for seq in VAL_SEQS:
            if f"/{seq}/" in off_cg:
                by_seq_enh[seq].append(m_enh["cd_l1"])
                by_seq_cg[seq].append(m_cg["cd_l1"])
                break
    if not enh_cd:
        return {"num_evaluated": 0}
    return {
        "num_evaluated": len(enh_cd),
        "mean_cg_cd_l1": float(np.mean(cg_cd)),
        "mean_enh_cd_l1": float(np.mean(enh_cd)),
        "mean_improvement_cd_l1": float(np.mean(cg_cd) - np.mean(enh_cd)),
        "per_sequence_enh": {k: float(np.mean(v)) for k, v in by_seq_enh.items()},
        "per_sequence_cg": {k: float(np.mean(v)) for k, v in by_seq_cg.items()},
    }


def gate_stage1(metrics: dict, tt_max_regress_pct: float = 5.0) -> dict:
    overall = metrics.get("overall")
    per = metrics.get("per_sequence", {})
    tt = per.get("TicTacToe")
    vh = per.get("VictoryHeart")
    tt_ok = tt is None or tt <= TT_BASELINE_CD * (1 + tt_max_regress_pct / 100)
    pass_gate = (
        overall is not None
        and overall < 700
        and (vh is None or vh < 850)
        and tt_ok
    )
    return {
        "pass": pass_gate,
        "overall": overall,
        "TicTacToe": tt,
        "VictoryHeart": vh,
        "tt_regress_ok": tt_ok,
        "thresholds": {"overall_lt": 700, "vh_lt": 850, "tt_regress_pct": tt_max_regress_pct},
    }


def gate_stage2(current: dict, baseline: dict, max_degrade_pct: float = 2.0) -> dict:
    cur_o = current.get("overall")
    base_o = baseline.get("overall")
    if cur_o is None or base_o is None:
        return {"pass": False, "reason": "missing_metrics"}
    delta_pct = (cur_o - base_o) / base_o * 100 if base_o > 0 else 0
    improved_seq = False
    for seq in VAL_SEQS:
        c, b = current.get("per_sequence", {}).get(seq), baseline.get("per_sequence", {}).get(seq)
        if c is not None and b is not None and c < b:
            improved_seq = True
    pass_gate = delta_pct <= max_degrade_pct or improved_seq
    return {
        "pass": pass_gate,
        "delta_pct": delta_pct,
        "improved_any_seq": improved_seq,
        "threshold_degrade_pct": max_degrade_pct,
    }


def gate_stage3(metrics: dict, passthrough_enh_cd: float | None = None) -> dict:
    enh = metrics.get("mean_enh_cd_l1")
    cg = metrics.get("mean_cg_cd_l1")
    pass_gate = enh is not None and enh <= CG_HE_BASELINE * 1.05
    if passthrough_enh_cd is not None and enh is not None:
        pass_gate = pass_gate and enh < passthrough_enh_cd
    return {
        "pass": pass_gate,
        "mean_enh_cd_l1": enh,
        "mean_cg_cd_l1": cg,
        "improvement": metrics.get("mean_improvement_cd_l1"),
        "baseline_cg_he": CG_HE_BASELINE,
        "baseline_enh_he": ENH_HE_BASELINE,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["1", "2", "3"], required=True)
    p.add_argument("--recon-root", default=None, help="Stage1/2 recon root")
    p.add_argument("--enh-root", default=None, help="Stage3 ENH root")
    p.add_argument("--baseline-json", default=None, help="Stage2: compare to Stage1 metrics json")
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--max-frames", type=int, default=0)
    p.add_argument("--n-samples", type=int, default=5000)
    p.add_argument("--out-json", default=None)
    args = p.parse_args()

    cg_paths = load_cg_list(args.cg_list)
    if args.max_frames > 0:
        by_seq: dict[str, list[str]] = defaultdict(list)
        for pth in cg_paths:
            for seq in VAL_SEQS:
                if f"/{seq}/" in pth:
                    by_seq[seq].append(pth)
                    break
        cg_paths = []
        n_per = args.max_frames // 2 if args.max_frames >= 2 else args.max_frames
        for seq in VAL_SEQS:
            cg_paths.extend(by_seq[seq][:n_per])

    report: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stage": args.stage,
        "n_frames": len(cg_paths),
    }

    if args.stage in ("1", "2"):
        if not args.recon_root:
            raise SystemExit("--recon-root required for stage 1/2")
        metrics = per_seq_cd(args.recon_root, cg_paths, args.n_samples)
        report["metrics"] = metrics
        if args.stage == "1":
            report["gate"] = gate_stage1(metrics)
        else:
            baseline = {}
            if args.baseline_json and os.path.isfile(args.baseline_json):
                baseline = json.load(open(args.baseline_json, encoding="utf-8")).get("metrics", {})
            report["gate"] = gate_stage2(metrics, baseline)
            report["baseline_metrics"] = baseline
    else:
        if not args.enh_root:
            raise SystemExit("--enh-root required for stage 3")
        metrics = eval_enh_vs_he(args.enh_root, cg_paths, args.n_samples, args.recon_root)
        report["metrics"] = metrics
        report["gate"] = gate_stage3(metrics)

    out = args.out_json or os.path.join(
        GC2026_ROOT, "output/remediation", f"s312_gate_stage{args.stage}.json"
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"out": out, "pass": report["gate"].get("pass")}, indent=2))
    sys.exit(0 if report["gate"].get("pass") else 1)


if __name__ == "__main__":
    main()
