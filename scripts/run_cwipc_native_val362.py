#!/usr/bin/env python3
"""Val362 experiment sweep: CWIPC-Native variants + PGDR hybrid baseline."""
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

from diagnose_stage1 import build_official_pairs, mean_chamfer_pairs, recon_he_pairs, recon_official_pairs  # noqa: E402

PY = os.environ.get("PY_CWIPC", "python3.12")
VAL_SEQS = ("TicTacToe", "VictoryHeart")
VH_REG_CFG = os.path.join(GC2026_ROOT, "output/remediation/cwipc_registered/VictoryHeart/VictoryHeart_camera_config.json")
STAGE1_CONFIG = os.path.join(GC2026_ROOT, "output/remediation/stage1_config.json")


def sample_frames(cg_list: str, n_per_seq: int) -> list[str]:
    tt, vh = [], []
    with open(cg_list, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if "/TicTacToe/" in ln:
                tt.append(ln)
            elif "/VictoryHeart/" in ln:
                vh.append(ln)
    if n_per_seq <= 0:
        return tt + vh
    return tt[:n_per_seq] + vh[:n_per_seq]


def eval_recon(out_root: str, cg_paths: list[str]) -> dict:
    import numpy as np
    from compare_reconstructed_cg import recon_path_from_cg
    from evaluate_uvg import chamfer_symmetric_kdtree
    from uvg_io import read_ply_xyz

    pairs_file = os.path.join(GC2026_ROOT, "data/processed/val_pairs_cgv2.txt")
    cg_set = set(cg_paths)
    off_pairs = [(c, h) for c, h in build_official_pairs(pairs_file, 0) if c in cg_set]
    m_he = mean_chamfer_pairs(recon_he_pairs(out_root, off_pairs), n_samples=5000)
    m_off = mean_chamfer_pairs(recon_official_pairs(out_root, off_pairs), n_samples=5000)
    per_he: dict[str, float] = {}
    per_off: dict[str, float] = {}
    by_seq_he: dict[str, list] = defaultdict(list)
    by_seq_off: dict[str, list] = defaultdict(list)
    rng = np.random.RandomState(21)
    for cg, he in off_pairs:
        recon = recon_path_from_cg(cg, out_root)
        if not os.path.isfile(recon) or not os.path.isfile(he):
            continue
        a = read_ply_xyz(recon, max_points=100000, rng=rng)
        b_he = read_ply_xyz(he, max_points=100000, rng=rng)
        b_off = read_ply_xyz(cg, max_points=100000, rng=rng)
        for seq in VAL_SEQS:
            if f"/{seq}/" in cg:
                by_seq_he[seq].append(chamfer_symmetric_kdtree(a, b_he, 5000, rng)["cd_l1"])
                by_seq_off[seq].append(chamfer_symmetric_kdtree(a, b_off, 5000, rng)["cd_l1"])
                break
    for seq in VAL_SEQS:
        if by_seq_he[seq]:
            per_he[seq] = float(sum(by_seq_he[seq]) / len(by_seq_he[seq]))
        if by_seq_off[seq]:
            per_off[seq] = float(sum(by_seq_off[seq]) / len(by_seq_off[seq]))
    return {
        "recon_vs_he": m_he,
        "recon_vs_official": m_off,
        "per_sequence_he": per_he,
        "per_sequence_official": per_off,
        "overall_he": m_he.get("mean_cd_l1"),
        "overall_official": m_off.get("mean_cd_l1"),
    }


def run_variant(tag: str, cg_paths: list[str], sweep_root: str, cmd_extra: list[str]) -> dict:
    out_root = os.path.join(sweep_root, tag)
    os.makedirs(out_root, exist_ok=True)
    lst = os.path.join(out_root, "_cg.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")
    cmd = [
        PY,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list", lst,
        "--out-root", out_root,
        "--force",
        "--no-coord-corrections",
        *cmd_extra,
    ]
    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"tag": tag, "error": (exc.stderr or exc.stdout or str(exc))[:1000]}
    metrics = eval_recon(out_root, cg_paths)
    n_ply = sum(
        1
        for _root, _dirs, files in os.walk(out_root)
        for f in files
        if f.endswith(".ply")
    )
    return {"tag": tag, "out_root": out_root, "n_ply": n_ply, **metrics}


def build_variants() -> list[tuple[str, list[str]]]:
    """tag, rgbd_to_cg extra args. VH fine-register is in stage1_config for hybrid paths."""
    return [
        ("B0_pgdr_hybrid", [
            "--backend", "hybrid",
            "--stage1-config", STAGE1_CONFIG,
            "--multi-camera",
            "--cwipc-filter-profile", "relaxed",
        ]),
        ("B1_hybrid_official", [
            "--backend", "hybrid",
            "--stage1-config", STAGE1_CONFIG,
            "--multi-camera",
            "--cwipc-filter-profile", "official",
        ]),
        ("B2_hybrid_mild", [
            "--backend", "hybrid",
            "--stage1-config", STAGE1_CONFIG,
            "--multi-camera",
            "--cwipc-filter-profile", "mild",
        ]),
        ("N1_cwipc_relaxed", [
            "--backend", "cwipc",
            "--cwipc-filter-profile", "relaxed",
        ]),
        ("N0_cwipc_official", [
            "--backend", "cwipc",
            "--cwipc-filter-profile", "official",
        ]),
        ("N2_cwipc_mild", [
            "--backend", "cwipc",
            "--cwipc-filter-profile", "mild",
        ]),
    ]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--frames-per-seq", type=int, default=15)
    p.add_argument("--full-seq", action="store_true")
    p.add_argument("--jobs", type=int, default=3)
    p.add_argument("--sweep-root", default=os.path.join(GC2026_ROOT, "output/cwipc_native/val362_sweep"))
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/cwipc_native/val362_sweep.json"))
    args = p.parse_args()

    n = 0 if args.full_seq else args.frames_per_seq
    cg_paths = sample_frames(args.cg_list, n)
    jobs = [(tag, extra) for tag, extra in build_variants()]

    results = []
    # Limit parallel cwipc (bag IO heavy); run 3 at a time
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {
            ex.submit(run_variant, tag, cg_paths, args.sweep_root, extra): tag
            for tag, extra in jobs
        }
        for fut in as_completed(futs):
            tag = futs[fut]
            print(f"[native_sweep] done {tag}", flush=True)
            results.append(fut.result())

    ranked = sorted(
        [r for r in results if r.get("overall_he") is not None],
        key=lambda x: x["overall_he"],
    )
    baseline = next((r for r in results if r.get("tag") == "B0_pgdr_hybrid"), None)
    base_he = baseline.get("overall_he") if baseline else None

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_frames_per_seq": len([p for p in cg_paths if "/TicTacToe/" in p]),
        "baseline": baseline,
        "best_vs_he": ranked[0] if ranked else None,
        "ranked_vs_he": [
            {
                "tag": r["tag"],
                "overall_he": r["overall_he"],
                "overall_official": r.get("overall_official"),
                "per_sequence_he": r.get("per_sequence_he"),
                "delta_he_vs_baseline": (
                    (r["overall_he"] - base_he) / base_he * 100 if base_he and r.get("overall_he") else None
                ),
            }
            for r in ranked
        ],
        "results": results,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({
        "best": ranked[0]["tag"] if ranked else None,
        "best_he": ranked[0]["overall_he"] if ranked else None,
        "baseline_he": base_he,
        "out": args.out_json,
    }, indent=2))


if __name__ == "__main__":
    main()
