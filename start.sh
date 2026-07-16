#!/usr/bin/env bash
# =========================================================================
# QoR Recorder - Linux 启动脚本
#
# 用法:
#   ./start.sh                # 默认配置启动
#   PORT=1344 ./start.sh      # 自定义端口
#   HOST=127.0.0.1 PORT=8080 DEBUG=1 ./start.sh
#
# 加载 .env 文件 (若存在):
#   1. 复制 .env.example 为 .env 并修改
#   2. 本脚本会自动 source .env
# =========================================================================
set -euo pipefail

cd "$(dirname "$0")"

# 加载 .env (若存在)
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "[INFO] 已加载 .env 配置"
fi

# 默认值
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-5000}"
export DEBUG="${DEBUG:-0}"

# 创建必要目录
mkdir -p uploads backups

# 激活虚拟环境 (若存在)
if [ -d venv ]; then
    source venv/bin/activate
    echo "[INFO] 已激活 venv"
elif [ -d .venv ]; then
    source .venv/bin/activate
    echo "[INFO] 已激活 .venv"
fi

# 安装依赖 (首次运行)
if ! python -c "import flask" 2>/dev/null; then
    echo "[INFO] 安装依赖..."
    pip install -r requirements.txt
fi

# 初始化数据库 (首次运行)
if [ ! -f qor_recorder.db ] && [ -z "${DATABASE_URL:-}" ]; then
    echo "[INFO] 首次运行, 初始化数据库..."
    python init_db.py
fi

echo "[INFO] 启动 QoR Recorder: ${HOST}:${PORT} (debug=${DEBUG})"
exec python app.py
