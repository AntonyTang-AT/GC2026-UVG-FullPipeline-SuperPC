#!/usr/bin/env python3
"""Aggregate per-sequence metrics from evaluate_uvg JSON output."""
from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)


def sequence_from_cg_path(cg_path: str) -> str:
    marker = "/UVG-CWI-DQPC/"
    if marker in cg_path:
        return cg_path.split(marker, 1)[1].split("/")[0]
    return "unknown"


def summarize_records(records: list[dict]) -> dict[str, dict]:
    by_seq: dict[str, list[dict]] = {}
    for r in records:
        seq = sequence_from_cg_path(r.get("cg_path", ""))
        by_seq.setdefault(seq, []).append(r)

    out: dict[str, dict] = {}
    for seq, rows in sorted(by_seq.items()):
        n = len(rows)
        out[seq] = {
            "num_frames": n,
            "mean_delta_cd_l1": sum(r.get("delta_cd_l1", 0.0) for r in rows) / n,
            "mean_cg_cd_l1": sum(r.get("cg_cd_l1", 0.0) for r in rows) / n,
            "mean_enh_cd_l1": sum(r.get("enh_cd_l1", 0.0) for r in rows) / n,
            "mean_enh_accuracy_l1": sum(r.get("enh_accuracy_l1", 0.0) for r in rows) / n,
            "mean_enh_completeness_l1": sum(r.get("enh_completeness_l1", 0.0) for r in rows) / n,
        }
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Per-sequence eval summary")
    p.add_argument("--eval-json", required=True)
    p.add_argument(
        "--out-json",
        default=None,
        help="Default: output/enhancement_eval/per_sequence_<basename>.json",
    )
    args = p.parse_args()

    with open(args.eval_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    records = data.get("records", [])
    per_seq = summarize_records(records)

    deltas = [v["mean_delta_cd_l1"] for v in per_seq.values()]
    summary = {
        "source_eval": os.path.abspath(args.eval_json),
        "num_sequences": len(per_seq),
        "num_evaluated": data.get("summary", {}).get("num_evaluated", len(records)),
        "mean_improvement_cd_l1": data.get("summary", {}).get("mean_improvement_cd_l1"),
        "sequences_positive": sum(1 for d in deltas if d > 0),
        "sequences_negative": sum(1 for d in deltas if d <= 0),
        "per_sequence": per_seq,
    }

    if args.out_json:
        out_path = args.out_json
    else:
        base = os.path.splitext(os.path.basename(args.eval_json))[0]
        out_dir = os.path.join(GC2026_ROOT, "output", "enhancement_eval")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"per_sequence_{base}.json")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Written {out_path} ({len(per_seq)} sequences)")


if __name__ == "__main__":
    main()
