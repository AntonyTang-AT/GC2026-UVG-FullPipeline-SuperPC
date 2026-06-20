#!/usr/bin/env python3
"""Scan installed CGv2 layout and write data/processed/cgv2_layout.json."""
from __future__ import annotations

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from uvg_io import CG_REL, UVG_ROOT_NAME, is_cgv2_filename  # noqa: E402


def main() -> None:
    raw_root = os.path.join(GC2026_ROOT, "data/raw")
    uvg_root = os.path.join(raw_root, UVG_ROOT_NAME)
    layout: dict = {
        "uvg_root": uvg_root,
        "cg_rel": CG_REL,
        "sequences": {},
    }
    for name in sorted(os.listdir(uvg_root)):
        path = os.path.join(uvg_root, name)
        if not os.path.isdir(path):
            continue
        cg_dir = os.path.join(path, CG_REL)
        if not os.path.isdir(cg_dir):
            continue
        seq = name
        v1_samples = []
        v2_samples = []
        for fname in sorted(os.listdir(cg_dir)):
            if not fname.endswith(".ply"):
                continue
            if is_cgv2_filename(fname):
                v2_samples.append(fname)
            else:
                v1_samples.append(fname)
        layout["sequences"][seq] = {
            "cg_dir": cg_dir,
            "v1_count": len(v1_samples),
            "v2_count": len(v2_samples),
            "v1_sample": v1_samples[:2],
            "v2_sample": v2_samples[:2],
        }
    out = os.path.join(GC2026_ROOT, "data/processed/cgv2_layout.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(layout, f, indent=2)
    print(f"Written {out}")
    print(json.dumps({s: layout["sequences"][s]["v2_count"] for s in layout["sequences"]}, indent=2))


if __name__ == "__main__":
    main()
