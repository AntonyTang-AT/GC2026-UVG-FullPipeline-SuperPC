#!/usr/bin/env bash
# Download SuperPC pretrained weights from official Google Drive Model Zoo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env_setup.sh
source "$SCRIPT_DIR/env_setup.sh"

# PyTorch + CUDA extensions require torch lib path (see env_setup.sh).
# RTX 5090 (sm_120) needs torch>=2.8+cu128 — install via:
#   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

OUT_DIR="${GC2026_ROOT}/models/superpc_pretrained"
DRIVE_URL="https://drive.google.com/drive/folders/1FrQtm8LBVrbdRT4Xs87rIZpJ9nYaTqcG"

mkdir -p "$OUT_DIR"

# Skip download only if a non-smoke official-looking checkpoint exists
existing=$(find "$OUT_DIR" -type f \( -name "*.pth" -o -name "*.pt" \) \
  ! -name "*smoke*" ! -name "*backup*" ! -name "*init*" 2>/dev/null | head -1)
if [[ -n "$existing" ]]; then
  echo "[download_pretrained] Found existing checkpoint(s), skipping download:"
  find "$OUT_DIR" -type f \( -name "*.pth" -o -name "*.pt" \) | sort
  exit 0
fi

if ! timeout 8 curl -fsI --connect-timeout 5 https://drive.google.com >/dev/null 2>&1; then
  echo "[download_pretrained] Google Drive unreachable (curl timeout). Skipping gdown."
else
  echo "[download_pretrained] Installing gdown if needed..."
  pip install -q gdown

  echo "[download_pretrained] Downloading from Google Drive -> $OUT_DIR"
  # Retry up to 3 times with increasing timeout (network to Drive is often flaky).
  for attempt in 1 2 3; do
  timeout_sec=$((120 * attempt))
  echo "[download_pretrained] gdown attempt $attempt (timeout ${timeout_sec}s)"
  if timeout "$timeout_sec" gdown --folder "$DRIVE_URL" -O "$OUT_DIR" --remaining-ok 2>&1; then
    break
  fi
  echo "[download_pretrained] gdown attempt $attempt failed."
  sleep 5
  done
fi

echo "[download_pretrained] Downloaded files:"
find "$OUT_DIR" -type f \( -name "*.pth" -o -name "*.pt" \) | sort

if ! find "$OUT_DIR" -type f \( -name "*.pth" -o -name "*.pt" \) | grep -q .; then
  echo "[download_pretrained] ERROR: No .pth/.pt found after download."
  echo "[download_pretrained] Falling back to random-init smoke checkpoint (NOT official weights)."
  python "$SCRIPT_DIR/create_init_ckpt.py" \
    --out "$OUT_DIR/shapenet_superpc_w_attn_init_smoke.pth"
  if ! find "$OUT_DIR" -type f \( -name "*.pth" -o -name "*.pt" \) | grep -q .; then
    echo "  Manual upload to $OUT_DIR still required for production runs."
    exit 1
  fi
fi
