#!/usr/bin/env python3
"""VictoryHeart coordinate-chain fix experiments (dev testbed for all future methods)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402

SEQ = "VictoryHeart"
PY_O3D = os.environ.get("PY_OPEN3D", "python3.12")
PY_CW = os.environ.get("PY_CWIPC", "python3.12")

# label, backend, py, extra args
VH_VARIANTS = [
    ("M0_cwipc_baseline", "cwipc", PY_CW, [
        "--merge-voxel-mm", "2.0",
    ]),
    ("M1_o3d_seq_only_fixed_8cam", "open3d", PY_O3D, [
        "--transform-mode", "seq_only",
        "--depth-scale", "5000",
        "--multi-camera",
        "--merge-voxel-mm", "2.0",
    ]),
    ("M2_o3d_cwipc_coords_fixed_8cam", "open3d", PY_O3D, [
        "--transform-mode", "cwipc_coords",
        "--depth-scale", "5000",
        "--multi-camera",
        "--merge-voxel-mm", "2.0",
    ]),
    ("M3_o3d_cwipc_coords_v3", "open3d", PY_O3D, [
        "--transform-mode", "cwipc_coords",
        "--depth-scale", "5000",
        "--multi-camera",
        "--merge-voxel-mm", "3.0",
    ]),
    ("M4_o3d_legacy_fixed_8cam", "open3d", PY_O3D, [
        "--transform-mode", "legacy",
        "--depth-scale", "5000",
        "--multi-camera",
        "--merge-voxel-mm", "2.0",
    ]),
    ("M5_o3d_cwipc_coords_ds1000", "open3d", PY_O3D, [
        "--transform-mode", "cwipc_coords",
        "--depth-scale", "1000",
        "--multi-camera",
        "--merge-voxel-mm", "2.0",
    ]),
    ("M6_cwipc_voxel3", "cwipc", PY_CW, [
        "--merge-voxel-mm", "3.0",
    ]),
]

# Historical probe (broken coord chain, pre-fix code)
PROBE_BASELINE = {
    "M0_cwipc_baseline": 989.4546088696637,
    "M1_o3d_seq_only_broken_8cam": 325629.7298075109,
    "M2_o3d_cwipc_coords_broken_8cam": 325600.6029752457,
}


def sample_vh_cg(cg_list: str, n: int) -> list[str]:
    paths = []
    with open(cg_list, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and f"/{SEQ}/" in ln:
                paths.append(ln)
    return paths if n <= 0 else paths[:n]


def run_variant(
    tag: str,
    cg_paths: list[str],
    out_root: str,
    backend: str,
    extra: list[str],
    py: str,
    coord_corrections: str | None,
) -> dict:
    os.makedirs(out_root, exist_ok=True)
    lst = os.path.join(out_root, "_cg.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")
    cmd = [
        py,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list", lst,
        "--out-root", out_root,
        "--backend", backend,
        "--force",
        *extra,
    ]
    if coord_corrections and os.path.isfile(coord_corrections):
        cmd.extend(["--coord-corrections", coord_corrections])
    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"tag": tag, "error": (exc.stderr or exc.stdout or str(exc))[:800]}
    pairs = recon_official_pairs(out_root, [(p, p) for p in cg_paths])
    m = mean_chamfer_pairs(pairs, n_samples=5000)
    return {"tag": tag, "recon_vs_official": m, "out_root": out_root, "n_frames": len(cg_paths)}


def main() -> None:
    p = argparse.ArgumentParser(description="VH coord-chain fix experiments")
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--quick-frames", type=int, default=20)
    p.add_argument("--full-seq", action="store_true")
    p.add_argument("--coord-corrections", default=os.path.join(GC2026_ROOT, "output/remediation/coord_corrections.json"))
    p.add_argument("--with-he-correction", action="store_true")
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/vh_coord_fix_experiments.json"))
    args = p.parse_args()

    n = 0 if args.full_seq else args.quick_frames
    cg_paths = sample_vh_cg(args.cg_list, n)
    if not cg_paths:
        raise SystemExit(f"No {SEQ} frames in {args.cg_list}")

    cc = args.coord_corrections if args.with_he_correction else None
    sweep_root = os.path.join(GC2026_ROOT, "output/remediation/vh_experiments")
    results = []

    for tag, backend, py, extra in VH_VARIANTS:
        out = os.path.join(sweep_root, tag)
        print(f"[vh_exp] {tag} n={len(cg_paths)}", flush=True)
        results.append(run_variant(tag, cg_paths, out, backend, extra, py, cc))

    ranked = sorted(
        [r for r in results if r.get("recon_vs_official", {}).get("mean_cd_l1") is not None],
        key=lambda x: x["recon_vs_official"]["mean_cd_l1"],
    )
    best = ranked[0] if ranked else None
    baseline_cd = PROBE_BASELINE.get("M0_cwipc_baseline")

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sequence": SEQ,
        "n_frames": len(cg_paths),
        "coord_chain_fix": "uvg_io transform_matrix mm auto-detect + cwipc_coords per-camera",
        "with_he_correction": args.with_he_correction,
        "probe_historical_baseline": PROBE_BASELINE,
        "best_variant": best,
        "results": results,
        "ranked": [
            {
                "tag": r["tag"],
                "cd": r["recon_vs_official"]["mean_cd_l1"],
                "accuracy": r["recon_vs_official"].get("mean_accuracy_l1"),
                "completeness": r["recon_vs_official"].get("mean_completeness_l1"),
            }
            for r in ranked
        ],
        "vs_cwipc_probe": {
            "probe_cwipc_cd": baseline_cd,
            "best_fixed_cd": best["recon_vs_official"]["mean_cd_l1"] if best else None,
            "delta_mm": (
                float(baseline_cd - best["recon_vs_official"]["mean_cd_l1"])
                if best and baseline_cd
                else None
            ),
        },
    }
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps({
        "n_frames": len(cg_paths),
        "best": best["tag"] if best else None,
        "best_cd": best["recon_vs_official"]["mean_cd_l1"] if best else None,
        "probe_cwipc": baseline_cd,
        "out": args.out_json,
    }, indent=2))


if __name__ == "__main__":
    main()
