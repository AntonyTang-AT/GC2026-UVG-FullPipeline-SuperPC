#!/usr/bin/env python3
"""Per-sequence Stage1 backend probe: sweep open3d/cwipc variants on a small frame set."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402

VAL_SEQS = {"TicTacToe", "VictoryHeart"}

# (id, backend, transform_mode, depth_scale, multi_camera)
PROBE_CANDIDATES = [
    ("A_open3d_seq_only_sc", "open3d", "seq_only", 5000.0, False),
    ("B_open3d_seq_only_mc", "open3d", "seq_only", 5000.0, True),
    ("C_open3d_legacy_sc", "open3d", "legacy", 1000.0, False),
    ("D_cwipc", "cwipc", "cwipc_coords", 1000.0, False),
]


def sequence_from_cg(cg_path: str) -> str:
    if "/UVG-CWI-DQPC/" in cg_path:
        return cg_path.split("/UVG-CWI-DQPC/")[1].split("/")[0]
    return os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(cg_path)))))


def sample_cg_paths(cg_all: str, seq: str, max_frames: int) -> list[str]:
    paths = []
    with open(cg_all, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if f"/{seq}/" in ln:
                paths.append(ln)
    if max_frames > 0:
        paths = paths[:max_frames]
    return paths


def run_rgbd_to_cg(
    cg_paths: list[str],
    out_dir: str,
    backend: str,
    transform_mode: str,
    depth_scale: float,
    multi_camera: bool,
    merge_voxel_mm: float,
    depth_trunc_mm: float,
    py: str,
) -> dict:
    list_path = os.path.join(out_dir, "_cg_list.txt")
    os.makedirs(out_dir, exist_ok=True)
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")

    cmd = [
        py,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list",
        list_path,
        "--out-root",
        out_dir,
        "--backend",
        backend,
        "--frame-map-mode",
        "even",
        "--depth-scale",
        str(depth_scale),
        "--transform-mode",
        transform_mode,
        "--depth-trunc-mm",
        str(depth_trunc_mm),
        "--merge-voxel-mm",
        str(merge_voxel_mm),
        "--force",
    ]
    if multi_camera:
        cmd.append("--multi-camera")

    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"error": (exc.stderr or exc.stdout or str(exc))[:1200]}

    off_pairs = [(p, p) for p in cg_paths]
    ro_pairs = recon_official_pairs(out_dir, off_pairs)
    m_ro = mean_chamfer_pairs(ro_pairs, n_samples=5000)
    return {"recon_vs_official": m_ro, "sweep_root": out_dir}


def main() -> None:
    p = argparse.ArgumentParser(description="Probe Stage1 backends for one sequence")
    p.add_argument("--sequence", required=True)
    p.add_argument(
        "--cg-all",
        default=os.path.join(GC2026_ROOT, "data/processed/all_cg_only_cgv2.txt"),
    )
    p.add_argument("--max-frames", type=int, default=8)
    p.add_argument("--probe-root", default=os.path.join(GC2026_ROOT, "output/remediation/probe"))
    p.add_argument("--merge-voxel-mm", type=float, default=3.0)
    p.add_argument("--depth-trunc-mm", type=float, default=5000.0)
    p.add_argument("--py-open3d", default=os.environ.get("PY_OPEN3D", "python3.12"))
    p.add_argument("--py-cwipc", default=os.environ.get("PY_CWIPC", "python3.12"))
    args = p.parse_args()

    cg_paths = sample_cg_paths(args.cg_all, args.sequence, args.max_frames)
    if not cg_paths:
        print(json.dumps({"sequence": args.sequence, "error": "no frames"}))
        sys.exit(1)

    seq_dir = os.path.join(args.probe_root, args.sequence)
    os.makedirs(seq_dir, exist_ok=True)

    variants = []
    for cid, backend, tmode, ds, multi in PROBE_CANDIDATES:
        out_dir = os.path.join(seq_dir, cid)
        py = args.py_cwipc if backend == "cwipc" else args.py_open3d
        res = run_rgbd_to_cg(
            cg_paths,
            out_dir,
            backend,
            tmode,
            ds,
            multi,
            args.merge_voxel_mm,
            args.depth_trunc_mm,
            py,
        )
        variants.append(
            {
                "id": cid,
                "backend": backend,
                "transform_mode": tmode,
                "depth_scale": ds,
                "multi_camera": multi,
                **res,
            }
        )

    ranked = sorted(
        [v for v in variants if v.get("recon_vs_official", {}).get("mean_cd_l1") is not None],
        key=lambda x: x["recon_vs_official"]["mean_cd_l1"],
    )
    best = ranked[0] if ranked else None

    report = {
        "sequence": args.sequence,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "n_frames": len(cg_paths),
        "variants": variants,
        "best": best,
        "ranked": [
            {
                "id": r["id"],
                "backend": r["backend"],
                "transform_mode": r["transform_mode"],
                "depth_scale": r["depth_scale"],
                "multi_camera": r["multi_camera"],
                "mean_cd_l1": r["recon_vs_official"]["mean_cd_l1"],
            }
            for r in ranked
        ],
    }

    out_json = os.path.join(seq_dir, "compare.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(
        json.dumps(
            {
                "sequence": args.sequence,
                "best_id": best["id"] if best else None,
                "mean_cd_l1": best["recon_vs_official"]["mean_cd_l1"] if best else None,
                "out": out_json,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
