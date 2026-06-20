#!/usr/bin/env python3
"""Open3D post-fix validation on TicTacToe (only seq where Open3D is optimal)."""
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

from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402

SEQ = "TicTacToe"
PY_O3D = os.environ.get("PY_OPEN3D", "python3.12")

# Open3D variants with fixed coord chain (mm auto-detect in uvg_io)
TT_O3D_VARIANTS = [
    ("O0_8cam_seq_only_v2", "open3d", [
        "--transform-mode", "seq_only",
        "--depth-scale", "5000",
        "--multi-camera",
        "--merge-voxel-mm", "2.0",
        "--no-coord-corrections",
    ]),
    ("O1_8cam_seq_only_v3", "open3d", [
        "--transform-mode", "seq_only",
        "--depth-scale", "5000",
        "--multi-camera",
        "--merge-voxel-mm", "3.0",
        "--no-coord-corrections",
    ]),
    ("O2_tsdf_v2", "open3d_tsdf", [
        "--transform-mode", "seq_only",
        "--depth-scale", "5000",
        "--multi-camera",
        "--merge-voxel-mm", "2.0",
        "--no-coord-corrections",
    ]),
    ("O3_tsdf_v3", "open3d_tsdf", [
        "--transform-mode", "seq_only",
        "--depth-scale", "5000",
        "--multi-camera",
        "--merge-voxel-mm", "3.0",
        "--no-coord-corrections",
    ]),
    ("O4_8cam_vh_he", "open3d", [
        "--transform-mode", "seq_only",
        "--depth-scale", "5000",
        "--multi-camera",
        "--merge-voxel-mm", "2.0",
    ]),
]

# Historical probe (pre mm-auto-detect on non-TT; TT was already ~540)
PROBE_BASELINE = {
    "O0_8cam_seq_only_v2": 540.5050862597258,
    "cwipc_on_tt": 843.7516204115602,
}


def sample_tt(cg_list: str, n: int) -> list[str]:
    paths = []
    with open(cg_list, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and f"/{SEQ}/" in ln:
                paths.append(ln)
    return paths if n <= 0 else paths[:n]


def run_variant(tag: str, backend: str, extra: list[str], cg_paths: list[str], out_root: str) -> dict:
    var_root = os.path.join(out_root, tag)
    os.makedirs(var_root, exist_ok=True)
    lst = os.path.join(var_root, "_cg.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")
    cmd = [
        PY_O3D,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list", lst,
        "--out-root", var_root,
        "--backend", backend,
        "--force",
        *extra,
    ]
    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"tag": tag, "backend": backend, "error": (exc.stderr or exc.stdout or str(exc))[:800]}
    m = mean_chamfer_pairs(
        recon_official_pairs(var_root, [(p, p) for p in cg_paths]),
        n_samples=5000,
    )
    return {"tag": tag, "backend": backend, "recon_vs_official": m, "out_root": var_root}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--quick-frames", type=int, default=30)
    p.add_argument("--full-seq", action="store_true")
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/o3d_fixed_tt_validation.json"))
    args = p.parse_args()

    n = 0 if args.full_seq else args.quick_frames
    cg_paths = sample_tt(args.cg_list, n)
    out_root = os.path.join(GC2026_ROOT, "output/remediation/o3d_fixed_tt")

    results = []
    for tag, backend, extra in TT_O3D_VARIANTS:
        print(f"[o3d_tt] {tag} n={len(cg_paths)}", flush=True)
        results.append(run_variant(tag, backend, extra, cg_paths, out_root))

    ranked = sorted(
        [r for r in results if r.get("recon_vs_official", {}).get("mean_cd_l1")],
        key=lambda x: x["recon_vs_official"]["mean_cd_l1"],
    )
    best = ranked[0] if ranked else None

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sequence": SEQ,
        "n_frames": len(cg_paths),
        "coord_chain_fix": "uvg_io transform_matrix mm auto-detect (TT uses meters, unaffected)",
        "probe_historical_baseline": PROBE_BASELINE,
        "best_variant": best,
        "ranked": [
            {
                "tag": r["tag"],
                "backend": r["backend"],
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
        "probe_baseline": PROBE_BASELINE["O0_8cam_seq_only_v2"],
        "out": args.out_json,
    }, indent=2))


if __name__ == "__main__":
    main()
