#!/usr/bin/env python3
"""Select val grid winner and apply decision gate (ENH Chamfer < CG with margin)."""
from __future__ import annotations

import argparse
import json
import os

GC2026_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRID_ROOT = os.path.join(GC2026_ROOT, "output", "val_grid")
GATE_MARGIN = 1.0


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--margin", type=float, default=GATE_MARGIN)
    parser.add_argument("--out-json", default=os.path.join(GRID_ROOT, "gate_decision.json"))
    args = parser.parse_args()

    rows = load_summary()
    if not rows:
        raise SystemExit("No val_grid summary.json — run run_val_grid.sh first")

    cg_ref = cg_baseline_enh()
    best = min(rows, key=lambda r: r["mean_enh_cd_l1"])
    improvement_vs_cg = cg_ref - best["mean_enh_cd_l1"]
    passed = improvement_vs_cg >= args.margin

    decision = {
        "gate_passed": passed,
        "margin_required": args.margin,
        "cg_baseline_enh_cd_l1": cg_ref,
        "best_experiment": best["experiment"],
        "best_mean_enh_cd_l1": best["mean_enh_cd_l1"],
        "improvement_vs_cg_baseline": improvement_vs_cg,
        "best_config": _parse_experiment_tag(best["experiment"]),
    }

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(decision, f, indent=2)

    print(json.dumps(decision, indent=2))
    if not passed:
        raise SystemExit(f"Gate FAILED: improvement {improvement_vs_cg:.2f} < margin {args.margin}")


def _parse_experiment_tag(tag: str) -> dict:
    # tartanair_com_blend_cg_v0_vx2.0
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
    if "_v1_" in tag or tag.endswith("_v1_vx"):
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


if __name__ == "__main__":
    main()
