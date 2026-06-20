#!/usr/bin/env python3
"""Select best Stage1 config from coord_probe + sweep; write stage1_winner.json."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)


def load_json(path: str) -> dict | list | None:
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--remediation-dir", default=os.path.join(GC2026_ROOT, "output/remediation"))
    p.add_argument("--gate-mm", type=float, default=200.0)
    p.add_argument("--combo-compare", default=None, help="Optional compare json from combo test")
    args = p.parse_args()

    candidates = []
    coord = load_json(os.path.join(args.remediation_dir, "coord_probe.json"))
    if coord:
        for v in coord.get("variants", []):
            ro = v.get("recon_vs_official", {})
            if ro.get("mean_cd_l1") is None:
                continue
            candidates.append(
                {
                    "source": "coord_probe",
                    "id": v.get("id"),
                    "transform_mode": v.get("transform_mode"),
                    "depth_scale": 1000.0,
                    "frame_map_mode": coord.get("frame_map_mode", "even"),
                    "multi_camera": bool(v.get("multi_camera")),
                    "mean_cd_l1": float(ro["mean_cd_l1"]),
                }
            )

    diag = load_json(os.path.join(args.remediation_dir, "diagnosis_report.json"))
    if diag:
        for s in diag.get("open3d_sweep", []):
            ro = s.get("recon_vs_official", {})
            if ro.get("mean_cd_l1") is None:
                continue
            candidates.append(
                {
                    "source": "open3d_sweep",
                    "id": f"fm_{s.get('frame_map_mode')}_ds_{int(s.get('depth_scale', 0))}",
                    "transform_mode": "chain_meters",
                    "depth_scale": float(s.get("depth_scale", 1000)),
                    "frame_map_mode": s.get("frame_map_mode", "even"),
                    "multi_camera": False,
                    "mean_cd_l1": float(ro["mean_cd_l1"]),
                }
            )

    if args.combo_compare:
        c = load_json(args.combo_compare)
        if c and c.get("summary", {}).get("mean_cd_l1") is not None:
            candidates.append(
                {
                    "source": "combo_test",
                    "id": "seq_only_ds5000",
                    "transform_mode": "seq_only",
                    "depth_scale": 5000.0,
                    "frame_map_mode": "even",
                    "multi_camera": False,
                    "mean_cd_l1": float(c["summary"]["mean_cd_l1"]),
                }
            )

    if not candidates:
        raise SystemExit("No candidates found")

    ranked = sorted(candidates, key=lambda x: x["mean_cd_l1"])
    best = ranked[0]

    # Prefer combo seq_only+5000 if within 10% of best sweep
    for c in candidates:
        if c.get("id") == "seq_only_ds5000" and c["mean_cd_l1"] <= best["mean_cd_l1"] * 1.05:
            best = c
            break

    cd = best["mean_cd_l1"]
    if cd < 40.0:
        tier = "pass_full_stage1"
    elif cd < args.gate_mm:
        tier = "blend_only_no_model"
    else:
        tier = "passthrough_recon"

    winner = {
        "winner": "open3d",
        "mean_cd_l1": cd,
        "gate_mm": args.gate_mm,
        "tier": tier,
        "transform_mode": best.get("transform_mode", "seq_only"),
        "depth_scale": best.get("depth_scale", 5000.0),
        "frame_map_mode": best.get("frame_map_mode", "even"),
        "multi_camera": best.get("multi_camera", False),
        "merge_voxel_mm": 3.0,
        "selected_id": best.get("id"),
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "candidates_ranked": ranked[:10],
    }

    fix_path = os.path.join(args.remediation_dir, "stage1_fix_candidates.json")
    win_path = os.path.join(args.remediation_dir, "stage1_winner.json")
    with open(fix_path, "w", encoding="utf-8") as f:
        json.dump({"ranked": ranked, "best": best, "icp_note": "ICP ~250mm on T5 implies coord fix potential"}, f, indent=2)
    with open(win_path, "w", encoding="utf-8") as f:
        json.dump(winner, f, indent=2)
    print(json.dumps(winner, indent=2))


if __name__ == "__main__":
    main()
