# Source this before running SuperPC scripts:
#   source /root/autodl-tmp/GC2026/scripts/env_setup.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export GC2026_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export SUPERPC_ROOT="$GC2026_ROOT/code/SuperPC"

source /root/miniconda3/etc/profile.d/conda.sh
conda activate superpc

export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib/python3.9/site-packages/torch/lib:${LD_LIBRARY_PATH}"

# RTX 5090 (sm_120) requires torch 2.8+cu128:
#   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
# Then: bash scripts/rebuild_extensions.sh
