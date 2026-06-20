#!/usr/bin/env python3
"""Inflate single deflated entry from a zip local-header + data chunk file."""
from __future__ import annotations

import struct
import sys
import zlib

ZIP64_EXTRA_ID = 0x0001


def sizes_from_header(head: bytes) -> tuple[int, int, int]:
    comp32, uncomp32 = struct.unpack("<II", head[18:26])
    fn_len, extra_len = struct.unpack("<HH", head[26:30])
    header_size = 30 + fn_len + extra_len
    comp, uncomp = comp32, uncomp32
    if comp32 == 0xFFFFFFFF or uncomp32 == 0xFFFFFFFF:
        extra = head[30 + fn_len : 30 + fn_len + extra_len]
        pos = 0
        while pos + 4 <= len(extra):
            hid, dsz = struct.unpack("<HH", extra[pos : pos + 4])
            data = extra[pos + 4 : pos + 4 + dsz]
            if hid == ZIP64_EXTRA_ID:
                p = 0
                if uncomp32 == 0xFFFFFFFF:
                    uncomp = struct.unpack("<Q", data[p : p + 8])[0]
                    p += 8
                if comp32 == 0xFFFFFFFF:
                    comp = struct.unpack("<Q", data[p : p + 8])[0]
                break
            pos += 4 + dsz
    return header_size, comp, uncomp


def main() -> None:
    chunk_path, out_path = sys.argv[1:3]
    with open(chunk_path, "rb") as f:
        head = f.read(65536)
    header_size, comp_size, uncomp_size = sizes_from_header(head)
    dec = zlib.decompressobj(-zlib.MAX_WBITS)
    written = 0
    with open(chunk_path, "rb") as src, open(out_path, "wb") as dst:
        src.seek(header_size)
        rem = comp_size
        while rem > 0:
            block = src.read(min(4 * 1024 * 1024, rem))
            if not block:
                break
            rem -= len(block)
            raw = dec.decompress(block)
            if raw:
                dst.write(raw)
                written += len(raw)
        tail = dec.flush()
        if tail:
            dst.write(tail)
            written += len(tail)
    if written != uncomp_size:
        raise SystemExit(f"inflate size mismatch: {written} vs {uncomp_size}")
    print(f"[inflate] wrote {out_path} ({written/1e9:.3f} GB)")


if __name__ == "__main__":
    main()
