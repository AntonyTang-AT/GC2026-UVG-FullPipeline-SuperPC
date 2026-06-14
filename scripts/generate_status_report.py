#!/usr/bin/env python3
"""Aggregate pipeline outputs into a single status JSON for the user."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime

GC2026_ROOT = "/root/autodl-tmp/GC2026"


def count_ply(root: str) -> int:
    n = 0
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f.endswith(".ply"):
                n += 1
    return n


def load_json(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    models_dir = os.path.join(GC2026_ROOT, "models/superpc_pretrained")
    ckpts = []
    if os.path.isdir(models_dir):
        for f in sorted(os.listdir(models_dir)):
            if f.endswith((".pth", ".pt")):
                p = os.path.join(models_dir, f)
                ckpts.append({"name": f, "size_mb": round(os.path.getsize(p) / 1e6, 1)})

    output_names = [
        "BlueSpeech_enhanced",
        "BlueSpeech_smoothed",
        "all_sequences_enhanced",
        "all_sequences_smoothed",
        "all_sequences_official",
        "all_sequences_official_smoothed",
        "submission_candidate",
        "full_pipeline_candidate",
        "full_pipeline_val_candidate",
        "full_pipeline_val_cg",
        "full_pipeline_cg",
        "val_grid",
    ]
    outputs = {}
    for name in output_names:
        p = os.path.join(GC2026_ROOT, "output", name)
        if os.path.isdir(p):
            outputs[name] = {"ply_count": count_ply(p), "path": p}

    evals = {}
    eval_paths = [
        "baselines/val_cg_baseline_n20k.json",
        "baselines/comparison.json",
        "all_sequences_official/evaluation_val_n20k.json",
        "all_sequences_official/evaluation_val_summary.json",
        "all_sequences_enhanced/evaluation_val_summary.json",
        "submission_candidate/evaluation_val_n20k.json",
        "full_pipeline_candidate/evaluation_val_n20k.json",
        "full_pipeline_val_candidate/evaluation_val_n20k.json",
        "val_grid/summary.json",
    ]
    for rel in eval_paths:
        data = load_json(os.path.join(GC2026_ROOT, "output", rel))
        if data is None:
            continue
        if isinstance(data, list):
            evals[rel] = data
        elif "summary" in data:
            evals[rel] = data["summary"]

    rgbd_meta = load_json(os.path.join(GC2026_ROOT, "data/processed/rgbd_pairs_meta.json"))

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "primary_track": "Full Pipeline",
        "fallback_track": "Enhancement Only",
        "checkpoints": ckpts,
        "outputs": outputs,
        "evaluations": evals,
        "rgbd": rgbd_meta,
        "next_steps": [
            "Complete val RGBD download: check_rgbd_download.sh",
            "Install RGBD: post_rgbd_install.sh",
            "Val smoke: run_full_pipeline_val.sh",
            "Unit test mm coords: python scripts/test_rgbd_to_cg_units.py",
            "Full RGBD download + run_full_pipeline.sh after val gate",
        ],
    }

    def rgbd_download_summary() -> str:
        try:
            out = subprocess.run(
                [
                    "bash",
                    os.path.join(GC2026_ROOT, "scripts/check_rgbd_download.sh"),
                ],
                env={
                    **os.environ,
                    "SEQ_FILTER": "TicTacToe,VictoryHeart",
                },
                capture_output=True,
                text=True,
                timeout=30,
            )
            lines = (out.stdout or out.stderr or "").strip().splitlines()
            return "\n".join(lines[-4:]) if lines else "check script unavailable"
        except (subprocess.SubprocessError, OSError) as exc:
            return f"check failed: {exc}"

    def tail_log(rel: str, n: int = 2) -> str:
        path = os.path.join(GC2026_ROOT, "output", rel)
        if not os.path.isfile(path):
            return "n/a"
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-n:]).strip() or "empty"

    def chain_stage() -> str:
        val_log = os.path.join(GC2026_ROOT, "output/wait_rgbd_val.log")
        chain_log = os.path.join(GC2026_ROOT, "output/full_pipeline_chain.log")
        if os.path.isfile(chain_log):
            with open(chain_log, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            if "full_after_val" in text and "DONE" in text.split("full_after_val")[-1]:
                return "chain completed (or full infer stage)"
            if "run_full_pipeline_val" in text:
                return "val smoke / post stage"
        if os.path.isfile(val_log):
            with open(val_log, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            if "waiting for SEQ" in text and "DONE" not in text:
                return "waiting for val RGBD download"
        return "unknown / not started"

    color_data = load_json(
        os.path.join(GC2026_ROOT, "output/submission_candidate/color_evaluation_val.json")
    )
    temporal_data = load_json(
        os.path.join(GC2026_ROOT, "output/submission_candidate/temporal_stability.json")
    )
    color_summary = color_data.get("summary", {}) if color_data else {}
    temporal_summary = temporal_data.get("summary", {}) if temporal_data else {}

    out_json = os.path.join(GC2026_ROOT, "output", "status_report.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out_json}")

    out_md = os.path.join(GC2026_ROOT, "output", "status_report.md")
    enh_val = evals.get("submission_candidate/evaluation_val_n20k.json", {})
    full_val = evals.get("full_pipeline_val_candidate/evaluation_val_n20k.json", {})
    enh_ply = outputs.get("submission_candidate", {}).get("ply_count", 0)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# GC2026 UVG-CWI-DQPC Status\n\n")
        f.write(f"Generated: {report['generated_at']}\n\n")
        f.write("## Processing Tracks\n\n")
        f.write("| Track | Role | Val improve (n=20k) |\n")
        f.write("|-------|------|---------------------|\n")
        f.write(
            f"| Full Pipeline (primary) | RGBD→CG→SuperPC | "
            f"{full_val.get('mean_improvement_cd_l1', 'pending')} |\n"
        )
        f.write(
            f"| Enhancement Only (fallback) | Official CG→SuperPC | "
            f"{enh_val.get('mean_improvement_cd_l1', 'n/a')} |\n\n"
        )

        f.write("## Enhancement Metrics (val)\n\n")
        f.write(f"- Chamfer improve (n=20k): {enh_val.get('mean_improvement_cd_l1', 'n/a')}\n")
        f.write(f"- Color PSNR-Y: {color_summary.get('mean_psnr_y', 'n/a')}\n")
        f.write(f"- Temporal adjacent CD-L1: {temporal_summary.get('mean_adjacent_cd_l1', 'n/a')}\n")
        f.write(f"- ENH frames: {enh_ply}\n\n")

        f.write("## RGBD Download (val sequences)\n\n")
        f.write("```\n")
        f.write(rgbd_download_summary())
        f.write("\n```\n\n")

        f.write("## Background Chain\n\n")
        f.write(f"- Stage: {chain_stage()}\n")
        f.write("- Logs: `output/wait_rgbd_val.log`, `output/full_pipeline_chain.log`\n")
        f.write(f"- aria2 tail: `{tail_log('aria2_download.log', 1).replace(chr(10), ' ')[:120]}`\n\n")

        f.write("## Submission Artifacts\n\n")
        f.write("| Artifact | Path | Status |\n")
        f.write("|----------|------|--------|\n")
        enh_tar = os.path.join(GC2026_ROOT, "output/submission_candidate_submission.tar.gz")
        full_tar = os.path.join(GC2026_ROOT, "output/full_pipeline_candidate_submission.tar.gz")
        f.write(
            f"| Enhancement tar | `output/submission_candidate_submission.tar.gz` | "
            f"{'exists' if os.path.isfile(enh_tar) else 'missing'} |\n"
        )
        f.write(
            f"| Full Pipeline tar | `output/full_pipeline_candidate_submission.tar.gz` | "
            f"{'exists' if os.path.isfile(full_tar) else 'pending'} |\n"
        )
        f.write(
            f"| Primary manifest | `submissions/GC2026_Team/manifest.json` | Enhancement until Full ready |\n\n"
        )

        if rgbd_meta:
            f.write(
                f"RGBD mapped: {rgbd_meta.get('mapped', 0)} "
                f"missing: {rgbd_meta.get('missing_rgb', 0)}\n\n"
            )

        f.write("## Next Steps\n\n")
        for step in report["next_steps"]:
            f.write(f"- {step}\n")


if __name__ == "__main__":
    main()
