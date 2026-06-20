#!/usr/bin/env python3
"""Pick per-sequence enhancement config from val_grid experiment evals."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
GRID_ROOT = os.path.join(GC2026_ROOT, "output", "val_grid")

sys.path.insert(0, SCRIPT_DIR)
from summarize_eval_by_sequence import summarize_records  # noqa: E402


def parse_experiment_tag(tag: str) -> dict:
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
    ckpt = tag.split("_blend")[0].split("_filter")[0].split("_model")[0]
    if not ckpt.endswith(".pth"):
        ckpt = ckpt + ".pth"
    return {
        "checkpoint": ckpt,
        "output_mode": mode,
        "blend_voxel_mm": voxel,
        "use_vision": vision,
        "experiment": tag,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--grid-root", default=GRID_ROOT)
    p.add_argument(
        "--out-json",
        default=os.path.join(GC2026_ROOT, "output", "enhancement_eval", "per_sequence_enh_config.json"),
    )
    p.add_argument("--default-experiment", default="", help="Fallback experiment dir name")
    p.add_argument(
        "--full-per-seq-json",
        default=os.path.join(GC2026_ROOT, "output", "enhancement_eval", "per_sequence_submission_full.json"),
        help="Full-dataset per-seq summary to assign model on negative sequences",
    )
    args = p.parse_args()

    experiments: list[tuple[str, dict, dict[str, dict]]] = []
    for name in sorted(os.listdir(args.grid_root)):
        exp_dir = os.path.join(args.grid_root, name)
        ev = os.path.join(exp_dir, "evaluation_val_n20k.json")
        if not os.path.isfile(ev):
            continue
        with open(ev, "r", encoding="utf-8") as f:
            data = json.load(f)
        per_seq = summarize_records(data.get("records", []))
        cfg = parse_experiment_tag(name)
        experiments.append((name, cfg, per_seq))

    if not experiments:
        raise SystemExit(f"No val grid experiments with evaluation in {args.grid_root}")

    all_seqs = set()
    for _, _, per_seq in experiments:
        all_seqs.update(per_seq.keys())

    default_name = args.default_experiment
    if not default_name:
        default_name = min(
            experiments,
            key=lambda x: float(
                json.load(open(os.path.join(args.grid_root, x[0], "evaluation_val_n20k.json")))["summary"][
                    "mean_enh_cd_l1"
                ]
            ),
        )[0]

    default_cfg = parse_experiment_tag(default_name)
    seq_configs: dict[str, dict] = {}

    for seq in sorted(all_seqs):
        best_delta = None
        best_cfg = None
        for _, cfg, per_seq in experiments:
            if seq not in per_seq:
                continue
            d = per_seq[seq]["mean_delta_cd_l1"]
            if best_delta is None or d > best_delta:
                best_delta = d
                best_cfg = {k: cfg[k] for k in ("output_mode", "blend_voxel_mm", "use_vision", "checkpoint")}
                best_cfg["mean_delta_cd_l1_val"] = d
                best_cfg["source_experiment"] = cfg["experiment"]
        if best_cfg:
            seq_configs[seq] = best_cfg

    if args.full_per_seq_json and os.path.isfile(args.full_per_seq_json):
        with open(args.full_per_seq_json, "r", encoding="utf-8") as f:
            full_data = json.load(f)
        for seq, stats in full_data.get("per_sequence", {}).items():
            delta = float(stats.get("mean_delta_cd_l1", 0.0))
            if seq not in seq_configs and delta > 2.0:
                seq_configs[seq] = {
                    "output_mode": "blend_cg",
                    "blend_voxel_mm": default_cfg["blend_voxel_mm"],
                    "use_vision": default_cfg["use_vision"],
                    "checkpoint": default_cfg["checkpoint"],
                    "mean_delta_cd_l1_full": delta,
                    "source_experiment": default_name,
                }
            elif seq in seq_configs and delta < 0.0:
                seq_configs[seq]["mean_delta_cd_l1_full"] = delta
                seq_configs[seq]["full_negative_note"] = "keep_val_tuned_blend_cg"

    out = {
        "default": {
            "output_mode": default_cfg["output_mode"],
            "blend_voxel_mm": default_cfg["blend_voxel_mm"],
            "use_vision": default_cfg["use_vision"],
            "checkpoint": default_cfg["checkpoint"],
            "source_experiment": default_name,
        },
        "sequences": seq_configs,
        "grid_root": args.grid_root,
        "num_experiments": len(experiments),
    }

    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Written {args.out_json} ({len(seq_configs)} sequences)")


if __name__ == "__main__":
    main()
