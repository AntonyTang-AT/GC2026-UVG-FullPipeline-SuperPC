#!/usr/bin/env python3
"""Split CG list into pending (no output PLY yet) and optional shard files for multi-GPU."""
from __future__ import annotations

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from run_superpc_infer import output_ply_path  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cg-list", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--shard-dir", required=True, help="Directory for pending_0.txt, pending_1.txt, ...")
    p.add_argument("--num-shards", type=int, default=2)
    args = p.parse_args()

    with open(args.cg_list, "r", encoding="utf-8") as f:
        cg_paths = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]

    pending = []
    for cg in cg_paths:
        out = output_ply_path(args.out_dir, cg)
        if not os.path.isfile(out):
            pending.append(cg)

    os.makedirs(args.shard_dir, exist_ok=True)
    shards: list[list[str]] = [[] for _ in range(args.num_shards)]
    for i, cg in enumerate(pending):
        shards[i % args.num_shards].append(cg)

    for i, shard in enumerate(shards):
        path = os.path.join(args.shard_dir, f"pending_{i}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(shard) + ("\n" if shard else ""))

    meta = os.path.join(args.shard_dir, "pending_meta.txt")
    with open(meta, "w", encoding="utf-8") as f:
        f.write(f"total_cg={len(cg_paths)}\n")
        f.write(f"pending={len(pending)}\n")
        for i, shard in enumerate(shards):
            f.write(f"shard_{i}={len(shard)}\n")

    print(f"pending={len(pending)} shards={args.num_shards} -> {args.shard_dir}")
    for i, shard in enumerate(shards):
        print(f"  pending_{i}.txt: {len(shard)} frames")


if __name__ == "__main__":
    main()
