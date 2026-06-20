#!/usr/bin/env python3
"""Pick CWIPC-Native sweep winner: completion ratio + recon vs HE."""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from run_cwipc_native_val362 import eval_recon, sample_frames  # noqa: E402

DEFAULTS = os.path.join(GC2026_ROOT, "output/cwipc_native/native_defaults.json")


def count_expected(cg_list: str) -> int:
    with open(cg_list, encoding="utf-8") as f:
        return sum(1 for ln in f if ln.strip() and not ln.startswith("#"))


def count_ply(recon_root: str) -> int:
    n = 0
    for root, _dirs, files in os.walk(recon_root):
        n += sum(1 for f in files if f.endswith(".ply"))
    return n


def _eval_variant(tag_dir: str, cg_paths: list[str]) -> dict:
    try:
        return eval_recon(tag_dir, cg_paths)
    except Exception as exc:
        return {"error": str(exc)[:200]}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sweep-root", default=os.path.join(GC2026_ROOT, "output/cwipc_native/val362_sweep"))
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--min-completion", type=float, default=0.95)
    p.add_argument("--prefer-tag", default="")
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/cwipc_native/native_winner.json"))
    args = p.parse_args()

    defaults = json.load(open(DEFAULTS, encoding="utf-8")) if os.path.isfile(DEFAULTS) else {}
    if defaults:
        if not args.prefer_tag:
            args.prefer_tag = defaults.get("production_winner_tag", "")
        if args.min_completion == 0.95:
            args.min_completion = float(defaults.get("min_completion_ratio", 0.95))

    expected = count_expected(args.cg_list)
    cg_paths = sample_frames(args.cg_list, 0)
    rows = []

    eligible_dirs: list[tuple[str, str, float]] = []
    for name in sorted(os.listdir(args.sweep_root)):
        tag_dir = os.path.join(args.sweep_root, name)
        if not os.path.isdir(tag_dir):
            continue
        n_ply = count_ply(tag_dir)
        completion = n_ply / expected if expected else 0.0
        rows.append({"tag": name, "n_ply": n_ply, "expected": expected, "completion_ratio": completion})
        if n_ply >= max(1, int(expected * args.min_completion)):
            eligible_dirs.append((name, tag_dir, completion))

    if eligible_dirs:
        with ProcessPoolExecutor(max_workers=min(4, len(eligible_dirs))) as pool:
            futs = {
                pool.submit(_eval_variant, tag_dir, cg_paths): (name, completion)
                for name, tag_dir, completion in eligible_dirs
            }
            for fut in as_completed(futs):
                name, completion = futs[fut]
                row = next(r for r in rows if r["tag"] == name)
                metrics = fut.result()
                if "error" in metrics:
                    row["eligible"] = False
                    row["error"] = metrics["error"]
                else:
                    row.update(metrics)
                    row["eligible"] = True
    for row in rows:
        if "eligible" not in row:
            row["eligible"] = False

    eligible = [r for r in rows if r.get("eligible") and r.get("overall_he") is not None]
    eligible.sort(key=lambda x: x["overall_he"])

    winner = eligible[0] if eligible else None
    if args.prefer_tag:
        pref = next((r for r in eligible if r["tag"] == args.prefer_tag), None)
        if pref and winner and pref["overall_he"] <= winner["overall_he"] * 1.05:
            winner = pref

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected_frames": expected,
        "min_completion_ratio": args.min_completion,
        "winner": winner,
        "ranked_eligible": [{"tag": r["tag"], "overall_he": r["overall_he"], "completion_ratio": r["completion_ratio"], "per_sequence_he": r.get("per_sequence_he")} for r in eligible],
        "all_variants": rows,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"winner": winner["tag"] if winner else None, "overall_he": winner.get("overall_he") if winner else None, "out": args.out_json}, indent=2))


if __name__ == "__main__":
    main()
