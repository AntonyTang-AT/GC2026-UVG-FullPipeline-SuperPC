#!/usr/bin/env python3
"""
Batch SuperPC inference on UVG CG PLY frames.

Loads the model once, runs inference_only-style sampling per frame,
transfers RGB from input CG cloud via KNN, and writes colored PLY output.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import torch
from tqdm import tqdm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GC2026_ROOT = os.path.dirname(SCRIPT_DIR)
SUPERPC_ROOT = os.path.join(GC2026_ROOT, "code", "SuperPC")
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, SUPERPC_ROOT)
os.chdir(SUPERPC_ROOT)

from dataset.dataset import _resample_to_fixed_count  # noqa: E402
from uvg_io import (
    cg_to_rgbd_color_path,
    filter_cg_outliers,
    merge_xyz_rgb_voxel,
    read_ply_xyz_rgb,
    transfer_colors_knn,
    write_ply_xyz_rgb,
)  # noqa: E402
from test_superpc import (  # noqa: E402
    build_model_args_from_test_args,
    load_model,
    load_vision_tensors_from_image_path,
    run_sampling,
    _normalize_from_input_only,
)


def parse_args():
    p = argparse.ArgumentParser(description="Batch SuperPC inference for UVG CG PLY")
    p.add_argument("--cg-list", required=True, help="Text file with one CG ply path per line")
    p.add_argument("--ckpt-path", required=True, help="SuperPC checkpoint .pth")
    p.add_argument("--out-dir", default=os.path.join(GC2026_ROOT, "output", "enhanced"))
    p.add_argument("--model", default="superpc_w_attn", choices=["superpc", "superpc_w_attn"])
    p.add_argument("--num-points", type=int, default=2048)
    p.add_argument("--target-num-points", type=int, default=8192)
    p.add_argument("--sampling-steps", type=int, default=25)
    p.add_argument("--seed", type=int, default=21)
    p.add_argument("--use-input-scout-fill", action="store_true", default=True)
    p.add_argument("--no-input-scout-fill", action="store_false", dest="use_input_scout_fill")
    p.add_argument("--use-vision-conditioning", action="store_true", default=False)
    p.add_argument(
        "--rgbd-pairs-file",
        default="",
        help="Tab-separated cg_path rgb_path [intrinsics_path] from map_rgbd_pairs.py",
    )
    p.add_argument(
        "--output-mode",
        default="model",
        choices=["model", "blend_cg", "filter_cg"],
        help="model=SuperPC only; blend_cg=merge model+Cg; filter_cg=SOR on CG (baseline++)",
    )
    p.add_argument(
        "--blend-voxel-mm",
        type=float,
        default=2.0,
        help="Voxel size (mm) when merging model output with CG in blend_cg mode",
    )
    p.add_argument(
        "--max-output-points",
        type=int,
        default=0,
        help="Cap output points after blend (0=keep voxel merge result)",
    )
    p.add_argument("--max-samples", type=int, default=0, help="0 = all lines in list")
    p.add_argument("--color-knn", type=int, default=1, help="KNN neighbors for color transfer")
    p.add_argument("--device", default="cuda")
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip frames whose output PLY already exists",
    )
    return p.parse_args()


def make_test_namespace(args):
    """Minimal namespace compatible with build_model_args_from_test_args."""
    return argparse.Namespace(
        dataset="shapenet",
        shapenet_pc_path="",
        tartanair_root="",
        kitti360_root="",
        eval_split="test",
        val_ratio=0.1,
        split_seed=21,
        num_points=args.num_points,
        target_num_points=args.target_num_points,
        up_rate=max(1, args.target_num_points // max(args.num_points, 1)),
        input_noise_std_min=0.0025,
        input_noise_std_max=0.01,
        input_occlusion_ratio_min=0.25,
        input_occlusion_ratio_max=0.5,
        input_occlusion_ratio=None,
        num_occlusion_areas=3,
        use_input_scout_fill=args.use_input_scout_fill,
        use_hybrid_initialization=False,
        hybrid_scout_ratio=0.3,
        midpoint_downsample_mode="fps",
        midpoint_hybrid_fps_ratio=0.25,
        use_vision_conditioning=args.use_vision_conditioning,
        vision_pretrained_id="depth-anything/Depth-Anything-V2-Small-hf",
        vision_cache_dir=None,
        vision_image_dir=None,
        vision_intrinsics_dir=None,
        vision_intrinsics_path=None,
        vision_img_height=224,
        vision_img_width=224,
        vision_attn_d_model=128,
        vision_attn_heads=4,
        seed=args.seed,
    )


def prepare_inference_from_xyz(points: np.ndarray, model_args, sample_seed: int):
    rng = np.random.RandomState(sample_seed)
    input_raw = points.astype(np.float32)
    input_model = _resample_to_fixed_count(input_raw, int(model_args.num_points), rng).astype(np.float32)
    input_model_norm, center, scale = _normalize_from_input_only(input_model)
    return input_raw, input_model_norm, center, scale


def output_ply_path(out_dir: str, cg_path: str) -> str:
    seq = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(cg_path)))))
    fname = os.path.basename(cg_path)
    out_name = fname.replace("_CG_", "_ENH_", 1)
    return os.path.join(out_dir, seq, out_name)


def load_rgbd_pairs(path: str) -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    if not path or not os.path.isfile(path):
        return mapping
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                mapping[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else "")
    return mapping


def main():
    args = parse_args()
    if not os.path.isfile(args.ckpt_path):
        raise FileNotFoundError(f"Checkpoint not found: {args.ckpt_path}")

    rgbd_pairs = load_rgbd_pairs(args.rgbd_pairs_file)
    if not rgbd_pairs and args.use_vision_conditioning:
        default_pairs = os.path.join(GC2026_ROOT, "data/processed/rgbd_pairs.txt")
        if os.path.isfile(default_pairs):
            rgbd_pairs = load_rgbd_pairs(default_pairs)

    with open(args.cg_list, "r", encoding="utf-8") as f:
        cg_paths = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    if args.max_samples > 0:
        cg_paths = cg_paths[:args.max_samples]

    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    test_ns = make_test_namespace(args)
    model_args = build_model_args_from_test_args(test_ns)
    model = load_model(model_args, args.model, args.ckpt_path, device)

    os.makedirs(args.out_dir, exist_ok=True)
    log_path = os.path.join(args.out_dir, "runtime.log")
    started = datetime.utcnow().isoformat() + "Z"
    records = []

    skipped = 0
    for idx, cg_path in enumerate(tqdm(cg_paths, desc="SuperPC infer")):
        if not os.path.isfile(cg_path):
            print(f"[WARN] missing: {cg_path}")
            continue

        out_path = output_ply_path(args.out_dir, cg_path)
        if args.skip_existing and os.path.isfile(out_path):
            skipped += 1
            continue

        t0 = time.perf_counter()
        xyz, rgb = read_ply_xyz_rgb(cg_path)
        seed_i = int(args.seed) + idx

        image_tensor, intrinsics, _ = None, None, None
        if args.use_vision_conditioning:
            rgb_path = None
            if cg_path in rgbd_pairs:
                rgb_path = rgbd_pairs[cg_path][0]
            else:
                rgb_path = cg_to_rgbd_color_path(cg_path)
            if rgb_path and os.path.isfile(rgb_path):
                try:
                    image_tensor, intrinsics, _ = load_vision_tensors_from_image_path(
                        model_args, rgb_path,
                    )
                except Exception as exc:
                    print(f"[WARN] vision load failed for {cg_path}: {exc}")

        if args.output_mode == "filter_cg":
            out_xyz, out_rgb = filter_cg_outliers(xyz, rgb)
        else:
            input_raw_np, input_model_np, center_np, scale = prepare_inference_from_xyz(
                xyz, model_args, seed_i,
            )
            generated_np, _ = run_sampling(
                model,
                model_args,
                input_seed_np=input_model_np,
                image_tensor=image_tensor,
                intrinsics=intrinsics,
                device=device,
                steps=int(args.sampling_steps),
            )
            generated_xyz = (generated_np * float(scale) + center_np).astype(np.float32)

            if args.output_mode == "blend_cg":
                out_xyz, out_rgb = merge_xyz_rgb_voxel(
                    [generated_xyz, xyz],
                    [transfer_colors_knn(xyz, rgb, generated_xyz), rgb],
                    voxel_size=float(args.blend_voxel_mm),
                )
                if args.max_output_points > 0 and out_xyz.shape[0] > args.max_output_points:
                    rng = np.random.RandomState(seed_i)
                    sel = rng.choice(out_xyz.shape[0], args.max_output_points, replace=False)
                    out_xyz, out_rgb = out_xyz[sel], out_rgb[sel]
            else:
                out_xyz = generated_xyz
                out_rgb = transfer_colors_knn(xyz, rgb, generated_xyz, k=args.color_knn)

        write_ply_xyz_rgb(out_path, out_xyz, out_rgb)

        elapsed = time.perf_counter() - t0
        records.append(
            {
                "cg_path": cg_path,
                "out_path": out_path,
                "input_points": int(xyz.shape[0]),
                "output_points": int(out_xyz.shape[0]),
                "output_mode": args.output_mode,
                "seconds": round(elapsed, 3),
            }
        )

    finished = datetime.utcnow().isoformat() + "Z"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"start={started}\n")
        f.write(f"end={finished}\n")
        f.write(f"ckpt={args.ckpt_path}\n")
        f.write(f"num_points={args.num_points}\n")
        f.write(f"target_num_points={args.target_num_points}\n")
        f.write(f"sampling_steps={args.sampling_steps}\n")
        f.write(f"processed={len(records)}\n")
        f.write(f"skipped_existing={skipped}\n")
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    meta_path = os.path.join(args.out_dir, "infer_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"started": started, "finished": finished, "records": records}, f, indent=2)

    print(f"Done. {len(records)} frames ({skipped} skipped) -> {args.out_dir}")
    if records:
        first = records[0]
        last = records[-1]
        print(
            f"[summary] frames={len(records)} | "
            f"first={first['out_path']} ({first['output_points']} pts) | "
            f"last={last['out_path']} ({last['output_points']} pts) | "
            f"avg_sec={sum(r['seconds'] for r in records) / len(records):.2f}"
        )
        summary_path = os.path.join(args.out_dir, "acceptance_summary.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"frames={len(records)}\n")
            f.write(f"out_dir={args.out_dir}\n")
            f.write(f"first_out={first['out_path']}\n")
            f.write(f"first_points={first['output_points']}\n")
            f.write(f"last_out={last['out_path']}\n")
            f.write(f"last_points={last['output_points']}\n")


if __name__ == "__main__":
    main()
