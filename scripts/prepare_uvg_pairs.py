#!/usr/bin/env python3
"""Generate CG/HE pair lists and optional train/val splits for UVG-CWI-DQPC."""
from __future__ import annotations

import argparse
import json
import os
import random
from collections import defaultdict

from uvg_io import iter_frame_pairs, list_sequences


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare UVG CG/HE pair lists")
    parser.add_argument(
        "--raw-root",
        default="/root/autodl-tmp/GC2026/data/raw",
        help="Directory containing UVG-CWI-DQPC/",
    )
    parser.add_argument(
        "--out-dir",
        default="/root/autodl-tmp/GC2026/data/processed",
        help="Output directory for list files and metadata",
    )
    parser.add_argument("--val-sequences", nargs="*", default=["TicTacToe", "VictoryHeart"])
    parser.add_argument("--seed", type=int, default=21)
    parser.add_argument("--max-frames-per-seq", type=int, default=0, help="0 = no limit")
    args = parser.parse_args()

    all_seqs = list_sequences(args.raw_root)
    val_set = set(args.val_sequences)
    train_seqs = [s for s in all_seqs if s not in val_set]
    val_seqs = [s for s in all_seqs if s in val_set]

    os.makedirs(args.out_dir, exist_ok=True)

    def write_split(name: str, sequences: list[str]) -> dict:
        pairs = iter_frame_pairs(args.raw_root, sequences)
        if args.max_frames_per_seq > 0:
            by_seq: dict[str, list] = defaultdict(list)
            for p in pairs:
                by_seq[p.sequence].append(p)
            limited = []
            rng = random.Random(args.seed)
            for seq in sorted(by_seq.keys()):
                items = sorted(by_seq[seq], key=lambda x: x.frame_id)
                if len(items) > args.max_frames_per_seq:
                    items = items[:args.max_frames_per_seq]
                limited.extend(items)
            pairs = limited

        list_path = os.path.join(args.out_dir, f"{name}_pairs.txt")
        cg_only_path = os.path.join(args.out_dir, f"{name}_cg_only.txt")
        with open(list_path, "w", encoding="utf-8") as f_pairs, open(
            cg_only_path, "w", encoding="utf-8"
        ) as f_cg:
            for pair in pairs:
                he = pair.he_path or ""
                f_pairs.write(f"{pair.cg_path}\t{he}\n")
                f_cg.write(f"{pair.cg_path}\n")

        missing_he = sum(1 for p in pairs if p.he_path is None)
        meta = {
            "split": name,
            "sequences": sequences,
            "num_frames": len(pairs),
            "missing_he": missing_he,
            "pairs_file": list_path,
            "cg_only_file": cg_only_path,
        }
        with open(os.path.join(args.out_dir, f"{name}_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print(f"[{name}] {len(pairs)} frames, missing HE: {missing_he} -> {list_path}")
        return meta

    all_meta = write_split("all", all_seqs)
    train_meta = write_split("train", train_seqs)
    val_meta = write_split("val", val_seqs)

    summary = {
        "raw_root": os.path.abspath(args.raw_root),
        "out_dir": os.path.abspath(args.out_dir),
        "all_sequences": all_seqs,
        "train_sequences": train_seqs,
        "val_sequences": val_seqs,
        "splits": {"all": all_meta, "train": train_meta, "val": val_meta},
    }
    with open(os.path.join(args.out_dir, "dataset_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Done. Summary:", os.path.join(args.out_dir, "dataset_summary.json"))


if __name__ == "__main__":
    main()
