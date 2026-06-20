#!/usr/bin/env bash
# Print AutoDL instance metadata + ready-to-copy SCP templates for RGBD zip transfer.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
REMOTE_ZIP="${GC2026_ROOT}/data/raw/UVG-CWI-DQPC/__zip"

region="${AutoDLRegion:-unknown}"
dc="${AutoDLDataCenter:-unknown}"
uuid="${AutoDLContainerUUID:-unknown}"
hostname="$(hostname)"

case "$region" in
  west-E|west-E*) SSH_HOST="connect.weste.seetacloud.com" ;;
  west-B|west-B*) SSH_HOST="connect.westb.seetacloud.com" ;;
  west-C|west-C*) SSH_HOST="connect.westc.seetacloud.com" ;;
  north*|North*) SSH_HOST="connect.north.seetacloud.com" ;;
  *) SSH_HOST="connect.weste.seetacloud.com" ;;
esac

echo "=== GC2026 RGBD transfer (run on sender's PC) ==="
echo "Instance hostname : ${hostname}"
echo "Container UUID    : ${uuid}"
echo "Region / DC       : ${region} / ${dc}"
echo "SSH user          : root"
echo "SSH host (region) : ${SSH_HOST}"
echo "SSH port          : (NOT inside container — copy from AutoDL console「SSH连接」)"
echo "Remote zip dir    : ${REMOTE_ZIP}"
echo "Web panel         : ${AutoDLServiceURL:-n/a}"
echo ""
echo "After upload on server:"
echo "  SEQ_FILTER=TicTacToe,VictoryHeart bash ${GC2026_ROOT}/scripts/check_rgbd_download.sh"
echo "  SEQ_FILTER=TicTacToe,VictoryHeart bash ${GC2026_ROOT}/scripts/post_rgbd_install.sh"
echo "  (overnight_nogpu.sh will auto-run Stage1 when check passes)"
echo ""
echo "Required filenames (no .aria2 left):"
echo "  TicTacToe_UVG-CWI-DQPC_v1-0_RGBD.zip"
echo "  VictoryHeart_UVG-CWI-DQPC_v1-0_RGBD.zip"
echo "=== Set PORT from AutoDL console, then run on sender PC ==="
cat <<'EOF'
PORT=你的SSH端口   # 控制台 SSH 指令里的 -p 数字，例如 47964
HOST=connect.weste.seetacloud.com
REMOTE=/root/autodl-tmp/GC2026/data/raw/UVG-CWI-DQPC/__zip

# 单个 zip
scp -P "${PORT}" ./TicTacToe_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/

# val 两条一起
scp -P "${PORT}" \
  ./TicTacToe_UVG-CWI-DQPC_v1-0_RGBD.zip \
  ./VictoryHeart_UVG-CWI-DQPC_v1-0_RGBD.zip \
  root@${HOST}:${REMOTE}/

# 其余序列（每人传自己负责的 zip，文件名勿改）
scp -P "${PORT}" ./BlueSpeech_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/
scp -P "${PORT}" ./BlueVolley_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/
scp -P "${PORT}" ./BouncingBlue_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/
scp -P "${PORT}" ./FitFluencer_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/
scp -P "${PORT}" ./GoodVision_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/
scp -P "${PORT}" ./Mannequin_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/
scp -P "${PORT}" ./OrangeKettlebell_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/
scp -P "${PORT}" ./PinkNoir_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/
scp -P "${PORT}" ./TrumanShow_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/
scp -P "${PORT}" ./VirtualLife_UVG-CWI-DQPC_v1-0_RGBD.zip root@${HOST}:${REMOTE}/
EOF
