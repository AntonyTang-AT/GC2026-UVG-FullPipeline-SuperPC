#!/usr/bin/env python3
"""Parallel cwipc VH optimization: fine-register + config/filter sweeps."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402
from rgbd_to_cg import relax_cwipc_playback_config  # noqa: E402

SEQ = "VictoryHeart"
PY_CW = os.environ.get("PY_CWIPC", "python3.12")
REG_DIR = os.path.join(GC2026_ROOT, "output/remediation/cwipc_registered", SEQ)


def sample_vh(cg_list: str, n: int) -> list[str]:
    paths = []
    with open(cg_list, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and f"/{SEQ}/" in ln:
                paths.append(ln)
    return paths if n <= 0 else paths[:n]


def write_config_variant(base_cfg: str, dest_dir: str, tag: str, relax: bool, extra_proc: dict | None) -> str:
    """Write variant camera config next to bag symlinks (same directory)."""
    os.makedirs(dest_dir, exist_ok=True)
    with open(base_cfg, encoding="utf-8") as f:
        cfg = json.load(f)
    if extra_proc:
        proc = cfg.setdefault("processing", {})
        proc.update(extra_proc)
    if relax:
        cfg = relax_cwipc_playback_config(cfg)
    out = os.path.join(dest_dir, f"{tag}_camera_config.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return out


def run_one(
    tag: str,
    cg_paths: list[str],
    camera_config: str | None,
    extra_rgbd: list[str],
    sweep_root: str,
) -> dict:
    out_root = os.path.join(sweep_root, tag)
    os.makedirs(out_root, exist_ok=True)
    lst = os.path.join(out_root, "_cg.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")
    cmd = [
        PY_CW,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list", lst,
        "--out-root", out_root,
        "--backend", "cwipc",
        "--force",
        *extra_rgbd,
    ]
    if camera_config:
        cmd.extend(["--cwipc-camera-config", camera_config])
    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"tag": tag, "error": (exc.stderr or exc.stdout or str(exc))[:800]}
    m = mean_chamfer_pairs(
        recon_official_pairs(out_root, [(p, p) for p in cg_paths]),
        n_samples=5000,
    )
    return {"tag": tag, "camera_config": camera_config, "recon_vs_official": m}


def build_variants(reg_cfg: str, cfg_root: str) -> list[tuple[str, str | None, list[str]]]:
    """tag, camera_config path, extra rgbd args."""
    variants: list[tuple[str, str | None, list[str]]] = [
        ("C0_baseline_relaxed", None, ["--merge-voxel-mm", "2.0"]),
    ]
    if os.path.isfile(reg_cfg):
        variants.extend([
            ("C1_fine_registered", write_config_variant(reg_cfg, REG_DIR, "C1_fine_relaxed", True, None),
             ["--merge-voxel-mm", "2.0"]),
            ("C2_fine_radius25", write_config_variant(reg_cfg, REG_DIR, "C2_fine_tight_radius", True,
             {"radius_filter": 2.5, "height_min": 0.0, "height_max": 3.0}),
             ["--merge-voxel-mm", "2.0"]),
            ("C3_official_filters", write_config_variant(reg_cfg, REG_DIR, "C3_fine_spatial_on", False, None),
             ["--merge-voxel-mm", "2.0"]),
            ("C4_fine_voxel15", write_config_variant(reg_cfg, REG_DIR, "C1_fine_relaxed", True, None),
             ["--merge-voxel-mm", "1.5"]),
            ("C5_fine_voxel25", write_config_variant(reg_cfg, REG_DIR, "C1_fine_relaxed", True, None),
             ["--merge-voxel-mm", "2.5"]),
        ])
    return variants


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--quick-frames", type=int, default=30)
    p.add_argument("--skip-register", action="store_true")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/cwipc_vh_optimization.json"))
    args = p.parse_args()

    reg_cfg = os.path.join(REG_DIR, f"{SEQ}_camera_config.json")
    if not args.skip_register and not os.path.isfile(reg_cfg):
        subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "run_cwipc_fine_register.py"), "--sequence", SEQ],
            check=True,
            cwd=GC2026_ROOT,
        )

    cg_paths = sample_vh(args.cg_list, args.quick_frames)
    sweep_root = os.path.join(GC2026_ROOT, "output/remediation/cwipc_vh_sweep")
    cfg_root = REG_DIR
    variants = build_variants(reg_cfg, cfg_root)

    results = []
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {
            ex.submit(run_one, tag, cg_paths, cc, extra, sweep_root): tag
            for tag, cc, extra in variants
        }
        for fut in as_completed(futs):
            tag = futs[fut]
            print(f"[cwipc_opt] done {tag}", flush=True)
            results.append(fut.result())

    ranked = sorted(
        [r for r in results if r.get("recon_vs_official", {}).get("mean_cd_l1")],
        key=lambda x: x["recon_vs_official"]["mean_cd_l1"],
    )
    best = ranked[0] if ranked else None
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sequence": SEQ,
        "n_frames": len(cg_paths),
        "registered_config": reg_cfg if os.path.isfile(reg_cfg) else None,
        "best": best,
        "ranked": [
            {
                "tag": r["tag"],
                "cd": r["recon_vs_official"]["mean_cd_l1"],
                "accuracy": r["recon_vs_official"].get("mean_accuracy_l1"),
                "completeness": r["recon_vs_official"].get("mean_completeness_l1"),
            }
            for r in ranked
        ],
        "results": results,
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({
        "best": best["tag"] if best else None,
        "best_cd": best["recon_vs_official"]["mean_cd_l1"] if best else None,
        "baseline_cd": next(
            (r["recon_vs_official"]["mean_cd_l1"] for r in results if r.get("tag") == "C0_baseline_relaxed"),
            None,
        ),
        "out": args.out_json,
    }, indent=2))


if __name__ == "__main__":
    main()
