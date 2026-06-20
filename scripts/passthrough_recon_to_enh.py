#!/usr/bin/env python3
"""Copy reconstructed CG PLYs to Full Pipeline ENH output paths (pass-through Stage2)."""
from __future__ import annotations

import argparse
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from uvg_io import read_ply_xyz_rgb, write_ply_xyz_rgb  # noqa: E402


def enh_path_from_recon(recon_path: str, out_root: str) -> str:
    seq = os.path.basename(os.path.dirname(recon_path))
    fname = os.path.basename(recon_path).replace("_CG_", "_ENH_", 1)
    return os.path.join(out_root, seq, fname)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--recon-list", required=True)
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()

    ok = 0
    with open(args.recon_list, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]

    for recon in lines:
        if not os.path.isfile(recon):
            print(f"[WARN] missing recon: {recon}")
            continue
        out = enh_path_from_recon(recon, args.out_dir)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            shutil.copy2(recon, out)
        except Exception:
            xyz, rgb = read_ply_xyz_rgb(recon)
            write_ply_xyz_rgb(out, xyz, rgb)
        ok += 1

    print(f"[passthrough] wrote {ok} ENH frames -> {args.out_dir}")


if __name__ == "__main__":
    main()
