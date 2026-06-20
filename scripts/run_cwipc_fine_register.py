#!/usr/bin/env python3
"""Fine-register cwipc multi-camera extrinsics via playback dump + test_aligner."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from rgbd_to_cg import CWIPC_MIN_POINTS, ensure_cwipc_playback_config, relax_cwipc_playback_config  # noqa: E402
from uvg_io import find_camera_config  # noqa: E402

PY_CW = os.environ.get("PY_CWIPC", "python3.12")


def export_cwipcdump_frames(
    playback_config: str,
    out_dir: str,
    n_frames: int,
    skip_bad: int = 0,
) -> list[str]:
    from cwipc import util as cwipc_util
    from cwipc import realsense2

    os.makedirs(out_dir, exist_ok=True)
    cap = realsense2.cwipc_realsense2_playback(playback_config)
    saved: list[str] = []
    skipped = 0
    try:
        while len(saved) < n_frames:
            if not cap.available(True):
                continue
            pc = cap.get()
            if pc is None:
                continue
            if pc.count() < CWIPC_MIN_POINTS:
                pc.free()
                continue
            if skipped < skip_bad:
                pc.free()
                skipped += 1
                continue
            path = os.path.join(out_dir, f"frame_{len(saved):04d}.cwipcdump")
            cwipc_util.cwipc_write_debugdump(path, pc)
            pc.free()
            saved.append(path)
    finally:
        cap.free()
    return saved


def link_bags_to_dir(camera_config_src: str, dest_dir: str) -> None:
    cam_dir = os.path.dirname(os.path.abspath(camera_config_src))
    os.makedirs(dest_dir, exist_ok=True)
    for name in os.listdir(cam_dir):
        if name.endswith(".bag"):
            dst = os.path.join(dest_dir, name)
            src = os.path.join(cam_dir, name)
            if not os.path.lexists(dst):
                os.symlink(src, dst)


def run_fine_aligner(dump_path: str, camera_config: str, correspondence: float) -> bool:
    out_ply = os.path.join(os.path.dirname(camera_config), "_aligner_preview.ply")
    cmd = [
        PY_CW, "-m", "cwipc.scripts.cwipc_test_aligner",
        dump_path, out_ply,
        "--cameraconfig", camera_config,
        "--correspondence", str(correspondence),
    ]
    proc = subprocess.run(cmd, cwd=GC2026_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout)
        return False
    return True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sequence", default="VictoryHeart")
    p.add_argument("--seq-root", default=None, help="camera_output directory")
    p.add_argument("--export-frames", type=int, default=3)
    p.add_argument("--correspondence", type=float, default=0.05, help="Fine align max corr (meters)")
    p.add_argument("--out-dir", default=None)
    args = p.parse_args()

    seq = args.sequence
    seq_root = args.seq_root or os.path.join(
        GC2026_ROOT, f"data/raw/UVG-CWI-DQPC/{seq}/consumer-grade_capture_system/camera_output"
    )
    out_dir = args.out_dir or os.path.join(GC2026_ROOT, "output/remediation/cwipc_registered", seq)
    os.makedirs(out_dir, exist_ok=True)

    src_cfg = find_camera_config(seq_root)
    if not src_cfg:
        raise SystemExit(f"No camera config under {seq_root}")

    link_bags_to_dir(src_cfg, out_dir)
    reg_cfg = os.path.join(out_dir, f"{seq}_camera_config.json")
    if not os.path.isfile(reg_cfg):
        with open(src_cfg, encoding="utf-8") as f:
            cfg = json.load(f)
        with open(reg_cfg, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    playback_relaxed = ensure_cwipc_playback_config(seq_root, reg_cfg)
    dump_dir = os.path.join(out_dir, "dumps")
    dumps = export_cwipcdump_frames(playback_relaxed, dump_dir, args.export_frames)
    if not dumps:
        raise SystemExit("Failed to export cwipcdump frames")

    ok = run_fine_aligner(dumps[0], reg_cfg, args.correspondence)
    if not ok:
        raise SystemExit("Fine aligner failed")

    ensure_cwipc_playback_config(seq_root, reg_cfg)
    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sequence": seq,
        "registered_config": reg_cfg,
        "playback_relaxed": os.path.join(out_dir, ".cwipc_playback_relaxed.json"),
        "dump_frames": dumps,
        "correspondence_m": args.correspondence,
    }
    with open(os.path.join(out_dir, "register_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
