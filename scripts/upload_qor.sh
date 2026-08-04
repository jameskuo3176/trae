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
# 支持的上传协议:
#   1. multipart/form-data  -> POST /api/v1/upload      (默认, 旧协议)
#   2. application/json     -> POST /api/v1/qor/upload  (--json 启用, JSON §6.5)
#
#   --json 模式会先调用 scripts/csv_to_json.py 将 CSV 转为 §6.5 JSON,
#   然后用单一请求把 records + violation_paths + notes 一起发到新端点.
#   推荐使用, 因为底层共用 save_records_to_db 业务逻辑, 行为一致.
#
# 用法:
#   ./upload_qor.sh <project_id> <version> <csv_file> [data_type] [options]
#
# 示例:
#   # 1. 上传 QoR 数据 (multipart)
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
#   # 8. 使用 JSON §6.5 协议 (推荐)
#   ./upload_qor.sh 1 v1.0 qor_report.csv --json
#   ./upload_qor.sh 1 v1.0 qor_report.csv qor --json --release --release-dir v1.0/main/cpu
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
#   3 - JSON 转换失败
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
  --module-name <NAME>  notes CSV 用, 关联模块 (--json 模式需要)
  --timing-group <TG>   violation CSV 用, 缺省从文件名提取 (--json 模式)
  --server <URL>        服务器地址 (覆盖 QOR_SERVER 环境变量)
  --json                使用 JSON 协议 (POST /api/v1/qor/upload), 推荐
                        配合 JSON 文件时会自动识别 §6.5 / DC 报告格式
  --keep-json <FILE>    --json 模式下保存转换后的 JSON 到指定文件 (调试用)
  -h, --help            显示本帮助

DC 报告格式 (自动识别):
  当 --json 模式 + 输入文件是 JSON 且包含 top_module + timing + area + misc
  顶层字段时, 会被识别为 DC 综合报告格式, 直接转发原始 JSON 到端点.
  关键: project_id / version 不进入 JSON, 走 URL query (?project_id=N&version=V).
  端点自动:
    - module = DC.top_module (无须 --module-name)
    - register_count = DC.misc.fgcg.total_flops
    - raw_dc_report = 完整 DC JSON 透传, Dashboard 表格视图直接渲染
    - full_dir = DC.run.directory
    - 1 个 DC 报告 = 1 条 QorRecord (多 scenarios / path_groups 存到 extra.scenarios)

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
  ./upload_qor.sh 1 v1.0 qor.csv --json --release
  ./upload_qor.sh 1 v1.0 dc_report.json --json --release
  ./upload_qor.sh 1 v1.0 /path/to/dc_report.json --json
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
OPT_MODULE_NAME=""
OPT_TIMING_GROUP=""
OPT_SERVER=""
OPT_RELEASE_DIR=""
USE_JSON=0
KEEP_JSON=""

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
        --module-name)
            OPT_MODULE_NAME="${2:-}"
            shift 2 || { echo "[ERROR] --module-name 需要参数"; exit 1; }
            ;;
        --timing-group)
            OPT_TIMING_GROUP="${2:-}"
            shift 2 || { echo "[ERROR] --timing-group 需要参数"; exit 1; }
            ;;
        --server)
            OPT_SERVER="${2:-}"
            shift 2 || { echo "[ERROR] --server 需要参数"; exit 1; }
            ;;
        --json)
            USE_JSON=1
            shift
            ;;
        --keep-json)
            KEEP_JSON="${2:-}"
            shift 2 || { echo "[ERROR] --keep-json 需要参数"; exit 1; }
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

# =========================================================================
# JSON 协议分支 (兼容 §6.5 JSON, DC 报告 JSON 自动识别)
# =========================================================================
if [ "$USE_JSON" = "1" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    JSON_PAYLOAD=""

    # 文件扩展名为 .json 时, 优先尝试作为已存在的 §6.5 JSON 加载;
    # 若顶层含 top_module + timing/area/misc, 则识别为 DC 报告格式并转换.
    FILE_EXT="${CSV_FILE##*.}"
    if [ "$FILE_EXT" = "json" ] || [ "$FILE_EXT" = "JSON" ]; then
        IS_DC_REPORT=$(python3 -c "
import json, sys
try:
    with open(r'''$CSV_FILE''', 'r', encoding='utf-8') as f:
        d = json.load(f)
    if isinstance(d, dict) and {'top_module','timing','area','misc'}.issubset(d.keys()):
        print('1')
    else:
        print('0')
except Exception:
    print('0')
" 2>/dev/null || echo "0")

        if [ "$IS_DC_REPORT" = "1" ]; then
            # DC 报告格式: 直接把原始 JSON 转发到 /api/v1/qor/upload
            # 关键: project_id / version 不进 JSON, 走 URL query (?project_id=&version=)
            # 端点会自动:
            #   - module = DC.top_module (无须指定)
            #   - register_count = misc.fgcg.total_flops
            #   - raw_dc_report = 完整 DC JSON 透传
            #   - full_dir = run.directory (DC 报告自带的 run 目录)
            #   - 1 个 DC 报告 = 1 条 QorRecord
            echo "[INFO] 检测到 DC 报告格式 -> 直接转发 (project_id/version 走 URL)"

            JSON_PAYLOAD=$(cat "$CSV_FILE")

            # 仅注入后端必需字段 (mark_released, module_id 覆盖, release_dir 覆盖)
            INJECTED_JSON=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
up = data.setdefault('upload', {})
if '$MODULE_ID':
    up['module_id'] = int('$MODULE_ID')
# DC 报告内置 release_dir = run.directory; 命令行 --release-dir 优先级更高
if '$RELEASE_DIR':
    up['release_dir'] = '$RELEASE_DIR'
if $MARK_RELEASED == 1:
    up['mark_released'] = True
print(json.dumps(data, ensure_ascii=False))
" <<< "$JSON_PAYLOAD" 2>/dev/null) || INJECTED_JSON="$JSON_PAYLOAD"

            if [ -n "$KEEP_JSON" ]; then
                echo "$INJECTED_JSON" > "$KEEP_JSON"
            fi
            JSON_PAYLOAD="$INJECTED_JSON"
        else
            # 已是 §6.5 JSON, 直接读
            echo "[INFO] 检测到 §6.5 JSON 格式, 直接读取"
            JSON_PAYLOAD=$(cat "$CSV_FILE")
        fi
    else
        # CSV 文件: 调 csv_to_json.py
        CSV_TO_JSON="${CSV_TO_JSON:-${SCRIPT_DIR}/csv_to_json.py}"
        if [ ! -f "$CSV_TO_JSON" ]; then
            echo "[ERROR] 找不到 csv_to_json.py: $CSV_TO_JSON"
            echo "  请设置 CSV_TO_JSON 环境变量指向正确路径"
            exit 1
        fi

        CSV_ARGS=(--project-id "$PROJECT_ID" --version "$VERSION")
        if [ -n "$FULL_DIR" ]; then
            CSV_ARGS+=(--full-dir "$FULL_DIR")
        fi
        if [ -n "$RELEASE_DIR" ] && [ "$DATA_TYPE" = "qor" ]; then
            CSV_ARGS+=(--release-dir "$RELEASE_DIR")
        fi
        if [ -n "$OPT_MODULE_NAME" ]; then
            CSV_ARGS+=(--module-name "$OPT_MODULE_NAME")
        fi
        if [ -n "$OPT_TIMING_GROUP" ]; then
            CSV_ARGS+=(--timing-group "$OPT_TIMING_GROUP")
        fi
        CSV_ARGS+=(--data-type "$DATA_TYPE")

        echo "[INFO] 转换 $CSV_FILE -> JSON §6.5 (使用 $CSV_TO_JSON)"
        if [ -n "$KEEP_JSON" ]; then
            if ! python3 "$CSV_TO_JSON" "${CSV_ARGS[@]}" -o "$KEEP_JSON" "$CSV_FILE"; then
                echo "[ERROR] CSV -> JSON 转换失败"
                exit 3
            fi
            JSON_PAYLOAD=$(cat "$KEEP_JSON")
            echo "[INFO] JSON 已保存到 $KEEP_JSON"
        else
            JSON_PAYLOAD=$(python3 "$CSV_TO_JSON" "${CSV_ARGS[@]}" "$CSV_FILE") || {
                echo "[ERROR] CSV -> JSON 转换失败"
                exit 3
            }
        fi

        # 注入 upload 顶层字段
        # 注: project_id / version 也走 URL query, JSON 内不重复 (端点会优先用 URL, 兼容旧 JSON 仍然有 upload 字段)
        INJECTED_JSON=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
up = data.setdefault('upload', {})
up['project_id'] = $PROJECT_ID
up['version'] = '$VERSION'
if $MARK_RELEASED == 1:
    up['mark_released'] = True
if '$MODULE_ID':
    up['module_id'] = int('$MODULE_ID')
if '$FULL_DIR':
    up['full_dir'] = '$FULL_DIR'
if '$RELEASE_DIR' and '$DATA_TYPE' == 'qor':
    up['release_dir'] = '$RELEASE_DIR'
print(json.dumps(data, ensure_ascii=False))
" <<< "$JSON_PAYLOAD")

        if [ -n "$KEEP_JSON" ]; then
            echo "$INJECTED_JSON" > "$KEEP_JSON"
        fi
        JSON_PAYLOAD="$INJECTED_JSON"
    fi

    # 5) POST JSON
    # 关键: project_id / version 走 URL query (即使为空也带上, 让端点统一处理)
    UPLOAD_URL="$SERVER/api/v1/qor/upload?project_id=$PROJECT_ID&version=$(printf %s "$VERSION" | python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read()))')"
    echo "[INFO] 上传 -> $UPLOAD_URL"
    echo "       project=$PROJECT_ID version=$VERSION release=$MARK_RELEASED"
    if [ -n "$MODULE_ID" ]; then
        echo "       module_id=$MODULE_ID"
    fi
    if [ -n "$FULL_DIR" ]; then
        echo "       full_dir=$FULL_DIR"
    fi
    if [ -n "$RELEASE_DIR" ]; then
        echo "       release_dir=$RELEASE_DIR"
    fi

    RESPONSE=$(curl -sS -X POST "$UPLOAD_URL" \
        -H "X-API-Key: $API_KEY" \
        -H "Content-Type: application/json" \
        --data-raw "$JSON_PAYLOAD" \
        -w "\n%{http_code}" 2>&1) || {
        echo "[ERROR] curl 请求失败"
        exit 2
    }

    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    echo "[INFO] HTTP 状态: $HTTP_CODE"
    echo "[INFO] 响应: $BODY"

    if [ "$HTTP_CODE" = "200" ]; then
        # 解析 saved/updated/notes/violation_paths 计数 (用 python3 避免 jq 依赖)
        SUMMARY=$(python3 -c "
import json
try:
    d = json.loads('''$BODY''')
    parts = []
    if d.get('saved'):
        parts.append(f\"saved={d['saved']}\")
    if d.get('updated'):
        parts.append(f\"updated={d['updated']}\")
    if d.get('skipped'):
        parts.append(f\"skipped={d['skipped']}\")
    if d.get('violation_paths_saved'):
        parts.append(f\"violations={d['violation_paths_saved']}\")
    if d.get('notes_saved'):
        parts.append(f\"notes={d['notes_saved']}\")
    if d.get('record_ids'):
        parts.append(f\"record_ids={d['record_ids']}\")
    if d.get('alerts_triggered'):
        parts.append(f\"alerts={d['alerts_triggered']}\")
    print(', '.join(parts) or '无变化')
except Exception as e:
    print(f'解析失败: {e}')
" 2>/dev/null || echo "")
        if [ -n "$SUMMARY" ]; then
            echo "[OK] 上传成功 ($SUMMARY)"
        else
            echo "[OK] 上传成功"
        fi
        exit 0
    else
        echo "[FAIL] 上传失败 (HTTP $HTTP_CODE)"
        exit 2
    fi
fi

# =========================================================================
# multipart/form-data 分支 (旧协议, 保持兼容)
# =========================================================================
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
