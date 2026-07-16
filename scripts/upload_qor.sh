#!/usr/bin/env bash
# =========================================================================
# QoR Recorder - DC 流程自动化上传脚本
#
# 用途: 在 Design Compiler 综合流程结束后, 自动上传 QoR CSV 报告
#
# 用法:
#   ./upload_qor.sh <project_id> <version> <csv_file> [data_type]
#
# 示例:
#   # 上传 QoR 数据
#   ./upload_qor.sh 1 v1.0 qor_report.csv
#
#   # 上传功耗数据
#   ./upload_qor.sh 1 v1.0 power_report.csv power
#
#   # 上传违例路径
#   ./upload_qor.sh 1 v1.0 violation_paths.csv violation
#
# 环境变量:
#   QOR_API_KEY   - API Key (必填, 格式: qor_xxxxxxxx)
#   QOR_SERVER    - 服务器地址 (默认: http://localhost:5000)
#   QOR_MODULE_ID - 模块 ID (可选)
#
# 获取 API Key:
#   1. 登录 Web 界面
#   2. 访问 API 设置页面, 创建 API Key (scope: upload)
#   3. 或调用: curl -X POST $QOR_SERVER/api/v1/auth/login \
#        -H "Content-Type: application/json" \
#        -d '{"username":"admin","password":"admin123"}'
# =========================================================================

set -euo pipefail

# --- 参数检查 ---
if [ "$#" -lt 3 ]; then
    echo "用法: $0 <project_id> <version> <csv_file> [data_type]"
    echo "  data_type: qor (默认) / power / violation"
    exit 1
fi

PROJECT_ID="$1"
VERSION="$2"
CSV_FILE="$3"
DATA_TYPE="${4:-qor}"

# --- 环境变量 ---
API_KEY="${QOR_API_KEY:-}"
SERVER="${QOR_SERVER:-http://localhost:5000}"
MODULE_ID="${QOR_MODULE_ID:-}"

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

# --- 上传 ---
echo "[INFO] 上传 $CSV_FILE -> $SERVER/api/v1/upload"
echo "       project=$PROJECT_ID version=$VERSION type=$DATA_TYPE"

RESPONSE=$(curl -sS -X POST "$SERVER/api/v1/upload" \
    "${FORM_ARGS[@]}" \
    -w "\n%{http_code}" 2>&1) || {
    echo "[ERROR] curl 请求失败"
    exit 1
}

# --- 解析响应 ---
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

echo "[INFO] HTTP 状态: $HTTP_CODE"
echo "[INFO] 响应: $BODY"

if [ "$HTTP_CODE" = "200" ]; then
    echo "[OK] 上传成功"
    exit 0
else
    echo "[FAIL] 上传失败 (HTTP $HTTP_CODE)"
    exit 1
fi
