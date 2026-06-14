#!/usr/bin/env python3
"""Create an initialized SuperPC checkpoint for pipeline smoke tests when official weights are unavailable."""
from __future__ import annotations

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
SUPERPC_ROOT = os.path.join(GC2026_ROOT, "code", "SuperPC")
sys.path.insert(0, SUPERPC_ROOT)
os.chdir(SUPERPC_ROOT)

from models.diffusion import PUFM_w_attn  # noqa: E402
from test_superpc import build_model_args_from_test_args  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=os.path.join(GC2026_ROOT, "models/superpc_pretrained/shapenet_superpc_w_attn_init_smoke.pth"),
    )
    args = parser.parse_args()

    test_ns = argparse.Namespace(
        dataset="shapenet",
        shapenet_pc_path="",
        tartanair_root="",
        kitti360_root="",
        eval_split="test",
        val_ratio=0.1,
        split_seed=21,
        num_points=2048,
        target_num_points=8192,
        up_rate=4,
        input_noise_std_min=0.0025,
        input_noise_std_max=0.01,
        input_occlusion_ratio_min=0.25,
        input_occlusion_ratio_max=0.5,
        input_occlusion_ratio=None,
        num_occlusion_areas=3,
        use_input_scout_fill=True,
        use_hybrid_initialization=False,
        hybrid_scout_ratio=0.3,
        midpoint_downsample_mode="fps",
        midpoint_hybrid_fps_ratio=0.25,
        use_vision_conditioning=False,
        vision_pretrained_id="depth-anything/Depth-Anything-V2-Small-hf",
        vision_cache_dir=None,
        vision_image_dir=None,
        vision_intrinsics_dir=None,
        vision_intrinsics_path=None,
        vision_img_height=224,
        vision_img_width=224,
        vision_attn_d_model=128,
        vision_attn_heads=4,
        seed=21,
    )
    model_args = build_model_args_from_test_args(test_ns)
    model = PUFM_w_attn(model_args)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    torch = __import__("torch")
    torch.save(model.state_dict(), args.out)
    print(f"[create_init_ckpt] WARNING: random-init checkpoint for pipeline testing only: {args.out}")
    print("[create_init_ckpt] Replace with official Google Drive weights for real enhancement quality.")


if __name__ == "__main__":
    main()
