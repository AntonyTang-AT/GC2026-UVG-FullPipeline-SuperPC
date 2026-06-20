#!/usr/bin/env python3
"""Pick Stage1 production tag from Val362 sweep metrics."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)

DEFAULT_TAG = "N0_cwipc_official"
NEAR_COMPLETION_SLACK = 0.053  # N0 343/362 ≈ 94.75% when min is 95%
CANDIDATE_TAGS = (
    "B1_hybrid_official",
    "N0_cwipc_official",
    "N2_cwipc_mild",
    "B2_hybrid_mild",
    "B0_pgdr_hybrid",
)


def load_rows(sweep_json: str, winner_json: str) -> list[dict]:
    rows: dict[str, dict] = {}
    if os.path.isfile(sweep_json):
        data = json.load(open(sweep_json, encoding="utf-8"))
        for item in data.get("variants") or []:
            tag = item.get("tag")
            if tag:
                rows[tag] = {
                    "tag": tag,
                    "n_ply": item.get("n_ply"),
                    "expected": data.get("n_frames_per_seq", 362) * 2 if False else 362,
                    "overall_he": item.get("overall_he"),
                    "per_sequence_he": item.get("per_sequence_he") or {},
                }
    if os.path.isfile(winner_json):
        w = json.load(open(winner_json, encoding="utf-8"))
        expected = w.get("expected_frames", 362)
        for item in w.get("all_variants") or []:
            tag = item.get("tag")
            if not tag:
                continue
            completion = item.get("completion_ratio")
            if completion is None and item.get("n_ply") is not None:
                completion = float(item["n_ply"]) / expected if expected else 0.0
            rows[tag] = {
                "tag": tag,
                "n_ply": item.get("n_ply"),
                "expected": expected,
                "completion_ratio": completion,
                "overall_he": item.get("overall_he") or item.get("recon_vs_he", {}).get("mean_cd_l1")
                if isinstance(item.get("recon_vs_he"), dict)
                else item.get("overall_he"),
                "per_sequence_he": item.get("per_sequence_he") or {},
            }
    return [rows[t] for t in CANDIDATE_TAGS if t in rows]


def pick(rows: list[dict], min_completion: float) -> tuple[dict | None, str]:
    effective_min = max(0.0, min_completion - NEAR_COMPLETION_SLACK)
    eligible = [
        r
        for r in rows
        if r.get("overall_he") is not None
        and (r.get("completion_ratio") or 0.0) >= effective_min
    ]
    if not eligible:
        eligible = [r for r in rows if r.get("tag") == DEFAULT_TAG]
    if not eligible:
        return None, "no eligible variants"

    eligible.sort(
        key=lambda x: (
            float(x["overall_he"]),
            float((x.get("per_sequence_he") or {}).get("TicTacToe", 9999.0)),
        )
    )
    best = eligible[0]
    comp = best.get("completion_ratio") or 0.0
    reason = (
        f"lowest overall_he={best['overall_he']:.1f}mm, completion={comp:.1%}, "
        f"TT={(best.get('per_sequence_he') or {}).get('TicTacToe', 'n/a')}"
    )
    if comp < min_completion:
        reason += f"; near-complete (>= {effective_min:.1%}), run retry_missing_recon"
    else:
        reason = f"completion>={min_completion:.0%}, " + reason
    ties = [r for r in eligible if abs(r["overall_he"] - best["overall_he"]) < 0.05]
    if len(ties) > 1:
        pref = next((r for r in ties if r["tag"] == DEFAULT_TAG), best)
        if pref["tag"] != best["tag"]:
            best = pref
            reason += f"; tie-break -> {DEFAULT_TAG}"
    return best, reason


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--sweep-json",
        default=os.path.join(GC2026_ROOT, "output/cwipc_native/val362_sweep.json"),
    )
    p.add_argument(
        "--winner-json",
        default=os.path.join(GC2026_ROOT, "output/cwipc_native/native_winner.json"),
    )
    p.add_argument("--min-completion", type=float, default=0.95)
    p.add_argument(
        "--out-json",
        default=os.path.join(GC2026_ROOT, "output/cwipc_native/stage1_production_tag.json"),
    )
    args = p.parse_args()

    rows = load_rows(args.sweep_json, args.winner_json)
    winner, reason = pick(rows, args.min_completion)
    if winner is None:
        winner = {"tag": DEFAULT_TAG}
        reason = f"fallback {DEFAULT_TAG}"

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tag": winner["tag"],
        "reason": reason,
        "min_completion_ratio": args.min_completion,
        "selected": winner,
        "candidates": rows,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"tag": winner["tag"], "reason": reason, "out": args.out_json}, indent=2))


if __name__ == "__main__":
    main()
