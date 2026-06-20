#!/usr/bin/env python3
"""Val362 targeted experiments: TicTacToe 8cam + VictoryHeart cwipc parameter sweep."""
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

from diagnose_stage1 import recon_official_pairs, mean_chamfer_pairs  # noqa: E402


def sample_seq_frames(cg_list: str, seq: str, n: int) -> list[str]:
    paths = []
    with open(cg_list, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and f"/{seq}/" in ln:
                paths.append(ln)
    return paths[:n] if n > 0 else paths


def run_rebuild(
    cg_paths: list[str],
    out_root: str,
    backend: str,
    extra_args: list[str],
    py: str,
) -> dict:
    os.makedirs(out_root, exist_ok=True)
    list_path = os.path.join(out_root, "_cg_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cg_paths) + "\n")
    cmd = [
        py,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list",
        list_path,
        "--out-root",
        out_root,
        "--backend",
        backend,
        "--frame-map-mode",
        "even",
        "--force",
        *extra_args,
    ]
    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"error": (exc.stderr or exc.stdout or str(exc))[:1200]}
    pairs = [(p, p) for p in cg_paths]
    return {"recon_vs_official": mean_chamfer_pairs(recon_official_pairs(out_root, pairs), n_samples=5000)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--cg-list",
        default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"),
    )
    p.add_argument("--quick-frames", type=int, default=5, help="Frames for VH sweep quick screen")
    p.add_argument("--tt-frames", type=int, default=20, help="Frames for TicTacToe 8cam compare")
    p.add_argument(
        "--out-json",
        default=os.path.join(GC2026_ROOT, "output/remediation/val362_experiments.json"),
    )
    args = p.parse_args()

    py_o3d = os.environ.get("PY_OPEN3D", "python3.12")
    py_cw = os.environ.get("PY_CWIPC", "python3.12")

    results = {"created_at": datetime.utcnow().isoformat() + "Z", "experiments": []}

    # TicTacToe: single cam vs 8 cam (seq_only + ds5000)
    tt_paths = sample_seq_frames(args.cg_list, "TicTacToe", args.tt_frames)
    for label, multi in [("tt_single_cam", False), ("tt_8cam", True)]:
        out = os.path.join(GC2026_ROOT, "output/remediation/val362_exp", label)
        extra = [
            "--transform-mode",
            "seq_only",
            "--depth-scale",
            "5000",
        ]
        if multi:
            extra += ["--multi-camera", "--merge-voxel-mm", "3.0"]
        res = run_rebuild(tt_paths, out, "open3d", extra, py_o3d)
        results["experiments"].append(
            {
                "id": label,
                "sequence": "TicTacToe",
                "backend": "open3d",
                "transform_mode": "seq_only",
                "depth_scale": 5000.0,
                "multi_camera": multi,
                "n_frames": len(tt_paths),
                **res,
            }
        )

    # VictoryHeart: cwipc merge_voxel sweep
    vh_quick = sample_seq_frames(args.cg_list, "VictoryHeart", args.quick_frames)
    for voxel in [2.0, 3.0, 5.0]:
        out = os.path.join(GC2026_ROOT, "output/remediation/val362_exp", f"vh_cwipc_voxel_{voxel}")
        extra = ["--merge-voxel-mm", str(voxel), "--depth-trunc-mm", "5000"]
        res = run_rebuild(vh_quick, out, "cwipc", extra, py_cw)
        results["experiments"].append(
            {
                "id": f"vh_cwipc_voxel_{voxel}",
                "sequence": "VictoryHeart",
                "backend": "cwipc",
                "merge_voxel_mm": voxel,
                "n_frames": len(vh_quick),
                **res,
            }
        )

    ranked_tt = sorted(
        [e for e in results["experiments"] if e.get("sequence") == "TicTacToe" and e.get("recon_vs_official", {}).get("mean_cd_l1")],
        key=lambda x: x["recon_vs_official"]["mean_cd_l1"],
    )
    ranked_vh = sorted(
        [e for e in results["experiments"] if e.get("sequence") == "VictoryHeart" and e.get("recon_vs_official", {}).get("mean_cd_l1")],
        key=lambda x: x["recon_vs_official"]["mean_cd_l1"],
    )
    results["best_tictactoe"] = ranked_tt[0] if ranked_tt else None
    results["best_victoryheart"] = ranked_vh[0] if ranked_vh else None

    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(json.dumps({"best_tt": results.get("best_tictactoe", {}).get("id"), "best_vh": results.get("best_victoryheart", {}).get("id")}, indent=2))


if __name__ == "__main__":
    main()
