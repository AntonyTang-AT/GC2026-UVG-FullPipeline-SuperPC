#!/usr/bin/env python3
"""Build competition-style manifest.json and README for enhanced outputs."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

PIPELINE_VERSION = "gc2026-superpc-v3"
DEFAULT_PROCESSING_TRACK = "Enhancement Only"
COORDINATE_SYSTEM = "UVG-CWI-DQPC consumer-grade capture coordinates (mm, same as input CG PLY)"


def collect_ply_files(root: str) -> list[dict]:
    entries = []
    for seq in sorted(os.listdir(root)):
        seq_dir = os.path.join(root, seq)
        if not os.path.isdir(seq_dir):
            continue
        for fname in sorted(os.listdir(seq_dir)):
            if not fname.endswith(".ply"):
                continue
            path = os.path.join(seq_dir, fname)
            entries.append(
                {
                    "sequence": seq,
                    "filename": fname,
                    "path": os.path.abspath(path),
                }
            )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Create submission manifest")
    parser.add_argument("--enhanced-dir", required=True, help="Root with per-sequence PLY folders")
    parser.add_argument("--out-dir", default=None, help="Where to write manifest (default: enhanced-dir)")
    parser.add_argument("--title", default="UVG-CWI-DQPC GC2026 Track1 SuperPC Enhancement")
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--team", default="GC2026 Team")
    parser.add_argument(
        "--processing-track",
        default=DEFAULT_PROCESSING_TRACK,
        choices=["Enhancement Only", "Full Pipeline"],
        help="UVG-CWI submissions processing track",
    )
    parser.add_argument("--pipeline-notes", default="", help="Short description of reconstruction + enhancement stages")
    parser.add_argument("--post-processing", default="", help="JSON string or path describing blend/vision params")
    parser.add_argument("--cg-version", default=os.environ.get("UVG_CG_VERSION", "v2"))
    parser.add_argument("--cg-source", default="", help="official | reconstructed")
    args = parser.parse_args()

    post_processing = {}
    if args.post_processing:
        if os.path.isfile(args.post_processing):
            with open(args.post_processing, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                post_processing = loaded.get("best_config", loaded)
        else:
            post_processing = json.loads(args.post_processing)

    out_dir = args.out_dir or args.enhanced_dir
    os.makedirs(out_dir, exist_ok=True)
    frames = collect_ply_files(args.enhanced_dir)

    if args.cg_source:
        post_processing = dict(post_processing)
        post_processing["cg_source"] = args.cg_source
    post_processing = dict(post_processing)
    post_processing["cg_version"] = args.cg_version

    manifest = {
        "title": args.title,
        "team": args.team,
        "pipeline": PIPELINE_VERSION,
        "processing_track": args.processing_track,
        "coordinate_system": COORDINATE_SYSTEM,
        "fps": args.fps,
        "pipeline_notes": args.pipeline_notes,
        "post_processing": post_processing,
        "cg_version": args.cg_version,
        "cg_source": args.cg_source or post_processing.get("cg_source", "official"),
        "frame_index_note": "ENH filenames mirror CG with _CG_ replaced by _ENH_; same 4-digit frame index",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "num_frames": len(frames),
        "sequences": sorted({e["sequence"] for e in frames}),
        "frames": frames,
    }

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    readme_path = os.path.join(out_dir, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(
            f"# {args.title}\n\n"
            f"- Processing track: **{args.processing_track}**\n"
            f"- Pipeline notes: {args.pipeline_notes or 'SuperPC enhancement'}\n"
            f"- Frames: {len(frames)}\n"
            f"- Sequences: {', '.join(manifest['sequences'])}\n"
            f"- Generated: {manifest['created_at']}\n"
        )

    print(f"manifest.json -> {manifest_path}")
    print(f"README.md -> {readme_path}")


if __name__ == "__main__":
    main()
