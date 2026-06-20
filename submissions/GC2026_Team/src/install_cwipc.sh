#!/usr/bin/env bash
# Install cwipc v7.7.5 (Ubuntu 22.04) + Python CLI + librealsense for bag playback.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
LOG="${GC2026_ROOT}/output/install_cwipc.log"
TMP="${GC2026_ROOT}/output/cwipc_install_cache"
CWIPC_VERSION="7.7.5"
CWIPC_DEB_URL="https://github.com/cwi-dis/cwipc/releases/download/v${CWIPC_VERSION}/cwipc-ubuntu2204-v${CWIPC_VERSION}.deb"
LIBRS_TAG="v2.56.5"
LIBRS_TAR="${TMP}/librealsense-2.56.5.tar.gz"
LIBRS_TAR_URL="https://github.com/IntelRealSense/librealsense/archive/refs/tags/v2.56.5.tar.gz"
LIBRS_SRC="${TMP}/librealsense-2.56.5"
LIBRS_BUILD="${LIBRS_SRC}/build"
MINICONDA_BIN="/root/miniconda3/bin"

exec > >(tee -a "$LOG") 2>&1
echo "[install_cwipc] START $(date -Is)"

export DEBIAN_FRONTEND=noninteractive
mkdir -p "$TMP"

INSTALL_LOCK="${TMP}/install_cwipc.lock"
exec 9>"$INSTALL_LOCK"
if ! flock -n 9; then
  echo "[install_cwipc] another install_cwipc is running — waiting..."
  flock 9
fi

pick_python() {
  if command -v python3.12 >/dev/null 2>&1; then
    echo python3.12
    return 0
  fi
  if [ -x "${MINICONDA_BIN}/python3.12" ]; then
    echo "${MINICONDA_BIN}/python3.12"
    return 0
  fi
  echo python3
}

PY="$(pick_python)"
echo "[install_cwipc] Python: $PY ($($PY --version 2>&1))"

ensure_python312() {
  if "$PY" -c 'import sys; assert sys.version_info >= (3, 12)' 2>/dev/null; then
    return 0
  fi
  echo "[install_cwipc] Installing python3.12 (cwipc wheels require >=3.12)..."
  apt-get install -y -qq software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -qq
  apt-get install -y -qq python3.12 python3.12-venv python3.12-dev
  PY=python3.12
}

ensure_cwipc_deb() {
  if dpkg -s cwipc >/dev/null 2>&1; then
    echo "[install_cwipc] cwipc deb already installed: $(dpkg -s cwipc | grep ^Version)"
    return 0
  fi
  deb="${TMP}/cwipc-ubuntu2204-v${CWIPC_VERSION}.deb"
  if [ ! -f "$deb" ]; then
    echo "[install_cwipc] Downloading deb..."
    if command -v aria2c >/dev/null 2>&1; then
      aria2c -x 16 -s 16 -k 1M -d "$TMP" -o "$(basename "$deb")" "$CWIPC_DEB_URL"
    else
      curl -fsSL -o "$deb" "$CWIPC_DEB_URL"
    fi
  fi
  echo "[install_cwipc] Installing deb..."
  apt-get install -y -qq "$deb"
}

fix_libexec_symlinks() {
  mkdir -p /usr/local/libexec/cwipc
  for f in /usr/libexec/cwipc/*; do
    ln -sf "$f" "/usr/local/libexec/cwipc/$(basename "$f")"
  done
}

ensure_librealsense() {
  if ldconfig -p 2>/dev/null | grep -q 'librealsense2.so.2.56'; then
    echo "[install_cwipc] librealsense2.so.2.56 found in ldconfig"
    return 0
  fi
  for d in /usr/local/lib /usr/lib/x86_64-linux-gnu "${LIBRS_BUILD}" "${LIBRS_BUILD}/Release"; do
    if [ -f "${d}/librealsense2.so.2.56" ]; then
      echo "[install_cwipc] librealsense2.so.2.56 found in ${d}"
      export LD_LIBRARY_PATH="${d}:${LD_LIBRARY_PATH:-}"
      return 0
    fi
  done

  echo "[install_cwipc] Building librealsense ${LIBRS_TAG} from source tarball..."
  apt-get install -y -qq cmake build-essential libssl-dev libusb-1.0-0-dev libudev-dev pkg-config

  tar_ok() {
    [ -f "$LIBRS_TAR" ] || return 1
    local sz
    sz=$(wc -c < "$LIBRS_TAR")
    # GitHub tag tarball is ~26–35MB; smaller files are truncated downloads.
    [ "$sz" -ge 25000000 ] || return 1
    tar -tzf "$LIBRS_TAR" "librealsense-2.56.5/CMakeLists.txt" >/dev/null 2>&1
  }

  download_librealsense_tar() {
    echo "[install_cwipc] Downloading librealsense tarball..."
    rm -f "$LIBRS_TAR"
    local urls=(
      "https://ghfast.top/https://github.com/IntelRealSense/librealsense/archive/refs/tags/v2.56.5.tar.gz"
      "https://github.com/IntelRealSense/librealsense/archive/refs/tags/v2.56.5.tar.gz"
    )
    for url in "${urls[@]}"; do
      echo "[install_cwipc] try: $url"
      if curl -fsSL --connect-timeout 30 --max-time 7200 --retry 3 -o "$LIBRS_TAR" "$url" && tar_ok; then
        echo "[install_cwipc] tarball OK ($(du -h "$LIBRS_TAR" | cut -f1))"
        return 0
      fi
      rm -f "$LIBRS_TAR"
    done
    return 1
  }

  if ! tar_ok; then
    download_librealsense_tar || true
  fi

  if ! tar_ok; then
    echo "[install_cwipc] librealsense tarball incomplete — SCP full v2.56.5.tar.gz to $LIBRS_TAR"
    return 1
  fi

  rm -rf "$LIBRS_SRC"
  tar -xzf "$LIBRS_TAR" -C "$TMP"
  if [ ! -f "${LIBRS_SRC}/CMakeLists.txt" ]; then
    echo "[install_cwipc] extract failed — missing ${LIBRS_SRC}/CMakeLists.txt"
    return 1
  fi

  # Prefetch nlohmann/json from SCP'd tarball (avoids GitHub during cmake).
  prefetch_nlohmann_json() {
    local json_dir="${LIBRS_BUILD}/third-party/json"
    local json_tar="${TMP}/json-3.11.3.tar.gz"
    mkdir -p "$(dirname "$json_dir")"
    rm -rf "$json_dir"
    if [ -f "$json_tar" ]; then
      echo "[install_cwipc] extracting SCP'd nlohmann/json from $json_tar"
      mkdir -p "$json_dir"
      if tar -xzf "$json_tar" -C "$json_dir" --strip-components=1 \
        && [ -f "${json_dir}/CMakeLists.txt" ]; then
        echo "[install_cwipc] nlohmann/json OK"
        return 0
      fi
      rm -rf "$json_dir"
    fi
    for url in \
      "https://ghfast.top/https://github.com/nlohmann/json/archive/refs/tags/v3.11.3.tar.gz" \
      "https://github.com/nlohmann/json/archive/refs/tags/v3.11.3.tar.gz"; do
      echo "[install_cwipc] download nlohmann/json: $url"
      if curl -fsSL --connect-timeout 30 --max-time 900 --retry 2 -o "$json_tar" "$url"; then
        mkdir -p "$json_dir"
        if tar -xzf "$json_tar" -C "$json_dir" --strip-components=1 \
          && [ -f "${json_dir}/CMakeLists.txt" ]; then
          return 0
        fi
      fi
      rm -rf "$json_dir"
    done
    return 1
  }

  patch_external_json_skip_fetch() {
    python3 <<PY
from pathlib import Path
p = Path("${LIBRS_SRC}/CMake/external_json.cmake")
text = p.read_text(encoding="utf-8")
needle = "function(get_nlohmann_json)\\n"
inject = """function(get_nlohmann_json)
    if(EXISTS "\${CMAKE_BINARY_DIR}/third-party/json/CMakeLists.txt")
        add_subdirectory( "\${CMAKE_BINARY_DIR}/third-party/json"
                          "\${CMAKE_BINARY_DIR}/third-party/json/build" )
        message(STATUS "Using prefetched nlohmann/json")
        return()
    endif()
"""
if "prefetched nlohmann/json" not in text:
    text = text.replace(needle, inject, 1)
    p.write_text(text, encoding="utf-8")
PY
  }

  rm -rf "$LIBRS_BUILD"
  if ! prefetch_nlohmann_json; then
    echo "[install_cwipc] WARN: nlohmann/json prefetch failed"
  fi
  patch_external_json_skip_fetch

  cmake -S "$LIBRS_SRC" -B "$LIBRS_BUILD" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_EXAMPLES=false \
    -DBUILD_GRAPHICAL_EXAMPLES=false \
    -DBUILD_WITH_OPENGL=false \
    -DBUILD_TOOLS=false
  # Limit parallel compile jobs — container cgroup is ~2GB; nproc causes OOM kills.
  build_jobs="${LIBRS_BUILD_JOBS:-2}"
  cmake --build "$LIBRS_BUILD" -j"$build_jobs"
  cmake --install "$LIBRS_BUILD"
  ldconfig
}

ensure_pymodules() {
  echo "[install_cwipc] Installing cwipc Python wheels via cwipc_pymodules_install.sh..."
  export CWIPC_PYTHON="$PY"
  if command -v cwipc_pymodules_install.sh >/dev/null 2>&1; then
    cwipc_pymodules_install.sh
  else
    wheeldir="/usr/share/cwipc/python"
    "$PY" -m pip install --quiet importlib.metadata
    "$PY" -m pip install --quiet --upgrade --find-links="$wheeldir" "$wheeldir"/cwipc_*.whl
  fi
}

write_env_snippet() {
  snippet="${GC2026_ROOT}/output/cwipc_env.sh"
  cwipc_bin=""
  if [ -x "${MINICONDA_BIN}/cwipc" ]; then
    cwipc_bin="${MINICONDA_BIN}/cwipc"
  elif command -v cwipc >/dev/null 2>&1; then
    cwipc_bin="$(command -v cwipc)"
  fi
  cat >"$snippet" <<EOF
# Source before running rgbd_to_cg / Full Pipeline Stage1
export PATH="${MINICONDA_BIN}:\$PATH"
export LD_LIBRARY_PATH="/usr/local/lib:/usr/lib/x86_64-linux-gnu:\${LD_LIBRARY_PATH:-}"
export LD_PRELOAD="/usr/lib/x86_64-linux-gnu/libstdc++.so.6\${LD_PRELOAD:+:\${LD_PRELOAD}}"
export CWIPC_PYTHON="${PY}"
EOF
  echo "[install_cwipc] Wrote ${snippet}"
}

verify() {
  export PATH="${MINICONDA_BIN}:$PATH"
  if ! command -v cwipc >/dev/null 2>&1; then
    echo "[install_cwipc] WARN: unified cwipc CLI not on PATH (expected in miniconda after pip wheels)"
    return 1
  fi
  echo "[install_cwipc] cwipc: $(command -v cwipc)"
  cwipc version 2>&1 || true
  cwipc_check 2>&1 | head -25 || true
  "$PY" -c "import cwipc; import _cwipc_realsense2; print('python cwipc OK')"
}

ensure_python312
ensure_cwipc_deb
fix_libexec_symlinks
ensure_librealsense
ensure_pymodules
write_env_snippet
verify || true

echo "[install_cwipc] DONE $(date -Is)"
echo "[install_cwipc] Next: source ${GC2026_ROOT}/output/cwipc_env.sh"
echo "[install_cwipc] Dry-run: python scripts/rgbd_to_cg.py --dry-run --cg-list data/processed/val_cg_only.txt"
