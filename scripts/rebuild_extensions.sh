#!/usr/bin/env bash
# Rebuild SuperPC CUDA extensions after PyTorch upgrade (e.g. torch 2.8+cu128 for RTX 5090).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env_setup.sh
source "$SCRIPT_DIR/env_setup.sh"

SUPERPC="$GC2026_ROOT/code/SuperPC"

pip uninstall -y chamfer_3D emd_assignment pointops 2>/dev/null || true
rm -rf "$SUPERPC/models/pointops/build" "$SUPERPC/Chamfer3D/build" "$SUPERPC/emd_assignment/build"

cd "$SUPERPC/models/pointops" && "$PYTHON" setup.py install
cd "$SUPERPC/Chamfer3D" && "$PYTHON" setup.py install
cd "$SUPERPC/emd_assignment" && "$PYTHON" setup.py install

"$PYTHON" -c "import chamfer_3D; import pointops_cuda; import emd; from emd_assignment import emd_module; print('[rebuild_extensions] OK')"
