#!/usr/bin/env python3
"""CWIPC playback filter profiles (official / relaxed / mild)."""
from __future__ import annotations

import copy
from typing import Callable

PROFILE_NAMES = ("official", "relaxed", "mild")


def apply_mild_profile(cfg: dict) -> dict:
    """Keep RealSense filters; slightly widen height gate for offline playback."""
    c = copy.deepcopy(cfg)
    proc = c.setdefault("processing", {})
    proc["height_max"] = max(float(proc.get("height_max", 2.0)), 2.5)
    proc["radius_filter"] = min(float(proc.get("radius_filter", 0.55)), 0.45)
    return c


def apply_profile(cfg: dict, profile: str) -> dict:
    from rgbd_to_cg import relax_cwipc_playback_config

    if profile == "official":
        return copy.deepcopy(cfg)
    if profile == "relaxed":
        return relax_cwipc_playback_config(cfg)
    if profile == "mild":
        return apply_mild_profile(cfg)
    raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILE_NAMES}")
