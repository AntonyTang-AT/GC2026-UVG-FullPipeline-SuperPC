#!/usr/bin/env python3
"""Retry missing Stage1 PLY frames for a recon root."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from compare_reconstructed_cg import recon_path_from_cg  # noqa: E402

PY = os.environ.get("PY_CWIPC", "python3.12")
DEFAULTS = os.path.join(GC2026_ROOT, "output/cwipc_native/native_defaults.json")


def load_defaults() -> dict:
    if os.path.isfile(DEFAULTS):
        return json.load(open(DEFAULTS, encoding="utf-8"))
    return {}


def missing_paths(cg_list: str, recon_root: str) -> list[str]:
    missing = []
    with open(cg_list, encoding="utf-8") as f:
        for ln in f:
            cg = ln.strip()
            if not cg or cg.startswith("#"):
                continue
            dst = recon_path_from_cg(cg, recon_root)
            if not os.path.isfile(dst):
                missing.append(cg)
    return missing


def write_cg_list(path: str, cgs: list[str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(cgs) + ("\n" if cgs else ""))


def run_rgbd(
    cg_list: str,
    recon_root: str,
    backend: str,
    profile: str,
    cfg: str,
) -> int:
    cmd = [
        PY,
        os.path.join(SCRIPT_DIR, "rgbd_to_cg.py"),
        "--cg-list",
        cg_list,
        "--out-root",
        recon_root,
        "--backend",
        backend,
        "--cwipc-filter-profile",
        profile,
        "--no-coord-corrections",
        "--force",
    ]
    if backend == "cwipc":
        pass
    else:
        cmd.extend(["--stage1-config", cfg, "--multi-camera"])
    return subprocess.run(cmd, cwd=GC2026_ROOT).returncode


def copy_from_baseline(cg: str, recon_root: str, baseline_root: str) -> bool:
    src = recon_path_from_cg(cg, baseline_root)
    dst = recon_path_from_cg(cg, recon_root)
    if not os.path.isfile(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--recon-root", required=True)
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only_cgv2.txt"))
    p.add_argument("--backend", default="")
    p.add_argument("--cwipc-filter-profile", default="")
    p.add_argument("--stage1-config", default="")
    p.add_argument(
        "--baseline-recon-root",
        default="",
        help="Fallback copy source for frames that cannot be reconstructed",
    )
    p.add_argument("--no-baseline-fallback", action="store_true")
    args = p.parse_args()

    d = load_defaults()
    backend = args.backend or d.get("default_backend", "hybrid")
    profile = args.cwipc_filter_profile or d.get("cwipc_filter_profile", "official")
    cfg = args.stage1_config or d.get("stage1_config", os.path.join(GC2026_ROOT, "output/remediation/stage1_config.json"))
    baseline = args.baseline_recon_root or d.get("baseline_recon", os.path.join(GC2026_ROOT, "output/remediation/stage1_pgdr_val362"))

    miss = missing_paths(args.cg_list, args.recon_root)
    report: dict = {
        "recon_root": args.recon_root,
        "missing_before": len(miss),
        "retried_official": 0,
        "retried_relaxed": 0,
        "retried_mild": 0,
        "copied_baseline": 0,
    }
    if not miss:
        report["missing_after"] = 0
        print(json.dumps(report, indent=2))
        return

    lst = os.path.join(args.recon_root, "_retry_missing.txt")
    write_cg_list(lst, miss)
    report["retried_official"] = len(miss)
    run_rgbd(lst, args.recon_root, backend, profile, cfg)

    miss = missing_paths(args.cg_list, args.recon_root)
    if miss and profile not in ("relaxed", "mild"):
        write_cg_list(lst, miss)
        report["retried_relaxed"] = len(miss)
        run_rgbd(lst, args.recon_root, backend, "relaxed", cfg)
        miss = missing_paths(args.cg_list, args.recon_root)

    if miss and profile != "mild":
        write_cg_list(lst, miss)
        report["retried_mild"] = len(miss)
        run_rgbd(lst, args.recon_root, backend, "mild", cfg)
        miss = missing_paths(args.cg_list, args.recon_root)

    if miss and not args.no_baseline_fallback and baseline and os.path.isdir(baseline):
        copied = 0
        for cg in miss:
            if copy_from_baseline(cg, args.recon_root, baseline):
                copied += 1
        report["copied_baseline"] = copied
        miss = missing_paths(args.cg_list, args.recon_root)

    report["missing_after"] = len(miss)
    if miss:
        report["still_missing_sample"] = miss[:5]
    print(json.dumps(report, indent=2))
    if miss:
        sys.exit(1)


if __name__ == "__main__":
    main()
