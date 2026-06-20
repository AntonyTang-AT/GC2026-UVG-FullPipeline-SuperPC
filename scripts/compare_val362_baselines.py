#!/usr/bin/env python3
"""Summarize Val362 N0 v2 vs prior B1/B2 baselines."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)


def load_json(path: str) -> dict:
    if path and os.path.isfile(path):
        return json.load(open(path, encoding="utf-8"))
    return {}


def gate_he(gate: dict) -> dict:
    out = {}
    if "recon_vs_he" in gate:
        r = gate["recon_vs_he"]
        out["recon_overall_he"] = r.get("overall")
        out["recon_per_seq"] = r.get("per_sequence")
    if "enh_vs_he" in gate:
        e = gate["enh_vs_he"]
        out["enh_overall_he"] = e.get("mean_enh_cd_l1")
        out["enh_improvement_vs_recon"] = e.get("mean_improvement_cd_l1")
        out["enh_per_seq"] = e.get("per_sequence_enh")
    if "gate_recon" in gate:
        out["gate_recon_pass"] = gate["gate_recon"].get("pass")
    if "gate_enh" in gate:
        out["gate_enh_pass"] = gate["gate_enh"].get("pass")
    return out


def eval_summary(path: str) -> dict:
    d = load_json(path)
    s = d.get("summary", d)
    return {
        "num_evaluated": s.get("num_evaluated"),
        "mean_cg_cd_l1": s.get("mean_cg_cd_l1"),
        "mean_enh_cd_l1": s.get("mean_enh_cd_l1"),
        "mean_improvement_cd_l1": s.get("mean_improvement_cd_l1"),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--v2-recon-gate", required=True)
    p.add_argument("--v2-enh-gate", required=True)
    p.add_argument("--v2-eval", required=True)
    p.add_argument("--baseline-b1-gate", default="")
    p.add_argument("--baseline-b1-eval", default="")
    p.add_argument("--out-json", required=True)
    args = p.parse_args()

    v2_recon = gate_he(load_json(args.v2_recon_gate))
    v2_enh = gate_he(load_json(args.v2_enh_gate))
    v2_uvg = eval_summary(args.v2_eval)
    b1_enh = gate_he(load_json(args.baseline_b1_gate))
    b1_uvg = eval_summary(args.baseline_b1_eval)

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n0_v2": {
            "recon_vs_he": v2_recon,
            "enh_vs_he": v2_enh,
            "vs_official_cg": v2_uvg,
        },
        "b1_baseline": {
            "enh_vs_he": b1_enh,
            "vs_official_cg": b1_uvg,
        },
        "delta_n0_minus_b1": {},
    }
    for k in ("mean_enh_cd_l1", "mean_improvement_cd_l1"):
        a, b = v2_uvg.get(k), b1_uvg.get(k)
        if a is not None and b is not None:
            report["delta_n0_minus_b1"][k] = float(a) - float(b)
    ra, rb = v2_recon.get("recon_overall_he"), b1_enh.get("recon_overall_he")
    if ra is not None and rb is not None:
        report["delta_n0_minus_b1"]["recon_overall_he"] = float(ra) - float(rb)

    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
