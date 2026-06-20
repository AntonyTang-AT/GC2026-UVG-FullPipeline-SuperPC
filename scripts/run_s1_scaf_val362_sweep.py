#!/usr/bin/env python3
"""Stage1 SCAF (open3d_cwipc_mc) sweep vs PGDR hybrid baseline on Val362 TT+VH."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402

PY_O3D = os.environ.get("PY_OPEN3D", "python3.12")
VAL_SEQS = ("TicTacToe", "VictoryHeart")


def sample_frames(cg_list: str, n_per_seq: int) -> tuple[list[str], list[str], list[str]]:
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
    if n_per_seq > 0:
        tt, vh = tt[:n_per_seq], vh[:n_per_seq]
        all_p = tt + vh
    return tt, vh, all_p


def run_variant(
    tag: str,
    backend: str,
    cg_paths: list[str],
    extra: list[str],
    sweep_root: str,
    stage1_config: str | None,
) -> dict:
    out_root = os.path.join(sweep_root, tag)
    os.makedirs(out_root, exist_ok=True)
    lst = os.path.join(out_root, "_cg.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")
    cmd = [
        PY_O3D,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list", lst,
        "--out-root", out_root,
        "--backend", backend,
        "--force",
        "--no-coord-corrections",
        *extra,
    ]
    if stage1_config and os.path.isfile(stage1_config):
        cmd.extend(["--stage1-config", stage1_config])
    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"tag": tag, "backend": backend, "error": (exc.stderr or exc.stdout or str(exc))[:800]}
    per_seq = {}
    by_seq: dict[str, list[str]] = defaultdict(list)
    for p in cg_paths:
        for seq in VAL_SEQS:
            if f"/{seq}/" in p:
                by_seq[seq].append(p)
                break
    for seq, paths in by_seq.items():
        m = mean_chamfer_pairs(recon_official_pairs(out_root, [(p, p) for p in paths]), n_samples=5000)
        if m.get("mean_cd_l1") is not None:
            per_seq[seq] = float(m["mean_cd_l1"])
    m_all = mean_chamfer_pairs(
        recon_official_pairs(out_root, [(p, p) for p in cg_paths]),
        n_samples=5000,
    )
    return {
        "tag": tag,
        "backend": backend,
        "out_root": out_root,
        "recon_vs_official": m_all,
        "per_sequence_cd": per_seq,
        "overall_cd": m_all.get("mean_cd_l1"),
    }


def build_variants(stage1_config: str) -> list[tuple[str, str, list[str], list[str] | None]]:
    """tag, backend, extra args, seq_filter: tt|vh|None(all)"""
    cfg = stage1_config
    return [
        ("B0_hybrid_baseline", "hybrid", ["--multi-camera"], None),
        ("S1_scaf_ds5000", "open3d_cwipc_mc", ["--multi-camera", "--depth-scale", "5000"], None),
        ("S2_scaf_ds2500", "open3d_cwipc_mc", ["--multi-camera", "--depth-scale", "2500"], None),
        ("S3_scaf_ds1000", "open3d_cwipc_mc", ["--multi-camera", "--depth-scale", "1000"], None),
        ("S4_scaf_tt_ds5000", "open3d_cwipc_mc", ["--multi-camera", "--depth-scale", "5000"], ["tt"]),
        ("S5_scaf_vh_ds5000", "open3d_cwipc_mc", ["--multi-camera", "--depth-scale", "5000"], ["vh"]),
        ("S6_scaf_vh_ds2500", "open3d_cwipc_mc", ["--multi-camera", "--depth-scale", "2500"], ["vh"]),
    ]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--frames-per-seq", type=int, default=15)
    p.add_argument("--full-seq", action="store_true")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument(
        "--stage1-config",
        default=os.path.join(GC2026_ROOT, "output/remediation/stage1_config.json"),
    )
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/s1_scaf_sweep.json"))
    args = p.parse_args()

    n = 0 if args.full_seq else args.frames_per_seq
    tt_paths, vh_paths, all_paths = sample_frames(args.cg_list, n)
    sweep_root = os.path.join(GC2026_ROOT, "output/remediation/s1_scaf_sweep")

    jobs = []
    for tag, backend, extra, seq_filter in build_variants(args.stage1_config):
        if seq_filter == ["tt"]:
            paths = tt_paths
        elif seq_filter == ["vh"]:
            paths = vh_paths
        else:
            paths = all_paths
        if not paths:
            continue
        jobs.append((tag, backend, paths, extra))

    results = []
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {
            ex.submit(
                run_variant, tag, backend, paths, extra, sweep_root, args.stage1_config
            ): tag
            for tag, backend, paths, extra in jobs
        }
        for fut in as_completed(futs):
            tag = futs[fut]
            print(f"[s1_scaf] done {tag}", flush=True)
            results.append(fut.result())

    baseline = next((r for r in results if r.get("tag") == "B0_hybrid_baseline"), None)
    base_per = baseline.get("per_sequence_cd", {}) if baseline else {}

    scaf_wins = []
    for r in results:
        if not r.get("tag", "").startswith("S"):
            continue
        per = r.get("per_sequence_cd", {})
        for seq in VAL_SEQS:
            if seq not in per or seq not in base_per:
                continue
            if per[seq] <= base_per[seq] * 1.01:
                scaf_wins.append({
                    "tag": r["tag"],
                    "sequence": seq,
                    "cd": per[seq],
                    "baseline_cd": base_per[seq],
                })

    ranked = sorted(
        [r for r in results if r.get("overall_cd")],
        key=lambda x: x["overall_cd"],
    )

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_frames_per_seq": len(tt_paths),
        "baseline": baseline,
        "best_overall": ranked[0] if ranked else None,
        "scaf_wins_vs_baseline": scaf_wins,
        "ranked": [{"tag": r["tag"], "overall_cd": r["overall_cd"], "per_sequence_cd": r.get("per_sequence_cd")} for r in ranked],
        "results": results,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({
        "best": ranked[0]["tag"] if ranked else None,
        "best_cd": ranked[0]["overall_cd"] if ranked else None,
        "scaf_wins": len(scaf_wins),
        "out": args.out_json,
    }, indent=2))


if __name__ == "__main__":
    main()
