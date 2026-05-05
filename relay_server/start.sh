#!/bin/bash
# LaoLiu Relay Server 启动脚本
# 用法: ./start.sh [port]
#
# 跨平台兼容:
#   - macOS / Linux: 自动查找 python3
#   - 可通过 LAOLIU_PYTHON 环境变量指定 Python 路径

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

PORT="${1:-9236}"

# 优先使用项目 venv
if [ -x "$PROJECT_DIR/.venv/bin/python3" ]; then
  PYTHON="$PROJECT_DIR/.venv/bin/python3"
elif [ -n "$LAOLIU_PYTHON" ]; then
  PYTHON="$LAOLIU_PYTHON"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
elif command -v python &>/dev/null; then
  PYTHON="python"
elif [ -x "/opt/homebrew/bin/python3" ]; then
  PYTHON="/opt/homebrew/bin/python3"
elif [ -x "/usr/local/bin/python3" ]; then
  PYTHON="/usr/local/bin/python3"
else
  echo "❌ 未找到 Python 3。请安装或设置 LAOLIU_PYTHON 环境变量。"
  exit 1
fi

echo "🚀 LaoLiu Relay Server"
echo "   Project: $PROJECT_DIR"
echo "   Port: $PORT"
echo "   Python: $PYTHON"
echo ""

# 启动
exec "$PYTHON" -m relay_server.main
