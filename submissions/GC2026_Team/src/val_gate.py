#!/usr/bin/env python3
"""Select val grid winner with full-dataset and per-sequence constraints."""
from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
GRID_ROOT = os.path.join(GC2026_ROOT, "output", "val_grid")
GATE_MARGIN = 1.0

sys.path.insert(0, SCRIPT_DIR)
from summarize_eval_by_sequence import summarize_records  # noqa: E402


def load_summary() -> list[dict]:
    path = os.path.join(GRID_ROOT, "summary.json")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cg_baseline_enh() -> float:
    p = os.path.join(GC2026_ROOT, "output/baselines/val_cg_baseline_n20k.json")
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            return float(json.load(f)["summary"]["mean_enh_cd_l1"])
    return 85.96


def eval_per_sequence(eval_path: str) -> dict[str, dict]:
    if not os.path.isfile(eval_path):
        return {}
    with open(eval_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return summarize_records(data.get("records", []))


def parse_experiment_tag(tag: str) -> dict:
    parts = tag.split("_")
    ckpt = "_".join(parts[:2]) if len(parts) >= 2 else tag
    mode = "blend_cg"
    vision = 0
    voxel = 2.0
    if "blend_cg" in tag:
        mode = "blend_cg"
    elif "filter_cg" in tag:
        mode = "filter_cg"
    elif "model" in tag:
        mode = "model"
    if "_v1_" in tag:
        vision = 1
    for seg in tag.split("_"):
        if seg.startswith("vx"):
            try:
                voxel = float(seg[2:])
            except ValueError:
                pass
    return {
        "checkpoint": ckpt + ".pth",
        "output_mode": mode,
        "use_vision": vision,
        "blend_voxel_mm": voxel,
        "experiment_dir": os.path.join(GRID_ROOT, tag),
    }


def score_candidate(row: dict, cg_ref: float, args) -> tuple[float, dict]:
    tag = row["experiment"]
    exp_dir = os.path.join(GRID_ROOT, tag)
    val_ev = os.path.join(exp_dir, "evaluation_val_n20k.json")
    full_ev = os.path.join(exp_dir, "evaluation_full_n20k.json")

    val_per = eval_per_sequence(val_ev)
    full_per = eval_per_sequence(full_ev)

    val_improve = float(row.get("improvement", cg_ref - row["mean_enh_cd_l1"]))
    full_improve = None
    seq_positive_full = 0
    if full_per:
        deltas = [v["mean_delta_cd_l1"] for v in full_per.values()]
        full_improve = sum(deltas) / len(deltas)
        seq_positive_full = sum(1 for d in deltas if d > 0)

    val_seq_positive = sum(1 for v in val_per.values() if v["mean_delta_cd_l1"] > 0)
    val_seq_total = len(val_per)

    penalty = 0.0
    if val_improve < args.margin:
        penalty += 1000.0
    if full_improve is not None and full_improve < args.min_full_improve:
        penalty += 500.0
    if full_per and seq_positive_full < args.min_full_seq_positive:
        penalty += 200.0

    score = float(row["mean_enh_cd_l1"]) + penalty
    meta = {
        "val_improvement": val_improve,
        "full_improvement": full_improve,
        "val_sequences_positive": val_seq_positive,
        "val_sequences_total": val_seq_total,
        "full_sequences_positive": seq_positive_full,
        "full_sequences_total": len(full_per),
    }
    return score, meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--margin", type=float, default=GATE_MARGIN)
    parser.add_argument("--min-full-improve", type=float, default=0.0)
    parser.add_argument("--min-full-seq-positive", type=int, default=6)
    parser.add_argument("--cg-version", default=os.environ.get("UVG_CG_VERSION", "v2"))
    parser.add_argument("--out-json", default=os.path.join(GRID_ROOT, "gate_decision.json"))
    args = parser.parse_args()

    rows = load_summary()
    if not rows:
        raise SystemExit("No val_grid summary.json — run run_val_grid.sh first")

    cg_ref = cg_baseline_enh()
    scored = []
    for row in rows:
        score, meta = score_candidate(row, cg_ref, args)
        scored.append((score, row, meta))

    scored.sort(key=lambda x: x[0])
    best_score, best, best_meta = scored[0]

    val_per = eval_per_sequence(os.path.join(GRID_ROOT, best["experiment"], "evaluation_val_n20k.json"))
    full_per = eval_per_sequence(
        os.path.join(GRID_ROOT, best["experiment"], "evaluation_full_n20k.json")
    )

    improvement_vs_cg = cg_ref - best["mean_enh_cd_l1"]
    passed = improvement_vs_cg >= args.margin
    if best_meta.get("full_improvement") is not None:
        passed = passed and best_meta["full_improvement"] >= args.min_full_improve
    if best_meta.get("full_sequences_total", 0) > 0:
        passed = passed and best_meta["full_sequences_positive"] >= args.min_full_seq_positive

    rgbd_meta_path = os.path.join(GC2026_ROOT, "data/processed/rgbd_pairs_meta.json")
    rgbd_mapped = 0
    if os.path.isfile(rgbd_meta_path):
        with open(rgbd_meta_path, "r", encoding="utf-8") as f:
            rgbd_mapped = int(json.load(f).get("mapped", 0))

    decision = {
        "gate_passed": passed,
        "margin_required": args.margin,
        "cg_baseline_enh_cd_l1": cg_ref,
        "best_experiment": best["experiment"],
        "best_mean_enh_cd_l1": best["mean_enh_cd_l1"],
        "improvement_vs_cg_baseline": improvement_vs_cg,
        "cg_version": args.cg_version,
        "rgbd_pairs_mapped": rgbd_mapped,
        "gate_constraints": {
            "min_full_improve": args.min_full_improve,
            "min_full_seq_positive": args.min_full_seq_positive,
        },
        "best_config": parse_experiment_tag(best["experiment"]),
        "per_sequence_val": val_per,
        "per_sequence_full": full_per,
        "selection_meta": best_meta,
    }

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(decision, f, indent=2)

    print(json.dumps({k: decision[k] for k in decision if k not in ("per_sequence_val", "per_sequence_full")}, indent=2))
    if not passed:
        raise SystemExit(
            f"Gate FAILED: val improve={improvement_vs_cg:.2f} full={best_meta.get('full_improvement')}"
        )


if __name__ == "__main__":
    main()
