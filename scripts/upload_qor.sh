#!/usr/bin/env bash
# =========================================================================
# QoR Recorder - DC 流程自动化上传脚本
#
# 用途: 在 Design Compiler 综合流程结束后, 自动上传 CSV 报告到 QoR Recorder
#
# 支持的数据类型 (data_type):
#   qor        - QoR 综合指标 CSV (新建/覆盖 QorRecord, 一行=一个 run)
#   power      - 功耗数据 CSV (合并到已有 QorRecord, 按 模块+版本 匹配)
#   violation  - 违例路径 CSV (关联到已有 QorRecord, 文件名建议含 timing_group)
#   notes      - Run 备注 CSV (2~3 列: item, description[, full_dir])
#
# 用法:
#   ./upload_qor.sh <project_id> <version> <csv_file> [data_type] [options]
#
# 示例:
#   # 1. 上传 QoR 数据
#   ./upload_qor.sh 1 v1.0 qor_report.csv
#
#   # 2. 上传并立即标记为已发布 (对 release 账号可见)
#   ./upload_qor.sh 1 v1.0 qor_report.csv qor --release
#
#   # 3. 上传功耗数据
#   ./upload_qor.sh 1 v1.0 power_report.csv power
#
#   # 4. 上传违例路径 (文件名建议 SRAMCLK_violations.csv)
#   ./upload_qor.sh 1 v1.0 SRAMCLK_violations.csv violation
#
#   # 5. 上传 Run 备注 (2 列: item, description)
#   ./upload_qor.sh 1 v1.0 run_notes.csv notes
#
#   # 6. 上传 Run 备注, 并指定 full_dir 区分多目录 run
#   ./upload_qor.sh 1 v1.0 run_notes.csv notes --full-dir /scratch/runs/v1.0
#
#   # 7. 同时指定模块 ID 和 full_dir
#   QOR_MODULE_ID=5 ./upload_qor.sh 1 v1.0 run_notes.csv notes --full-dir "$PWD"
#
# 环境变量:
#   QOR_API_KEY   - API Key (必填, 格式: qor_xxxxxxxx)
#   QOR_SERVER    - 服务器地址 (默认: http://localhost:5000)
#   QOR_MODULE_ID - 模块 ID (可选, 不传则从 CSV 的 module_name 列识别)
#   QOR_RELEASE   - 设为 1 则自动标记为已发布 (可选, --release 优先)
#   QOR_FULL_DIR  - Run 目录路径 (可选, 用于 notes 数据类型, --full-dir 优先)
#
# 获取 API Key:
#   1. 登录 Web 界面
#   2. 访问 API 设置页面, 创建 API Key (scope: upload)
#   3. 或让管理员分配团队共享的 'dc-bot' 账号 API Key
#
# 退出码:
#   0 - 上传成功
#   1 - 参数/环境错误
#   2 - 上传失败 (HTTP 非 200)
# =========================================================================

set -euo pipefail

# --- 显示用法 ---
usage() {
    cat <<'EOF'
用法: upload_qor.sh <project_id> <version> <csv_file> [data_type] [options]

必填参数:
  project_id    项目 ID (数字)
  version       版本标签 (如 v1.0, 20260722_v2, commit-hash)
  csv_file      CSV 文件路径

可选参数:
  data_type     数据类型: qor (默认) / power / violation / notes

选项 (可放在任意位置):
  --release             上传后立即标记为已发布 (对 release 账号可见)
  --full-dir <DIR>      Run 目录路径 (用于 notes, 区分同 module+version 下的不同 run)
  --release-dir <DIR>   发布目录 (v5.0, 仅 qor 类型有效, 整批覆盖)
  --module-id <ID>      模块 ID (覆盖 QOR_MODULE_ID 环境变量)
  --server <URL>        服务器地址 (覆盖 QOR_SERVER 环境变量)
  -h, --help            显示本帮助

环境变量:
  QOR_API_KEY           API Key (必填)
  QOR_SERVER            服务器地址 (默认 http://localhost:5000)
  QOR_MODULE_ID         模块 ID
  QOR_RELEASE=1         等同 --release
  QOR_FULL_DIR          等同 --full-dir
  QOR_RELEASE_DIR       等同 --release-dir (v5.0)

示例:
  export QOR_API_KEY=qor_xxxxxxxx
  ./upload_qor.sh 1 v1.0 qor_report.csv
  ./upload_qor.sh 1 v1.0 run_notes.csv notes --full-dir "$PWD" --release
  ./upload_qor.sh 1 v1.0 qor.csv qor --release-dir v1.0/main/cpu_core
EOF
    exit 1
}

# --- 解析参数 ---
PROJECT_ID=""
VERSION=""
CSV_FILE=""
DATA_TYPE="qor"
MARK_RELEASED=0
OPT_FULL_DIR=""
OPT_MODULE_ID=""
OPT_SERVER=""

# 至少需要 3 个位置参数
if [ "$#" -lt 3 ]; then
    usage
fi

PROJECT_ID="$1"; shift
VERSION="$1"; shift
CSV_FILE="$1"; shift

# 第 4 个位置参数: data_type (若不以 -- 开头)
if [ "$#" -gt 0 ] && [[ "$1" != --* ]]; then
    DATA_TYPE="$1"; shift
fi

# 解析剩余的 --flag 选项
while [ "$#" -gt 0 ]; do
    case "$1" in
        --release)
            MARK_RELEASED=1
            shift
            ;;
        --full-dir)
            OPT_FULL_DIR="${2:-}"
            shift 2 || { echo "[ERROR] --full-dir 需要参数"; exit 1; }
            ;;
        --release-dir)
            OPT_RELEASE_DIR="${2:-}"
            shift 2 || { echo "[ERROR] --release-dir 需要参数"; exit 1; }
            ;;
        --module-id)
            OPT_MODULE_ID="${2:-}"
            shift 2 || { echo "[ERROR] --module-id 需要参数"; exit 1; }
            ;;
        --server)
            OPT_SERVER="${2:-}"
            shift 2 || { echo "[ERROR] --server 需要参数"; exit 1; }
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "[ERROR] 未知参数: $1"
            usage
            ;;
    esac
done

# --- 校验 data_type ---
case "$DATA_TYPE" in
    qor|power|violation|notes) ;;
    *)
        echo "[ERROR] 无效的 data_type: $DATA_TYPE (应为 qor/power/violation/notes)"
        exit 1
        ;;
esac

# --- 解析最终配置 ---
API_KEY="${QOR_API_KEY:-}"
SERVER="${OPT_SERVER:-${QOR_SERVER:-http://localhost:5000}}"
MODULE_ID="${OPT_MODULE_ID:-${QOR_MODULE_ID:-}}"
FULL_DIR="${OPT_FULL_DIR:-${QOR_FULL_DIR:-}}"
RELEASE_DIR="${OPT_RELEASE_DIR:-${QOR_RELEASE_DIR:-}}"

# QOR_RELEASE=1 等同 --release
if [ "${QOR_RELEASE:-0}" = "1" ]; then
    MARK_RELEASED=1
fi

if [ -z "$API_KEY" ]; then
    echo "[ERROR] 请设置环境变量 QOR_API_KEY"
    echo "  export QOR_API_KEY=qor_xxxxxxxxxxxxxxxx"
    exit 1
fi

if [ ! -f "$CSV_FILE" ]; then
    echo "[ERROR] 文件不存在: $CSV_FILE"
    exit 1
fi

# --- 构造表单 ---
FORM_ARGS=(-H "X-API-Key: $API_KEY"
           -F "project_id=$PROJECT_ID"
           -F "version=$VERSION"
           -F "data_type=$DATA_TYPE"
           -F "files=@$CSV_FILE")

if [ -n "$MODULE_ID" ]; then
    FORM_ARGS+=(-F "module_id=$MODULE_ID")
fi

if [ "$MARK_RELEASED" = "1" ]; then
    FORM_ARGS+=(-F "mark_released=1")
fi

# notes 类型才传 full_dir (其他类型传了也会被后端忽略)
if [ -n "$FULL_DIR" ]; then
    FORM_ARGS+=(-F "full_dir=$FULL_DIR")
fi

# qor 类型才传 release_dir (整批覆盖, v5.0)
if [ -n "$RELEASE_DIR" ] && [ "$DATA_TYPE" = "qor" ]; then
    FORM_ARGS+=(-F "release_dir=$RELEASE_DIR")
fi

# --- 上传 ---
echo "[INFO] 上传 $CSV_FILE -> $SERVER/api/v1/upload"
echo "       project=$PROJECT_ID version=$VERSION type=$DATA_TYPE release=$MARK_RELEASED"
if [ -n "$MODULE_ID" ]; then
    echo "       module_id=$MODULE_ID"
fi
if [ -n "$FULL_DIR" ]; then
    echo "       full_dir=$FULL_DIR"
fi
if [ -n "$RELEASE_DIR" ]; then
    echo "       release_dir=$RELEASE_DIR"
fi

RESPONSE=$(curl -sS -X POST "$SERVER/api/v1/upload" \
    "${FORM_ARGS[@]}" \
    -w "\n%{http_code}" 2>&1) || {
    echo "[ERROR] curl 请求失败"
    exit 2
}

# --- 解析响应 ---
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

echo "[INFO] HTTP 状态: $HTTP_CODE"
echo "[INFO] 响应: $BODY"

if [ "$HTTP_CODE" = "200" ]; then
    echo "[OK] 上传成功 ($DATA_TYPE)"
    exit 0
else
    echo "[FAIL] 上传失败 (HTTP $HTTP_CODE)"
    exit 2
fi
