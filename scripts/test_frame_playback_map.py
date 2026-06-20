#!/usr/bin/env python3
"""Tests for 15fps <-> 30fps playback index mapping."""
from __future__ import annotations

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from uvg_frame_map import cg_frame_id_to_playback_index, build_playback_map  # noqa: E402


def main() -> None:
    assert cg_frame_id_to_playback_index("0000", mode="even") == 0
    assert cg_frame_id_to_playback_index("0001", mode="even") == 2
    assert cg_frame_id_to_playback_index("0010", mode="even") == 20
    assert cg_frame_id_to_playback_index("0005", mode="identity") == 5

    val_list = os.path.join(GC2026_ROOT, "data/processed/val_cg_only.txt")
    if os.path.isfile(val_list):
        with open(val_list) as f:
            paths = [ln.strip() for ln in f if ln.strip()]
        m = build_playback_map(paths[:20], mode="even")
        assert len(m) == min(20, len(paths))
        for v in m.values():
            assert v["playback_index"] == int(v["frame_id"]) * 2

    print("[test_frame_playback_map] OK")


if __name__ == "__main__":
    main()
