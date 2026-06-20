#!/usr/bin/env python3
"""Range-download one deflated entry from a remote zip and extract it (streaming, low RAM)."""
from __future__ import annotations

import argparse
import os
import struct
import urllib.request
import zlib

ZIP64_EXTRA_ID = 0x0001


def read_zip64_sizes(head: bytes, comp32: int, uncomp32: int) -> tuple[int, int]:
    if comp32 != 0xFFFFFFFF and uncomp32 != 0xFFFFFFFF:
        return comp32, uncomp32
    fn_len, extra_len = struct.unpack("<HH", head[26:30])
    extra = head[30 + fn_len : 30 + fn_len + extra_len]
    pos = 0
    while pos + 4 <= len(extra):
        hid, dsz = struct.unpack("<HH", extra[pos : pos + 4])
        data = extra[pos + 4 : pos + 4 + dsz]
        if hid == ZIP64_EXTRA_ID:
            p = 0
            uncomp = uncomp32
            comp = comp32
            if uncomp32 == 0xFFFFFFFF:
                uncomp = struct.unpack("<Q", data[p : p + 8])[0]
                p += 8
            if comp32 == 0xFFFFFFFF:
                comp = struct.unpack("<Q", data[p : p + 8])[0]
                p += 8
            return comp, uncomp
        pos += 4 + dsz
    raise ValueError("zip64 extra field not found")


def parse_header(blob: bytes) -> tuple[int, int, int, str]:
    if blob[:4] != b"PK\x03\x04":
        raise ValueError(f"bad local header signature: {blob[:4]!r}")
    comp32, uncomp32 = struct.unpack("<II", blob[18:26])
    comp_size, uncomp_size = read_zip64_sizes(blob, comp32, uncomp32)
    fn_len, extra_len = struct.unpack("<HH", blob[26:30])
    header_size = 30 + fn_len + extra_len
    if len(blob) < header_size:
        raise ValueError(f"header truncated: need {header_size} bytes, got {len(blob)}")
    name = blob[30 : 30 + fn_len].decode("utf-8", "replace")
    return header_size, comp_size, uncomp_size, name


def range_fetch(url: str, start: int, length: int, out_path: str, chunk_mb: int = 4) -> None:
    chunk = chunk_mb * 1024 * 1024
    got = 0
    with open(out_path, "wb") as out:
        while got < length:
            req_start = start + got
            req_end = min(start + length - 1, req_start + chunk - 1)
            req = urllib.request.Request(
                url, headers={"Range": f"bytes={req_start}-{req_end}"}
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                part = resp.read()
            out.write(part)
            got += len(part)
            pct = 100.0 * got / length
            print(f"\r[fetch] {got/1e9:.2f}/{length/1e9:.2f} GB ({pct:.1f}%)", end="", flush=True)
    print()


def inflate_chunk_file(chunk_path: str, header_size: int, comp_size: int, uncomp_size: int, out_path: str) -> None:
    dec = zlib.decompressobj(-zlib.MAX_WBITS)
    written = 0
    read_block = 4 * 1024 * 1024
    with open(chunk_path, "rb") as src, open(out_path, "wb") as dst:
        src.seek(header_size)
        remaining = comp_size
        while remaining > 0:
            block = src.read(min(read_block, remaining))
            if not block:
                break
            remaining -= len(block)
            raw = dec.decompress(block)
            if raw:
                dst.write(raw)
                written += len(raw)
        tail = dec.flush()
        if tail:
            dst.write(tail)
            written += len(tail)
    if written != uncomp_size:
        raise SystemExit(f"size mismatch after inflate: {written} vs {uncomp_size}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--offset", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--chunk-mb", type=int, default=4)
    p.add_argument("--keep-chunk", action="store_true")
    args = p.parse_args()

    probe_end = args.offset + 65535
    req = urllib.request.Request(
        args.url, headers={"Range": f"bytes={args.offset}-{probe_end}"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        head = resp.read()
    header_size, comp_size, uncomp_size, name = parse_header(head)
    total = header_size + comp_size
    end = args.offset + total - 1
    print(f"[fetch] entry={name.split('/')[-1]} header={header_size} comp={comp_size} uncomp={uncomp_size}")
    print(f"[fetch] range bytes={args.offset}-{end} ({total/1e9:.3f} GB)")

    chunk_path = args.out + ".zipchunk"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    range_fetch(args.url, args.offset, total, chunk_path, chunk_mb=args.chunk_mb)
    print("[fetch] inflating...")
    inflate_chunk_file(chunk_path, header_size, comp_size, uncomp_size, args.out)
    if not args.keep_chunk:
        os.remove(chunk_path)
    print(f"[fetch] wrote {args.out} ({uncomp_size/1e9:.3f} GB)")


if __name__ == "__main__":
    main()
