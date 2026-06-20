#!/usr/bin/env python3
"""Diagnose cwipc vs UVG RGBD bags: root cause, compatible data path, smoke test."""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from uvg_io import find_bag_files, find_camera_config  # noqa: E402

CWIPC_PLAYBACK_RELAXED = ".cwipc_playback_relaxed.json"


def relax_cwipc_playback_config(cfg: dict) -> dict:
    """UVG camera_config height/radius filters remove almost all playback points."""
    c = copy.deepcopy(cfg)
    flt = c.setdefault("filtering", {})
    flt["do_threshold"] = False
    flt["do_spatial"] = False
    proc = c.setdefault("processing", {})
    proc["height_min"] = 0.0
    proc["height_max"] = 10.0
    proc["radius_filter"] = 0.0
    proc["depth_x_erosion"] = 0
    proc["depth_y_erosion"] = 0
    return c


def ensure_relaxed_playback_config(seq_root: str) -> Optional[str]:
    src = find_camera_config(seq_root)
    if not src:
        return None
    cam_dir = os.path.dirname(src)
    dst = os.path.join(cam_dir, CWIPC_PLAYBACK_RELAXED)
    with open(src, encoding="utf-8") as f:
        cfg = json.load(f)
    relaxed = relax_cwipc_playback_config(cfg)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(relaxed, f, indent=2)
    return dst


def bag_header(path: str, n: int = 16) -> str:
    with open(path, "rb") as f:
        return f.read(n).decode("latin-1", errors="replace")


def test_librealsense_bag(bag: str) -> dict[str, Any]:
    try:
        import pyrealsense2 as rs
    except ImportError as exc:
        return {"ok": False, "error": f"pyrealsense2 missing: {exc}"}
    pipe = rs.pipeline()
    cfg = rs.config()
    cfg.enable_device_from_file(bag, repeat_playback=False)
    try:
        pipe.start(cfg)
        frames = pipe.wait_for_frames(timeout_ms=15000)
        depth = frames.get_depth_frame()
        color = frames.get_color_frame()
        pipe.stop()
        return {
            "ok": True,
            "depth": [depth.get_width(), depth.get_height()],
            "color": [color.get_width(), color.get_height()],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def test_cwipc_cli_playback_bag(bag: str) -> dict[str, Any]:
    cwipc = os.environ.get("CWIPC_BIN") or "cwipc"
    cmd = [cwipc, "copy", "--playback", bag, "/tmp/cwipc_bad_playback_test"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        err = (proc.stderr or proc.stdout or "").strip()
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stderr_tail": err[-500:] if err else "",
            "expected_failure": "unknown playback file type" in err.lower(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def test_cwipc_realsense_playback(config_path: str) -> dict[str, Any]:
    try:
        from cwipc import realsense2
    except ImportError as exc:
        return {"ok": False, "error": f"cwipc python missing: {exc}"}
    try:
        cap = realsense2.cwipc_realsense2_playback(config_path)
    except Exception as exc:
        return {"ok": False, "error": f"playback open failed: {exc}"}
    try:
        points = 0
        ts = None
        tiles = cap.maxtile()
        for _ in range(6):
            if not cap.available(True):
                continue
            pc = cap.get()
            if pc is None:
                continue
            if pc.count() > 1000:
                points = pc.count()
                ts = pc.timestamp()
                pc.free()
                break
            pc.free()
        return {"ok": points > 1000, "points": points, "timestamp_ms": ts, "tiles": tiles}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        cap.free()


def analyze_sequence(seq: str) -> dict[str, Any]:
    seq_root = os.path.join(GC2026_ROOT, "data/raw/UVG-CWI-DQPC", seq)
    bags = find_bag_files(seq_root)
    cam_cfg = find_camera_config(seq_root)
    cam_dir = os.path.dirname(cam_cfg) if cam_cfg else None
    row: dict[str, Any] = {
        "seq": seq,
        "n_bags": len(bags),
        "camera_config": cam_cfg,
        "bag_serial_match": [],
    }
    if not bags:
        row["error"] = "no bags"
        return row

    bag0 = bags[0]
    hdr = bag_header(bag0)
    row["bag_header"] = hdr.strip()
    row["is_rosbag_v2"] = hdr.startswith("#ROSBAG V2")
    row["librealsense_playback"] = test_librealsense_bag(bag0)
    row["cwipc_cli_wrong_playback"] = test_cwipc_cli_playback_bag(bag0)

    if cam_cfg and cam_dir:
        serials = []
        try:
            with open(cam_cfg, encoding="utf-8") as f:
                cfg = json.load(f)
            for cam in cfg.get("camera", []):
                serial = cam.get("serial")
                if not serial:
                    continue
                bag_path = os.path.join(cam_dir, f"{serial}.bag")
                serials.append({"serial": serial, "bag_exists": os.path.isfile(bag_path)})
        except Exception as exc:
            serials = [{"error": str(exc)}]
        row["bag_serial_match"] = serials
        relaxed = ensure_relaxed_playback_config(seq_root)
        row["relaxed_playback_config"] = relaxed
        if relaxed:
            row["cwipc_realsense2_playback"] = test_cwipc_realsense_playback(relaxed)
    return row


def main() -> None:
    p = argparse.ArgumentParser(description="cwipc compatibility diagnosis for UVG RGBD bags")
    p.add_argument("--sequences", nargs="*", default=["TicTacToe"])
    p.add_argument(
        "--out-json",
        default=os.path.join(GC2026_ROOT, "output/remediation/cwipc_feasibility.json"),
    )
    args = p.parse_args()

    sequences = [analyze_sequence(s) for s in args.sequences]
    any_playback_ok = any(
        s.get("cwipc_realsense2_playback", {}).get("ok") for s in sequences
    )

    report = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "cwipc_version": subprocess.getoutput("cwipc version 2>/dev/null").strip() or None,
        "root_cause": {
            "summary": (
                "rgbd_to_cg.py 曾把 .bag 传给 cwipc --playback；该参数只接受 .ply/.cwipcdump/.cwicpc，"
                "因此报 unknown playback file type。UVG 的 bag 是 RealSense SDK 录制的 ROSBAG V2，"
                "librealsense 可直接回放，但 cwipc 应使用 cwipc_realsense2_playback(camera_config.json)，"
                "且 {serial}.bag 必须与 config 同目录。"
            ),
            "wrong_api": "cwipc grab|copy --playback /path/to/serial.bag",
            "correct_api": "cwipc_realsense2_playback(<seq>_camera_config.json) 或 cwipc copy <config.json> <outdir>",
            "config_type": "realsense_playback",
            "bag_naming": "{serial}.bag beside camera_config.json",
            "filtering_note": (
                "官方 camera_config 的 height/radius/threshold 过滤在离线回放时几乎删光点云；"
                "需写入 .cwipc_playback_relaxed.json（见 rgbd_to_cg / diagnose 脚本）。"
            ),
        },
        "compatible_data": {
            "rgbd_zip_bags": True,
            "raw_zip_found": False,
            "realsense_native_bag_dir": False,
            "note": "无需额外 raw.zip；现有 RGBD zip 解压后的 camera_output/*.bag 即为兼容数据源。",
        },
        "sequences": sequences,
        "conclusion": (
            "cwipc 可用：使用 camera_output 下 camera_config + serial.bag，经 realsense2_playback API。"
            if any_playback_ok
            else "cwipc 仍不可用：检查 cwipc_env.sh、librealsense 与 bag/config 路径。"
        ),
        "recommended_stage1_backend": "cwipc" if any_playback_ok else "open3d",
    }

    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"out": args.out_json, "conclusion": report["conclusion"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
