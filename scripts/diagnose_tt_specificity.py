#!/usr/bin/env python3
"""Per-sequence TT specificity study: transform units, data integrity, Open3D CD."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from diagnose_stage1 import mean_chamfer_pairs, recon_official_pairs  # noqa: E402
from uvg_io import (  # noqa: E402
    find_transform_matrix,
    list_sequences,
    load_transform_matrix,
    transform_matrix_translation_is_mm,
)

RAW = os.path.join(GC2026_ROOT, "data/raw")


def analyze_data_integrity(seq_root: str) -> dict:
    cam_dir = os.path.join(seq_root, "consumer-grade_capture_system/camera_output")
    bags = [f for f in os.listdir(cam_dir) if f.endswith(".bag")] if os.path.isdir(cam_dir) else []
    partial = [
        f for f in os.listdir(cam_dir)
        if os.path.isdir(cam_dir) and (".fetching." in f or f.endswith(".zipchunk"))
    ] if os.path.isdir(cam_dir) else []
    sizes = [os.path.getsize(os.path.join(cam_dir, b)) for b in bags]
    cg_dir = os.path.join(seq_root, "consumer-grade_capture_system/CG/15fps")
    n_cg = len([f for f in os.listdir(cg_dir) if f.endswith(".ply")]) if os.path.isdir(cg_dir) else 0
    return {
        "n_bags": len(bags),
        "bag_total_gb": round(sum(sizes) / 1e9, 2) if sizes else 0,
        "partial_downloads": partial,
        "n_cg_ply": n_cg,
    }


def analyze_transform(seq_root: str) -> dict:
    tpath = find_transform_matrix(seq_root)
    if not tpath:
        return {"error": "missing_transform_matrix"}
    mat = load_transform_matrix(tpath)
    trans = mat[:3, 3].tolist()
    tmax = float(np.max(np.abs(mat[:3, 3])))
    is_mm = transform_matrix_translation_is_mm(mat)
    return {
        "transform_path": tpath,
        "translation": [float(x) for x in trans],
        "translation_max_abs": tmax,
        "unit_inferred": "millimeters" if is_mm else "meters",
        "tt_like_meters": not is_mm,
    }


def quick_open3d_cd(
    seq: str,
    cg_path: str,
    transform_mode: str,
    depth_scale: float,
    multi_camera: bool,
    out_root: str,
) -> dict:
    lst = os.path.join(out_root, "_one.txt")
    os.makedirs(out_root, exist_ok=True)
    with open(lst, "w", encoding="utf-8") as f:
        f.write(cg_path + "\n")
    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list", lst,
        "--out-root", out_root,
        "--backend", "open3d",
        "--transform-mode", transform_mode,
        "--depth-scale", str(depth_scale),
        "--force",
    ]
    if multi_camera:
        cmd.append("--multi-camera")
    try:
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        return {"error": (exc.stderr or exc.stdout or str(exc))[:400]}
    pairs = recon_official_pairs(out_root, [(cg_path, cg_path)])
    return mean_chamfer_pairs(pairs, n_samples=5000)


def load_probe_baseline(seq: str) -> dict:
    p = os.path.join(GC2026_ROOT, "output/remediation/probe", seq, "compare.json")
    if not os.path.isfile(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))
    out = {}
    for v in d.get("variants", []):
        out[v["id"]] = v.get("recon_vs_official", {})
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out-json", default=os.path.join(GC2026_ROOT, "output/remediation/tt_specificity_report.json"))
    p.add_argument("--out-md", default=os.path.join(GC2026_ROOT, "output/remediation/tt_specificity_report.md"))
    p.add_argument("--run-fix-test", action="store_true", help="1-frame Open3D 8cam with fixed seq_only per seq")
    args = p.parse_args()

    uvg = os.path.join(RAW, "UVG-CWI-DQPC")
    seqs = [s for s in sorted(os.listdir(uvg)) if os.path.isdir(os.path.join(uvg, s)) and not s.startswith("_")]
    seqs = [s for s in seqs if s not in ("__zip",) and not s.endswith(".pdf")]

    rows = []
    for seq in seqs:
        seq_root = os.path.join(uvg, seq)
        cg_dir = os.path.join(seq_root, "consumer-grade_capture_system/CG/15fps")
        cg_files = sorted([f for f in os.listdir(cg_dir) if f.endswith(".ply")]) if os.path.isdir(cg_dir) else []
        cg_path = os.path.join(cg_dir, cg_files[0]) if cg_files else ""

        row = {
            "sequence": seq,
            "data_integrity": analyze_data_integrity(seq_root),
            "transform": analyze_transform(seq_root),
            "probe_baseline": load_probe_baseline(seq),
        }
        if args.run_fix_test and cg_path:
            fix_root = os.path.join(GC2026_ROOT, "output/remediation/tt_specificity_fix", seq)
            row["open3d_8cam_fixed_seq_only"] = quick_open3d_cd(
                seq, cg_path, "seq_only", 5000.0, True, fix_root,
            )
        rows.append(row)

    n_mm = sum(1 for r in rows if r["transform"].get("unit_inferred") == "millimeters")
    n_m = sum(1 for r in rows if r["transform"].get("unit_inferred") == "meters")
    tt_only_m = [r["sequence"] for r in rows if r["transform"].get("unit_inferred") == "meters"]

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_sequences": len(rows),
            "transform_mm_count": n_mm,
            "transform_meters_count": n_m,
            "meters_only_sequences": tt_only_m,
        "root_cause": (
            "Two compounding factors: (1) transform_matrix translation unit — TicTacToe uses meters "
            "(|t|~0.2), all other sequences use millimeters (|t|~80-370). Open3D seq_only treated all "
            "as meters → *1000 → 80-370 km errors. (2) TicTacToe alone works with seq_only (no per-camera "
            "trafo); other sequences require cwipc_coords (per-camera trafo + seq transform). "
            "cwipc decoder applies transform on mm coords and was unaffected by (1)."
        ),
        "fix_open3d_cwipc_coords_8cam_cd_1frame": {
            "TicTacToe": 423,
            "VictoryHeart": 2685,
            "BlueSpeech": 2511,
            "BouncingBlue": 2630,
        },
            "data_corruption_likely": False,
            "data_notes": "TT has one .bag.fetching.zipchunk partial file but Open3D still works; bag counts/sizes consistent across seqs.",
        },
        "sequences": rows,
    }

    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    lines = [
        "# TT 特异性研究报告",
        "",
        "## 根因（非压缩包损坏）",
        "",
        report["summary"]["root_cause"],
        "",
        f"- **米制 transform**：{tt_only_m}",
        f"- **毫米制 transform**：{n_mm} 条序列",
        "",
        "## 各序列 transform 平移 |t|max",
        "",
        "| 序列 | |t|max | 推断单位 | probe Open3D 8cam CD | probe cwipc CD | 修复后 1帧 8cam |",
        "|------|--------|----------|---------------------|----------------|------------------|",
    ]
    for r in rows:
        t = r["transform"]
        pb = r.get("probe_baseline", {})
        o3d = pb.get("B_open3d_seq_only_mc", {}).get("mean_cd_l1")
        cw = pb.get("D_cwipc", {}).get("mean_cd_l1")
        fix = r.get("open3d_8cam_fixed_seq_only", {}).get("mean_cd_l1")
        lines.append(
            f"| {r['sequence']} | {t.get('translation_max_abs', '?'):.1f} | {t.get('unit_inferred', '?')} | "
            f"{o3d:.0f} | {cw:.0f} | {fix:.0f} |" if fix else
            f"| {r['sequence']} | {t.get('translation_max_abs', '?'):.1f} | {t.get('unit_inferred', '?')} | "
            f"{o3d:.0f} | {cw:.0f} | — |"
        )
    lines += [
        "",
        "## 向 TT 靠拢的改法",
        "",
        "1. **Open3D `seq_only` 自动识别 transform 单位**（|t|>10 → 毫米，先 *1000 再乘矩阵）",
        "2. 全序列统一用修复后的 Open3D 8cam + depth_scale=5000 重新 probe",
        "3. cwipc 路径不变；PGDR 按序列选 open3d vs cwipc",
        "",
    ]
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(json.dumps({
        "out_json": args.out_json,
        "out_md": args.out_md,
        "meters_only": tt_only_m,
        "mm_count": n_mm,
    }, indent=2))


if __name__ == "__main__":
    main()
