# Source this before running SuperPC scripts:
#   source /root/autodl-tmp/GC2026/scripts/env_setup.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export GC2026_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export SUPERPC_ROOT="$GC2026_ROOT/code/SuperPC"

source /root/miniconda3/etc/profile.d/conda.sh
conda activate superpc

# Ensure conda env python wins over base miniconda (py3.12 vs py3.9 mismatch broke torch/chamfer).
export PATH="${CONDA_PREFIX}/bin:${PATH}"
export PYTHON="${CONDA_PREFIX}/bin/python3.9"

PYVER="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib/python${PYVER}/site-packages/torch/lib:${LD_LIBRARY_PATH:-}"
