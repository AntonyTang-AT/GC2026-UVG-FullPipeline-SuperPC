#!/usr/bin/env python3
"""Verify SuperPC checkpoint and CUDA extensions load correctly."""
from __future__ import annotations

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
SUPERPC_ROOT = os.path.join(GC2026_ROOT, "code", "SuperPC")
sys.path.insert(0, SUPERPC_ROOT)
os.chdir(SUPERPC_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify SuperPC checkpoint")
    parser.add_argument("--ckpt-path", required=True, help="Path to .pth checkpoint")
    parser.add_argument("--model", default="superpc_w_attn", choices=["superpc", "superpc_w_attn"])
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if not os.path.isfile(args.ckpt_path):
        raise FileNotFoundError(f"Checkpoint not found: {args.ckpt_path}")

    print("[verify] Checking CUDA extensions...")
    import chamfer_3D  # noqa: F401
    from emd_assignment import emd_module  # noqa: F401
    import pointops_cuda  # noqa: F401
    print("[verify] CUDA extensions OK")

    import torch
    from test_superpc import build_model_args_from_test_args, load_model

    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    print(f"[verify] torch={torch.__version__} device={device}")

    state = torch.load(args.ckpt_path, map_location="cpu")
    if isinstance(state, dict):
        print(f"[verify] checkpoint keys: {list(state.keys())[:10]}")

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
    model = load_model(model_args, args.model, args.ckpt_path, device)
    num_params = sum(p.numel() for p in model.parameters())
    print(f"[verify] Model loaded: {args.model}, parameters={num_params:,}")
    print("[verify] SUCCESS")


if __name__ == "__main__":
    main()
