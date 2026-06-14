#!/usr/bin/env python3
"""Smoke test vision conditioning on a few CG frames."""
from __future__ import annotations

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
SUPERPC_ROOT = os.path.join(GC2026_ROOT, "code", "SuperPC")
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, SUPERPC_ROOT)
os.chdir(SUPERPC_ROOT)

from test_superpc import build_model_args_from_test_args, load_model, load_vision_tensors_from_image_path, run_sampling  # noqa: E402
from run_superpc_infer import make_test_namespace, prepare_inference_from_xyz  # noqa: E402
from uvg_io import read_ply_xyz_rgb, cg_to_rgbd_color_path  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cg-list", default=os.path.join(GC2026_ROOT, "data/processed/val_cg_only.txt"))
    p.add_argument("--ckpt-path", default=os.path.join(GC2026_ROOT, "models/superpc_pretrained/tartanair_com.pth"))
    p.add_argument("--max-samples", type=int, default=3)
    p.add_argument("--rgbd-pairs-file", default="")
    args = p.parse_args()

    import torch

    infer_args = argparse.Namespace(
        num_points=11520,
        target_num_points=46080,
        use_input_scout_fill=True,
        use_vision_conditioning=True,
        seed=21,
    )
    model_args = build_model_args_from_test_args(make_test_namespace(infer_args))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_model(model_args, "superpc_w_attn", args.ckpt_path, device)

    rgbd_map: dict[str, tuple[str, str]] = {}
    if args.rgbd_pairs_file and os.path.isfile(args.rgbd_pairs_file):
        with open(args.rgbd_pairs_file, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    rgbd_map[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else "")

    with open(args.cg_list, encoding="utf-8") as f:
        cg_paths = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if args.max_samples > 0:
        cg_paths = cg_paths[:args.max_samples]

    ok = 0
    for i, cg_path in enumerate(cg_paths):
        rgb_path = None
        if cg_path in rgbd_map:
            rgb_path = rgbd_map[cg_path][0]
        else:
            rgb_path = cg_to_rgbd_color_path(cg_path)
        if not rgb_path or not os.path.isfile(rgb_path):
            print(f"[SKIP] no RGB for {cg_path}")
            continue
        xyz, _ = read_ply_xyz_rgb(cg_path)
        _, input_model_np, _, _ = prepare_inference_from_xyz(xyz, model_args, 21 + i)
        image_tensor, intrinsics, _ = load_vision_tensors_from_image_path(model_args, rgb_path)
        out, _ = run_sampling(model, model_args, input_model_np, image_tensor, intrinsics, device, 5)
        print(f"[OK] {cg_path} rgb={rgb_path} out_pts={out.shape[0]}")
        ok += 1

    if ok == 0:
        raise SystemExit("No vision frames succeeded — check RGBD download")
    print(f"[verify_vision_frame] SUCCESS {ok}/{len(cg_paths)}")


if __name__ == "__main__":
    main()
