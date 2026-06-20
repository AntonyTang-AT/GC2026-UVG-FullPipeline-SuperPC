#!/usr/bin/env python3
"""Build per-sequence enhancement config from recon vs official CG compare stats."""
from __future__ import annotations

import argparse
import json
import os

GC2026_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--compare-json",
        default=os.path.join(GC2026_ROOT, "output", "cg_recon_eval", "val_compare_cgv2.json"),
    )
    p.add_argument(
        "--out-json",
        default=os.path.join(GC2026_ROOT, "output", "enhancement_eval", "recon_enh_config.json"),
    )
    p.add_argument("--high-cd-threshold-mm", type=float, default=40.0)
    p.add_argument("--low-cd-threshold-mm", type=float, default=15.0)
    args = p.parse_args()

    if not os.path.isfile(args.compare_json):
        raise SystemExit(f"Compare JSON not found: {args.compare_json}")

    with open(args.compare_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    records = data.get("records", [])

    by_seq: dict[str, list[float]] = {}
    for r in records:
        seq = r.get("sequence", "unknown")
        by_seq.setdefault(seq, []).append(float(r.get("cd_l1", 0.0)))

    seq_configs: dict[str, dict] = {}
    for seq, cds in sorted(by_seq.items()):
        mean_cd = sum(cds) / len(cds)
        if mean_cd >= args.high_cd_threshold_mm:
            cfg = {"output_mode": "blend_cg", "blend_voxel_mm": 3.0, "mean_recon_cd_l1": mean_cd}
        elif mean_cd <= args.low_cd_threshold_mm:
            cfg = {"output_mode": "model", "blend_voxel_mm": 2.0, "mean_recon_cd_l1": mean_cd}
        else:
            cfg = {"output_mode": "blend_cg", "blend_voxel_mm": 2.0, "mean_recon_cd_l1": mean_cd}
        seq_configs[seq] = cfg

    out = {
        "default": {"output_mode": "blend_cg", "blend_voxel_mm": 2.5},
        "sequences": seq_configs,
        "compare_json": os.path.abspath(args.compare_json),
        "thresholds": {"high_mm": args.high_cd_threshold_mm, "low_mm": args.low_cd_threshold_mm},
    }

    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Written {args.out_json} ({len(seq_configs)} sequences)")


if __name__ == "__main__":
    main()
