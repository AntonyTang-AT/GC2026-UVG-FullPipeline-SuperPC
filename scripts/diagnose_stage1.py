#!/usr/bin/env python3
"""Stage1 RGBD->CG diagnosis: recon vs official/HE, sweeps, backend comparison."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Optional

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402
from evaluate_uvg import chamfer_symmetric_kdtree  # noqa: E402
from uvg_io import (  # noqa: E402
    cg_to_he_path,
    find_transform_matrix,
    parse_frame_id,
    read_ply_xyz,
)


def mean_chamfer_pairs(
    pairs: list[tuple[str, str]],
    n_samples: int = 5000,
    max_load: int = 100000,
    max_frames: int = 0,
) -> dict:
    rng = np.random.RandomState(21)
    cd_list, acc_list, comp_list, n_pts = [], [], [], []
    subset = pairs[:max_frames] if max_frames > 0 else pairs
    for a_path, b_path in subset:
        if not os.path.isfile(a_path) or not os.path.isfile(b_path):
            continue
        a = read_ply_xyz(a_path, max_points=max_load, rng=rng)
        b = read_ply_xyz(b_path, max_points=max_load, rng=rng)
        m = chamfer_symmetric_kdtree(a, b, n_samples, rng)
        cd_list.append(m["cd_l1"])
        acc_list.append(m["accuracy_l1"])
        comp_list.append(m["completeness_l1"])
        n_pts.append(int(a.shape[0]))
    if not cd_list:
        return {"num_evaluated": 0}
    return {
        "num_evaluated": len(cd_list),
        "mean_cd_l1": float(np.mean(cd_list)),
        "mean_accuracy_l1": float(np.mean(acc_list)),
        "mean_completeness_l1": float(np.mean(comp_list)),
        "mean_n_points_a": float(np.mean(n_pts)),
    }


def build_official_pairs(pairs_file: str, max_samples: int = 0) -> list[tuple[str, str]]:
    with open(pairs_file, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if max_samples > 0:
        lines = lines[:max_samples]
    out = []
    for ln in lines:
        parts = ln.split("\t")
        cg = parts[0]
        he = parts[1] if len(parts) > 1 and parts[1] else cg_to_he_path(cg)
        out.append((cg, he))
    return out


def recon_he_pairs(recon_root: str, official_pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    pairs = []
    for off_cg, he in official_pairs:
        recon = recon_path_from_cg(off_cg, recon_root)
        if os.path.isfile(recon) and os.path.isfile(he):
            pairs.append((recon, he))
    return pairs


def recon_official_pairs(recon_root: str, official_pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    pairs = []
    for off_cg, _he in official_pairs:
        recon = recon_path_from_cg(off_cg, recon_root)
        if os.path.isfile(recon) and os.path.isfile(off_cg):
            pairs.append((recon, off_cg))
    return pairs


def cloud_stats(xyz: np.ndarray) -> dict:
    if xyz.size == 0:
        return {}
    return {
        "n_points": int(xyz.shape[0]),
        "centroid": [float(x) for x in xyz.mean(axis=0)],
        "bbox_min": [float(x) for x in xyz.min(axis=0)],
        "bbox_max": [float(x) for x in xyz.max(axis=0)],
        "z_mean": float(xyz[:, 2].mean()),
    }


def run_compare_script(recon_root: str, pairs_file: str, out_json: str, device: str = "cpu", max_samples: int = 50) -> dict:
    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "compare_reconstructed_cg.py"),
        "--recon-root",
        recon_root,
        "--pairs-file",
        pairs_file,
        "--device",
        device,
        "--n-samples",
        "5000",
        "--out-json",
        out_json,
    ]
    if max_samples > 0:
        cmd.extend(["--max-samples", str(max_samples)])
    subprocess.run(cmd, check=True, cwd=GC2026_ROOT)
    with open(out_json, "r", encoding="utf-8") as f:
        return json.load(f)["summary"]


def sweep_open3d(
    cg_paths: list[str],
    out_dir: str,
    depth_scales: list[float],
    frame_maps: list[str],
    max_frames: int,
) -> list[dict]:
    results = []
    subset = cg_paths[:max_frames]
    if not subset:
        return results
    list_path = os.path.join(out_dir, "_sweep_cg_list.txt")
    os.makedirs(out_dir, exist_ok=True)
    with open(list_path, "w", encoding="utf-8") as f:
        f.write("\n".join(subset) + "\n")

    for fmap in frame_maps:
        for ds in depth_scales:
            tag = f"fm_{fmap}_ds_{int(ds)}"
            sweep_root = os.path.join(out_dir, tag)
            os.makedirs(sweep_root, exist_ok=True)
            cmd = [
                sys.executable,
                os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
                "--cg-list",
                list_path,
                "--out-root",
                sweep_root,
                "--backend",
                "open3d",
                "--frame-map-mode",
                fmap,
                "--depth-scale",
                str(ds),
            ]
            try:
                subprocess.run(cmd, check=True, cwd=GC2026_ROOT, capture_output=True, text=True)
            except subprocess.CalledProcessError as exc:
                results.append(
                    {
                        "frame_map_mode": fmap,
                        "depth_scale": ds,
                        "error": (exc.stderr or exc.stdout or str(exc))[:500],
                    }
                )
                continue
            off_pairs = [(p, cg_to_he_path(p)) for p in subset]
            ro = recon_official_pairs(sweep_root, off_pairs)
            rh = recon_he_pairs(sweep_root, off_pairs)
            m_ro = mean_chamfer_pairs([(r, o) for r, o in ro], max_frames=0)
            m_rh = mean_chamfer_pairs(rh, max_frames=0)
            results.append(
                {
                    "frame_map_mode": fmap,
                    "depth_scale": ds,
                    "recon_vs_official": m_ro,
                    "recon_vs_he": m_rh,
                    "sweep_root": sweep_root,
                }
            )
    return results


def audit_enhancement(root: str) -> dict:
    report: dict = {}
    paths = {
        "val_old": os.path.join(root, "output/submission_candidate/evaluation_val_cpu.json"),
        "val_new": os.path.join(root, "output/submission_candidate/evaluation_val_n20k.json"),
        "full_old": os.path.join(root, "output/submission_candidate/evaluation_full_cpu.json"),
        "full_new": os.path.join(root, "output/submission_candidate/evaluation_full_n20k.json"),
        "infer_meta": os.path.join(root, "output/submission_candidate/infer_meta.json"),
        "per_seq_cfg": os.path.join(root, "output/enhancement_eval/per_sequence_enh_config.json"),
    }
    for key, path in paths.items():
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                report[key] = json.load(f)

    mode_counts: dict[str, int] = {}
    ckpt_counts: dict[str, int] = {}
    if "infer_meta" in report:
        for rec in report["infer_meta"].get("records", []):
            mode_counts[rec.get("output_mode", "?")] = mode_counts.get(rec.get("output_mode", "?"), 0) + 1
            ckpt_counts[rec.get("checkpoint", "?")] = ckpt_counts.get(rec.get("checkpoint", "?"), 0) + 1

    model_fallback_seqs = []
    if "per_seq_cfg" in report:
        for seq, entry in report["per_seq_cfg"].get("sequences", {}).items():
            if entry.get("source_experiment") == "full_negative_fallback_model":
                model_fallback_seqs.append(seq)

    unchanged_seqs = ["BlueSpeech", "TicTacToe", "TrumanShow"]
    fp_meta = os.path.join(root, "output/full_pipeline_candidate/infer_meta.json")
    fp_infer_by_seq = {}
    if os.path.isfile(fp_meta):
        with open(fp_meta, "r", encoding="utf-8") as f:
            for rec in json.load(f).get("records", []):
                cg_path = rec.get("cg_path", "")
                if "/UVG-CWI-DQPC/" in cg_path:
                    seq = cg_path.split("/UVG-CWI-DQPC/")[1].split("/")[0]
                else:
                    seq = os.path.basename(os.path.dirname(cg_path))
                fp_infer_by_seq.setdefault(seq, 0)
                fp_infer_by_seq[seq] += 1

    return {
        "val_delta_old": report.get("val_old", {}).get("summary", {}).get("mean_improvement_cd_l1"),
        "val_delta_new": report.get("val_new", {}).get("summary", {}).get("mean_improvement_cd_l1"),
        "full_delta_old": report.get("full_old", {}).get("summary", {}).get("mean_improvement_cd_l1"),
        "full_delta_new": report.get("full_new", {}).get("summary", {}).get("mean_improvement_cd_l1"),
        "infer_mode_counts": mode_counts,
        "infer_ckpt_counts": ckpt_counts,
        "model_fallback_sequences": model_fallback_seqs,
        "fp_infer_records_by_seq": fp_infer_by_seq,
        "unchanged_seqs_missing_fp_infer": [s for s in unchanged_seqs if fp_infer_by_seq.get(s, 0) == 0],
    }


def pick_winner(open3d_summary: Optional[dict], cwipc_summary: Optional[dict], gate_mm: float) -> dict:
    candidates = []
    for name, summary in (("open3d", open3d_summary), ("cwipc", cwipc_summary)):
        if not summary or summary.get("mean_cd_l1") is None:
            continue
        cd = float(summary["mean_cd_l1"])
        candidates.append({"backend": name, "mean_cd_l1": cd, "summary": summary})
    if not candidates:
        return {"winner": None, "reason": "no_valid_backend"}
    winner = min(candidates, key=lambda x: x["mean_cd_l1"])
    cd = winner["mean_cd_l1"]
    if cd < gate_mm:
        tier = "pass_full_stage1"
    elif cd < 200.0:
        tier = "blend_only_no_model"
    else:
        tier = "passthrough_recon"
    return {
        "winner": winner["backend"],
        "mean_cd_l1": cd,
        "gate_mm": gate_mm,
        "tier": tier,
        "candidates": candidates,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pairs-file", default=os.path.join(GC2026_ROOT, "data/processed/val_pairs_cgv2.txt"))
    p.add_argument("--recon-open3d", default=os.path.join(GC2026_ROOT, "output/full_pipeline_val_cg"))
    p.add_argument("--recon-cwipc", default=os.path.join(GC2026_ROOT, "output/remediation/stage1_cwipc"))
    p.add_argument("--out-dir", default=os.path.join(GC2026_ROOT, "output/remediation"))
    p.add_argument("--gate-mm", type=float, default=40.0)
    p.add_argument("--sweep-frames", type=int, default=20)
    p.add_argument("--run-sweep", action="store_true")
    p.add_argument("--run-cwipc-rebuild", action="store_true")
    p.add_argument("--compare-samples", type=int, default=50, help="Max frames for recon vs official compare")
    p.add_argument("--he-samples", type=int, default=20, help="Max frames for recon/official vs HE metrics")
    p.add_argument("--device", default="cpu")
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    official_pairs = build_official_pairs(args.pairs_file, max_samples=args.he_samples)
    cg_paths = [p[0] for p in official_pairs]

    enh_audit = audit_enhancement(GC2026_ROOT)

    open3d_compare = None
    if os.path.isdir(args.recon_open3d):
        open3d_compare = run_compare_script(
            args.recon_open3d,
            args.pairs_file,
            os.path.join(args.out_dir, "compare_open3d_baseline.json"),
            device=args.device,
            max_samples=args.compare_samples,
        )

    cwipc_compare = None
    if args.run_cwipc_rebuild:
        os.makedirs(args.recon_cwipc, exist_ok=True)
        val_cg_list = os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt")
        cmd = [
            sys.executable,
            os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
            "--cg-list",
            val_cg_list,
            "--out-root",
            args.recon_cwipc,
            "--backend",
            "auto",
            "--frame-map-mode",
            "even",
        ]
        subprocess.run(cmd, check=True, cwd=GC2026_ROOT)
        cwipc_compare = run_compare_script(
            args.recon_cwipc,
            args.pairs_file,
            os.path.join(args.out_dir, "compare_cwipc.json"),
            device=args.device,
            max_samples=args.compare_samples,
        )
    elif os.path.isdir(args.recon_cwipc):
        cwipc_compare = run_compare_script(
            args.recon_cwipc,
            args.pairs_file,
            os.path.join(args.out_dir, "compare_cwipc.json"),
            device=args.device,
            max_samples=args.compare_samples,
        )

    open3d_rh = mean_chamfer_pairs(recon_he_pairs(args.recon_open3d, official_pairs))
    open3d_oh = mean_chamfer_pairs(
        [(a, b) for a, b in recon_official_pairs(args.recon_open3d, official_pairs)]
    )
    official_he = mean_chamfer_pairs(official_pairs)

    sample_recon = recon_path_from_cg(cg_paths[0], args.recon_open3d) if cg_paths else ""
    sample_off = cg_paths[0] if cg_paths else ""
    rng = np.random.RandomState(21)
    stats = {}
    if sample_recon and os.path.isfile(sample_recon):
        stats["sample_recon"] = cloud_stats(read_ply_xyz(sample_recon, max_points=100000, rng=rng))
    if sample_off and os.path.isfile(sample_off):
        stats["sample_official"] = cloud_stats(read_ply_xyz(sample_off, max_points=100000, rng=rng))

    transform_info = {}
    if cg_paths:
        seq_root = cg_paths[0].split("consumer-grade_capture_system/CG/")[0]
        tpath = find_transform_matrix(seq_root)
        transform_info = {"seq": os.path.basename(seq_root.rstrip("/")), "transform_matrix": tpath}

    sweep_results = []
    if args.run_sweep:
        sweep_results = sweep_open3d(
            cg_paths,
            os.path.join(args.out_dir, "open3d_sweep"),
            depth_scales=[1000.0, 5000.0, 65535.0],
            frame_maps=["even", "identity"],
            max_frames=args.sweep_frames,
        )

    winner = pick_winner(open3d_compare, cwipc_compare, args.gate_mm)
    winner_path = os.path.join(args.out_dir, "stage1_winner.json")
    with open(winner_path, "w", encoding="utf-8") as f:
        json.dump(winner, f, indent=2)

    report = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "enhancement_audit": enh_audit,
        "open3d": {
            "recon_root": args.recon_open3d,
            "recon_vs_official": open3d_compare,
            "recon_vs_he": open3d_rh,
            "recon_vs_official_direct": open3d_oh,
            "official_vs_he": official_he,
        },
        "cwipc": {"recon_root": args.recon_cwipc, "recon_vs_official": cwipc_compare},
        "cloud_stats_sample": stats,
        "transform_info": transform_info,
        "open3d_sweep": sweep_results,
        "stage1_winner": winner,
    }
    out_path = os.path.join(args.out_dir, "diagnosis_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"diagnosis_report": out_path, "stage1_winner": winner}, indent=2))


if __name__ == "__main__":
    main()
