#!/usr/bin/env python3
"""Synthetic tests for transform_matrix helpers."""
from __future__ import annotations

import json
import os
import sys
import tempfile

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from uvg_io import apply_transform_xyz, load_transform_matrix  # noqa: E402


def main() -> None:
    mat = np.eye(4)
    mat[0, 3] = 10.0
    mat[1, 3] = -5.0
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]], dtype=np.float32)
    out = apply_transform_xyz(pts, mat)
    assert np.allclose(out[0], [10, -5, 0])
    assert np.allclose(out[1], [11, -3, 3])

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.json")
        with open(path, "w") as f:
            json.dump({"transform_matrix": mat.tolist()}, f)
        loaded = load_transform_matrix(path)
        assert np.allclose(loaded, mat)

    print("[test_transform_matrix] OK")


if __name__ == "__main__":
    main()
