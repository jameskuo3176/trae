#!/usr/bin/env bash
# =========================================================================
# QoR Recorder - Django/Gunicorn Linux 启动脚本
#
# 用法:
#   ./start.sh                # 默认配置启动
#   PORT=1344 ./start.sh      # 自定义端口
#   HOST=127.0.0.1 PORT=5000 ./start.sh
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
export GUNICORN_WORKERS="${GUNICORN_WORKERS:-3}"
export GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"
# 关闭 stdout 缓冲，否则 systemd/journal 下长时间看不到 print/logging
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
# DEBUG=1 -> gunicorn/django DEBUG；可用 LOG_LEVEL 显式覆盖
if [ -z "${LOG_LEVEL:-}" ]; then
    if [ "$DEBUG" = "1" ]; then
        export LOG_LEVEL=DEBUG
    else
        export LOG_LEVEL=INFO
    fi
fi
case "$(echo "$LOG_LEVEL" | tr '[:lower:]' '[:upper:]')" in
    DEBUG) GUNICORN_LOG_LEVEL=debug ;;
    WARNING|ERROR|CRITICAL) GUNICORN_LOG_LEVEL=warning ;;
    *) GUNICORN_LOG_LEVEL=info ;;
esac

# 创建必要目录
export DATA_DIR="${DATA_DIR:-$(pwd)/data}"
export UPLOAD_FOLDER="${UPLOAD_FOLDER:-$(pwd)/uploads}"
export BACKUP_DIR="${BACKUP_DIR:-$(pwd)/backups}"
export LOG_DIR="${LOG_DIR:-$(pwd)/logs}"
mkdir -p "$DATA_DIR" "$UPLOAD_FOLDER" "$BACKUP_DIR" "$LOG_DIR"

# 激活虚拟环境 (若存在)
if [ -d venv ]; then
    source venv/bin/activate
    echo "[INFO] 已激活 venv"
elif [ -d .venv ]; then
    source .venv/bin/activate
    echo "[INFO] 已激活 .venv"
fi

# 启动脚本不联网安装依赖；离线部署必须提前准备好 venv。
if ! python -c "import django, gunicorn" 2>/dev/null; then
    echo "[ERROR] Django/Gunicorn 未安装。请先按 deploy/README.md 创建离线 venv。" >&2
    exit 1
fi

echo "[INFO] DEBUG=${DEBUG} LOG_LEVEL=${LOG_LEVEL} PYTHONUNBUFFERED=${PYTHONUNBUFFERED}"
echo "[INFO] 应用日志: ${LOG_DIR}/qor_recorder.log  |  systemd: journalctl -u qor_recorder -f"

echo "[INFO] 应用 Django 数据库迁移..."
python manage.py migrate --noinput

echo "[INFO] 启动 QoR Recorder (Django/Gunicorn): ${HOST}:${PORT} log-level=${GUNICORN_LOG_LEVEL}"
exec python -m gunicorn django_app.wsgi:application \
    --bind "${HOST}:${PORT}" \
    --workers "${GUNICORN_WORKERS}" \
    --timeout "${GUNICORN_TIMEOUT}" \
    --log-level "${GUNICORN_LOG_LEVEL}" \
    --capture-output \
    --access-logfile - \
    --error-logfile -
