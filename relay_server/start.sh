#!/bin/bash
# Phoenix Relay Server 启动脚本
# 用法: ./start.sh [port]
#
# 跨平台兼容:
#   - macOS / Linux: 自动查找 python3
#   - 可通过 PHOENIX_PYTHON 环境变量指定 Python 路径

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${1:-9236}"

# 查找 Python
if [ -n "$PHOENIX_PYTHON" ]; then
  PYTHON="$PHOENIX_PYTHON"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
elif command -v python &>/dev/null; then
  PYTHON="python"
elif [ -x "/opt/homebrew/bin/python3" ]; then
  PYTHON="/opt/homebrew/bin/python3"
elif [ -x "/usr/local/bin/python3" ]; then
  PYTHON="/usr/local/bin/python3"
else
  echo "❌ 未找到 Python 3。请安装或设置 PHOENIX_PYTHON 环境变量。"
  exit 1
fi

echo "🚀 Phoenix Relay Server"
echo "   Port: $PORT"
echo "   Python: $PYTHON"
echo ""

# 设置端口
export PHOENIX_RELAY_PORT="$PORT"

# 启动
exec "$PYTHON" -c "
import sys
sys.path.insert(0, '.')
from relay_server.config import RELAY_PORT
import os
# Override port if set
if os.environ.get('PHOENIX_RELAY_PORT'):
    from relay_server import config
    config.RELAY_PORT = int(os.environ.get('PHOENIX_RELAY_PORT'))
from relay_server.main import main
main()
"
