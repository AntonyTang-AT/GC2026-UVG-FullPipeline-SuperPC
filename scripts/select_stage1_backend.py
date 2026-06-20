#!/usr/bin/env python3
"""Build stage1_config.json from probe summaries + Val362 experiments."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)

DEFAULT_ENTRY = {
    "backend": "open3d_cwipc_mc",
    "transform_mode": "cwipc_coords",
    "depth_scale": 1000.0,
    "frame_map_mode": "even",
    "multi_camera": True,
    "merge_voxel_mm": 3.0,
    "note": "PGDR default until probe overrides",
}


def load_json(path: str) -> dict | list | None:
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def variant_to_seq_entry(v: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "backend": v.get("backend", "open3d"),
        "transform_mode": v.get("transform_mode", "legacy"),
        "depth_scale": float(v.get("depth_scale", 1000.0)),
        "frame_map_mode": "even",
        "multi_camera": bool(v.get("multi_camera", False)),
        "merge_voxel_mm": float(v.get("merge_voxel_mm", 3.0)),
        "note": f"probe winner {v.get('id', v.get('best_id', ''))} cd={v.get('mean_cd_l1')}",
    }
    if entry["backend"] == "cwipc":
        entry["transform_mode"] = "cwipc_coords"
        entry["multi_camera"] = False
    return entry


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--probe-summary",
        default=os.path.join(GC2026_ROOT, "output/remediation/probe_all_summary.json"),
    )
    p.add_argument(
        "--val362-experiments",
        default=os.path.join(GC2026_ROOT, "output/remediation/val362_experiments.json"),
    )
    p.add_argument(
        "--out-config",
        default=os.path.join(GC2026_ROOT, "output/remediation/stage1_config.json"),
    )
    p.add_argument(
        "--changelog",
        default=os.path.join(GC2026_ROOT, "output/remediation/stage1_config_changelog.md"),
    )
    p.add_argument(
        "--baseline-config",
        default=os.path.join(GC2026_ROOT, "output/remediation/stage1_config.json"),
    )
    p.add_argument(
        "--scaf-sweep",
        default="",
        help="s1_scaf_sweep.json: merge SCAF wins into config without overwriting other sequences",
    )
    args = p.parse_args()

    old_cfg = load_json(args.baseline_config) or {"default": dict(DEFAULT_ENTRY), "sequences": {}}
    sequences: dict[str, dict] = {}

    probe = load_json(args.probe_summary)
    if probe:
        for row in probe.get("sequences", []):
            seq = row.get("sequence")
            if not seq or row.get("mean_cd_l1") is None:
                continue
            sequences[seq] = variant_to_seq_entry(row)

    val362 = load_json(args.val362_experiments)
    if val362:
        for key in ("best_tictactoe", "best_victoryheart"):
            best = val362.get(key)
            if not best:
                continue
            seq = best.get("sequence")
            if not seq:
                continue
            entry = variant_to_seq_entry(best)
            if "merge_voxel_mm" in best:
                entry["merge_voxel_mm"] = float(best["merge_voxel_mm"])
            prev_cd = sequences.get(seq, {}).get("note", "")
            new_cd = best.get("recon_vs_official", {}).get("mean_cd_l1")
            if seq not in sequences or (new_cd is not None):
                sequences[seq] = entry
                entry["note"] = f"val362_exp {best.get('id')} cd={new_cd:.1f}" if new_cd else entry["note"]

    scaf = load_json(args.scaf_sweep) if args.scaf_sweep else None
    scaf_merged: list[str] = []
    if scaf:
        base_per = (scaf.get("baseline") or {}).get("per_sequence_cd", {})
        for win in scaf.get("scaf_wins_vs_baseline", []):
            seq = win.get("sequence")
            tag = win.get("tag", "")
            if not seq or seq not in base_per:
                continue
            ds = 5000.0
            if "ds2500" in tag:
                ds = 2500.0
            elif "ds1000" in tag:
                ds = 1000.0
            prev = sequences.get(seq, old_cfg.get("sequences", {}).get(seq, {}))
            entry = {
                "backend": "open3d_cwipc_mc",
                "transform_mode": "cwipc_coords",
                "depth_scale": ds,
                "frame_map_mode": "even",
                "multi_camera": True,
                "merge_voxel_mm": float(prev.get("merge_voxel_mm", 3.0)),
                "note": f"SCAF {tag} cd={win.get('cd'):.1f} vs hybrid {win.get('baseline_cd'):.1f}",
            }
            if prev.get("cwipc_camera_config"):
                entry["cwipc_camera_config"] = prev["cwipc_camera_config"]
            sequences[seq] = entry
            scaf_merged.append(seq)

    new_cfg = {
        "default": old_cfg.get("default", dict(DEFAULT_ENTRY)),
        "sequences": {**old_cfg.get("sequences", {}), **sequences},
    }

    os.makedirs(os.path.dirname(args.out_config), exist_ok=True)
    with open(args.out_config, "w", encoding="utf-8") as f:
        json.dump(new_cfg, f, indent=2)

    lines = [
        "# stage1_config changelog",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
    ]
    if scaf_merged:
        lines.append(f"SCAF merged for: {', '.join(scaf_merged)}")
        lines.append("")
    lines.extend([
        "| Sequence | backend | transform | depth_scale | multi_cam | note |",
        "|----------|---------|-----------|-------------|-----------|------|",
    ])
    for seq in sorted(new_cfg["sequences"]):
        e = new_cfg["sequences"][seq]
        lines.append(
            f"| {seq} | {e.get('backend')} | {e.get('transform_mode')} | "
            f"{e.get('depth_scale')} | {e.get('multi_camera')} | {e.get('note', '')} |"
        )
    with open(args.changelog, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(json.dumps({"out_config": args.out_config, "n_sequences": len(new_cfg["sequences"])}, indent=2))


if __name__ == "__main__":
    main()
