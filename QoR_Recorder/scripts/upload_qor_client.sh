#!/usr/bin/env bash
# =========================================================================
# QoR Recorder — workstation upload client (curl + bash; optional python3)
#
# For engineer work machines talking to the deployed Linux server.
# Does NOT require a full /opt/qor_recorder checkout for default CSV upload.
#
# Modes:
#   1) CSV                    -> POST /api/v1/upload (multipart)
#      (sends both files=@csv and file=@csv for old/new servers)
#   2) JSON                   -> POST /api/v1/qor/upload
#      JSON input is auto-detected (.json extension or leading '{'), so --json
#      is optional. Use --multipart to force the legacy CSV endpoint.
#      - Input already §6.5   -> inject CLI fields, then upload
#      - Native DC report JSON -> convert with dc_report_to_json.py, then upload
#      - Input is CSV         -> needs csv_to_json.py client kit (see below)
#
# JSON mode ALWAYS needs a usable full_dir (CLI --full-dir or a supported JSON alias).
#
# Usage:
#   upload_qor_client.sh <project_id> <version> <file> [options]
#
# Options:
#   --json               Force JSON API (/api/v1/qor/upload); auto for .json
#   --multipart          Force legacy multipart CSV API (/api/v1/upload)
#   --full-dir DIR       Run directory (required for --json unless JSON has it)
#   --module-id N        Module ID (optional)
#   --release            Mark uploaded records as released
#   --release-dir DIR    Release directory
#   --server URL         Override QOR_SERVER
#   --env FILE           Env file with QOR_SERVER / QOR_API_KEY
#   -h, --help
#
# Config:
#   QOR_SERVER / QOR_API_KEY
#   CSV_TO_JSON           path to csv_to_json.py (optional)
#   DC_REPORT_TO_JSON     path to dc_report_to_json.py (optional)
#   QOR_CLIENT_ROOT       kit root containing scripts/ + django_app/services/
#
# CSV->JSON kit layout (copy once to work machine, e.g. ~/qor_client):
#   QOR_CLIENT_ROOT/
#     scripts/csv_to_json.py
#     scripts/dc_report_to_json.py
#     django_app/services/csv_field_mapping.py
#     django_app/services/csv_timing.py
#     django_app/services/csv_upload_paths.py
#   Or put the same tree under: <script_dir>/lib/
#
# Env file search (first hit; does not override already-exported vars):
#   --env FILE, $QOR_UPLOAD_ENV, script_dir/qor_upload.env,
#   ~/.qor_upload.env, ~/.config/qor-recorder/upload.env
# =========================================================================

set -euo pipefail

usage() {
    cat <<'EOF'
用法: upload_qor_client.sh <project_id> <version> <file> [options]

必填:
  project_id    项目 ID
  version       版本标签（如 v1.0；--json 时服务端可能仍从 full_dir 派生）
  file          本机 CSV 或 JSON 路径（.json 自动走 JSON 接口）

选项:
  --json              强制走 JSON 接口 POST /api/v1/qor/upload（.json 自动开启）
  --multipart         强制走旧的 multipart CSV 接口 POST /api/v1/upload
  --full-dir DIR      Run 目录（JSON 模式强烈建议/通常必填）
  --module-id N       模块 ID
  --release           上传后标记已发布（一般不要；由网页 Owner 发布）
  --release-dir DIR   发布目录
  --server URL        覆盖 QOR_SERVER
  --env FILE          指定环境文件
  -h, --help

配置: QOR_SERVER, QOR_API_KEY
可选: CSV_TO_JSON, DC_REPORT_TO_JSON, QOR_CLIENT_ROOT

示例（工作目录）:
  # CSV：multipart（最简单，无需 Python / 转换包）
  ./upload_qor_client.sh 2 v1.0 ./module_alu_qor.csv

  # JSON：原生 DC 报告（自动识别；使用 run.full_dir 或 run.directory）
  ./upload_qor_client.sh 2 v1.0 ./Synthesis.qor_summary.json

  # JSON：已有 §6.5 JSON（需 --full-dir，除非已有 upload.full_dir/upload.directory）
  ./upload_qor_client.sh 2 v1.0 ./run.json --full-dir /scratch/runs/v1.0

  # JSON：CSV 先转换再上传（需一次拷贝的 client kit + python3）
  export QOR_CLIENT_ROOT=~/qor_client
  ./upload_qor_client.sh 2 v1.0 ./module_alu_qor.csv --json --full-dir "$PWD"
EOF
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT_ID=""
VERSION=""
INPUT_FILE=""
OPT_MODULE_ID=""
MARK_RELEASED=0
OPT_RELEASE_DIR=""
OPT_FULL_DIR=""
OPT_SERVER=""
OPT_ENV=""
USE_JSON=0
FORCE_MULTIPART=0

if [ "$#" -lt 1 ]; then
    usage
fi

case "$1" in
    -h|--help) usage ;;
esac

if [ "$#" -lt 3 ]; then
    echo "[ERROR] 参数不足。需要: <project_id> <version> <file>"
    echo
    usage
fi

PROJECT_ID="$1"; shift
VERSION="$1"; shift
INPUT_FILE="$1"; shift

while [ "$#" -gt 0 ]; do
    case "$1" in
        --module-id)
            OPT_MODULE_ID="${2:-}"
            shift 2 || { echo "[ERROR] --module-id 需要参数"; exit 1; }
            ;;
        --release)
            MARK_RELEASED=1
            shift
            ;;
        --release-dir)
            OPT_RELEASE_DIR="${2:-}"
            shift 2 || { echo "[ERROR] --release-dir 需要参数"; exit 1; }
            ;;
        --full-dir)
            OPT_FULL_DIR="${2:-}"
            shift 2 || { echo "[ERROR] --full-dir 需要参数"; exit 1; }
            ;;
        --server)
            OPT_SERVER="${2:-}"
            shift 2 || { echo "[ERROR] --server 需要参数"; exit 1; }
            ;;
        --env)
            OPT_ENV="${2:-}"
            shift 2 || { echo "[ERROR] --env 需要参数"; exit 1; }
            ;;
        --json)
            USE_JSON=1
            shift
            ;;
        --multipart|--no-json)
            FORCE_MULTIPART=1
            shift
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

# --- load env file without overriding already-exported vars ---
_SAVED_KEY="${QOR_API_KEY:-}"
_SAVED_SERVER="${QOR_SERVER:-}"

source_env_file() {
    local f="$1"
    if [ -n "$f" ] && [ -f "$f" ]; then
        # shellcheck disable=SC1090
        set -a
        # Strip CR so a Windows-copied env file still works on Linux.
        # shellcheck disable=SC1091
        source /dev/stdin <<EOF
$(tr -d '\r' < "$f")
EOF
        set +a
        echo "[INFO] 已加载配置: $f"
        return 0
    fi
    return 1
}

if [ -n "$OPT_ENV" ]; then
    if [ ! -f "$OPT_ENV" ]; then
        echo "[ERROR] 找不到 --env 文件: $OPT_ENV"
        exit 1
    fi
    source_env_file "$OPT_ENV" || true
else
    if [ -n "${QOR_UPLOAD_ENV:-}" ]; then
        if [ ! -f "$QOR_UPLOAD_ENV" ]; then
            echo "[ERROR] QOR_UPLOAD_ENV 指向的文件不存在: $QOR_UPLOAD_ENV"
            exit 1
        fi
        source_env_file "$QOR_UPLOAD_ENV" || true
    else
        source_env_file "${SCRIPT_DIR}/qor_upload.env" \
            || source_env_file "${HOME}/.qor_upload.env" \
            || source_env_file "${HOME}/.config/qor-recorder/upload.env" \
            || true
    fi
fi

if [ -n "$_SAVED_KEY" ]; then
    QOR_API_KEY="$_SAVED_KEY"
fi
if [ -n "$_SAVED_SERVER" ]; then
    QOR_SERVER="$_SAVED_SERVER"
fi

API_KEY="${QOR_API_KEY:-}"
SERVER="${OPT_SERVER:-${QOR_SERVER:-}}"
MODULE_ID="${OPT_MODULE_ID:-${QOR_MODULE_ID:-}}"
RELEASE_DIR="${OPT_RELEASE_DIR:-${QOR_RELEASE_DIR:-}}"
FULL_DIR="${OPT_FULL_DIR:-${QOR_FULL_DIR:-}}"

if [ "${QOR_RELEASE:-0}" = "1" ]; then
    MARK_RELEASED=1
fi

if [ -z "$API_KEY" ]; then
    echo "[ERROR] 未设置 QOR_API_KEY。"
    echo "  请 export QOR_API_KEY=qor_xxxxxxxx"
    echo "  或在脚本同目录放置 qor_upload.env（见 qor_upload.env.example）。"
    exit 1
fi

if [ -z "$SERVER" ]; then
    echo "[ERROR] 未设置 QOR_SERVER。"
    echo "  请 export QOR_SERVER=http://<部署机主机名或IP>:5000"
    echo "  或写入 qor_upload.env。不要用默认 localhost（会打到本机）。"
    exit 1
fi

SERVER="${SERVER%/}"

if [ ! -f "$INPUT_FILE" ]; then
    echo "[ERROR] 文件不存在: $INPUT_FILE"
    echo "        必须是工作机上的本地文件路径。"
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "[ERROR] 找不到 curl。请先安装 curl。"
    exit 1
fi

if [ "$USE_JSON" = "1" ] && [ "$FORCE_MULTIPART" = "1" ]; then
    echo "[ERROR] --json 与 --multipart 不能同时使用。"
    exit 1
fi

# --- input sniffing -------------------------------------------------------
lower() {
    printf '%s' "$1" | tr 'A-Z' 'a-z'
}

input_is_json() {
    # Extension wins; otherwise peek at the first non-space byte (BOM tolerated).
    local ext first
    ext="$(lower "${INPUT_FILE##*.}")"
    if [ "$ext" = "json" ]; then
        return 0
    fi
    first="$(LC_ALL=C head -c 4096 "$INPUT_FILE" \
        | LC_ALL=C tr -d '\357\273\277 \t\r\n' \
        | LC_ALL=C cut -c1)"
    [ "$first" = "{" ]
}

input_looks_like_dc_report() {
    # Bash-only sniff used when python3 is unavailable.
    LC_ALL=C grep -q '"top_module"' "$INPUT_FILE" \
        && ! LC_ALL=C grep -q '"records"' "$INPUT_FILE"
}

INPUT_IS_JSON=0
if input_is_json; then
    INPUT_IS_JSON=1
fi

if [ "$INPUT_IS_JSON" = "1" ] && [ "$FORCE_MULTIPART" != "1" ] && [ "$USE_JSON" != "1" ]; then
    USE_JSON=1
    echo "[INFO] 检测到 JSON 输入 -> 自动使用 JSON 接口 /api/v1/qor/upload（等同 --json）"
    echo "       如确需旧的 multipart CSV 接口，请显式加 --multipart。"
fi

if [ "$INPUT_IS_JSON" = "1" ] && [ "$FORCE_MULTIPART" = "1" ]; then
    echo "[WARN] 输入是 JSON，但你指定了 --multipart；"
    echo "       /api/v1/upload 按 CSV 解析 JSON，通常会返回 422 且 saved=0。"
fi

# --- python3 invocation ---------------------------------------------------
# Never put non-ASCII text in python3 argv (including `python3 -c '...'`):
# python decodes argv with the locale encoding, so a C/POSIX locale turns UTF-8
# bytes into lone surrogates and CPython aborts with
#   "Unable to decode the command line: UnicodeEncodeError ... surrogates not allowed".
# All helper programs live in temp .py files; values travel via env vars.
run_py() {
    env PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python3 "$@"
}

# --- resolve csv_to_json client kit (only needed for --json + CSV) ---
resolve_csv_to_json() {
    local candidate root
    if [ -n "${CSV_TO_JSON:-}" ]; then
        if [ -f "$CSV_TO_JSON" ]; then
            printf '%s\n' "$CSV_TO_JSON"
            return 0
        fi
        echo "[ERROR] CSV_TO_JSON 指向的文件不存在: $CSV_TO_JSON" >&2
        return 1
    fi

    for root in \
        "${QOR_CLIENT_ROOT:-}" \
        "${SCRIPT_DIR}/lib" \
        "${SCRIPT_DIR}/.." \
        "${SCRIPT_DIR}"
    do
        [ -n "$root" ] || continue
        candidate="${root}/scripts/csv_to_json.py"
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
        candidate="${root}/csv_to_json.py"
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

resolve_dc_report_to_json() {
    local candidate root
    if [ -n "${DC_REPORT_TO_JSON:-}" ]; then
        if [ -f "$DC_REPORT_TO_JSON" ]; then
            printf '%s\n' "$DC_REPORT_TO_JSON"
            return 0
        fi
        echo "[ERROR] DC_REPORT_TO_JSON 指向的文件不存在: $DC_REPORT_TO_JSON" >&2
        return 1
    fi

    for root in \
        "${QOR_CLIENT_ROOT:-}" \
        "${SCRIPT_DIR}/lib" \
        "${SCRIPT_DIR}/.." \
        "${SCRIPT_DIR}"
    do
        [ -n "$root" ] || continue
        candidate="${root}/scripts/dc_report_to_json.py"
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
        candidate="${root}/dc_report_to_json.py"
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

print_kit_hint() {
    cat <<'EOF' >&2
[ERROR] --json 且输入为 CSV 时，工作机需要 csv_to_json 转换包（无需完整 Django）。
  一次拷贝到工作机，例如 ~/qor_client/：
    scripts/csv_to_json.py
    django_app/services/csv_field_mapping.py
    django_app/services/csv_timing.py
    django_app/services/csv_upload_paths.py
  然后任选其一：
    export QOR_CLIENT_ROOT=~/qor_client
    export CSV_TO_JSON=~/qor_client/scripts/csv_to_json.py
  或把上述树放到本脚本同级的 lib/ 目录下。
  若只想上传 CSV、不做 JSON 转换，去掉 --json 即可（multipart 默认模式）。
EOF
}

print_dc_kit_hint() {
    cat <<'EOF' >&2
[ERROR] 检测到原生 DC 报告 JSON，但找不到 dc_report_to_json.py。
  请把 scripts/dc_report_to_json.py 加入工作机 client kit，然后任选其一：
    export QOR_CLIENT_ROOT=~/qor_client
    export DC_REPORT_TO_JSON=~/qor_client/scripts/dc_report_to_json.py
  也可先手工转换后再上传：
    python3 dc_report_to_json.py --project-id PROJECT --version VERSION dc_report.json -o upload.json
    ./upload_qor_client.sh PROJECT VERSION upload.json --json
EOF
}

urlencode() {
    # Prefer python3; fall back to a minimal encoder for typical paths.
    if command -v python3 >/dev/null 2>&1; then
        run_py -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
        return
    fi
    local s="$1" out="" i c
    for (( i = 0; i < ${#s}; i++ )); do
        c="${s:i:1}"
        case "$c" in
            [a-zA-Z0-9.~_-]) out+="$c" ;;
            *) printf -v out '%s%%%02X' "$out" "'$c" ;;
        esac
    done
    printf '%s\n' "$out"
}

prepare_json_tool() {
    # ASCII-only helper program; every value is read from the environment so a
    # C/POSIX locale can never break argv decoding.
    if [ -z "${TMP_TOOL_PY:-}" ]; then
        TMP_TOOL_PY="$(mktemp "${TMPDIR:-/tmp}/qor_json_tool.XXXXXX.py")"
        cat > "$TMP_TOOL_PY" <<'PY'
import json
import os
import sys


def env_bytes(name):
    environb = getattr(os, "environb", None)
    if environb is not None:
        return environb.get(name.encode("ascii"))
    value = os.environ.get(name)
    return os.fsencode(value) if value is not None else None


def env_text(name):
    raw = env_bytes(name)
    if raw is None:
        return ""
    return raw.decode("utf-8", "surrogateescape")


def die(message):
    raise SystemExit("[ERROR] " + message)


def load_input():
    path = env_bytes("QOR_TOOL_IN")
    if not path:
        die("QOR_TOOL_IN is not set")
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        die("cannot read JSON file: %s" % exc)
    if not raw.strip():
        die("JSON file is empty")
    try:
        return json.loads(raw.decode("utf-8-sig", "surrogateescape"))
    except json.JSONDecodeError as exc:
        die("invalid JSON at line %d column %d: %s" % (exc.lineno, exc.colno, exc.msg))


def detect(data):
    if not isinstance(data, dict):
        die("invalid JSON: root must be an object")
    schema = data.get("schema_version", data.get("scheme_version"))
    is_upload = (
        isinstance(data.get("records"), list)
        or (isinstance(schema, str) and isinstance(data.get("upload"), dict))
    )
    is_dc = (
        ("top_module" in data and ("timing" in data or "area" in data))
        or isinstance(schema, int)
    )
    sys.stdout.write("upload" if is_upload else "dc" if is_dc else "upload")
    sys.stdout.write("\n")


def normalize_upload_full_dir(up):
    values = {}
    for key in ("full_dir", "directory"):
        value = up.get(key)
        if value is None:
            values[key] = ""
        elif not isinstance(value, str):
            die("upload.%s must be a string" % key)
        else:
            values[key] = value.strip()

    full_dir = values["full_dir"]
    directory = values["directory"]
    if full_dir and directory and full_dir != directory:
        die("upload.full_dir conflicts with upload.directory")

    canonical = full_dir or directory
    if canonical:
        up["full_dir"] = canonical
    up.pop("directory", None)


def inject(data):
    if not isinstance(data, dict):
        die("invalid JSON: root must be an object")
    up = data.setdefault("upload", {})
    if not isinstance(up, dict):
        die("invalid JSON: upload must be an object")
    normalize_upload_full_dir(up)

    project_id = env_text("QOR_TOOL_PROJECT_ID")
    try:
        up["project_id"] = int(project_id)
    except ValueError:
        die("invalid project_id: %s" % project_id)

    version = env_text("QOR_TOOL_VERSION")
    if version:
        up["version"] = version

    module_id = env_text("QOR_TOOL_MODULE_ID")
    if module_id:
        try:
            up["module_id"] = int(module_id)
        except ValueError:
            die("invalid module_id: %s" % module_id)

    full_dir = env_text("QOR_TOOL_FULL_DIR")
    if full_dir:
        up["full_dir"] = full_dir

    release_dir = env_text("QOR_TOOL_RELEASE_DIR")
    if release_dir:
        up["release_dir"] = release_dir

    if env_text("QOR_TOOL_MARK_RELEASED") == "1":
        up["mark_released"] = True

    if not up.get("full_dir"):
        die("upload.full_dir is missing; pass --full-dir DIR")

    out_path = env_bytes("QOR_TOOL_OUT")
    if not out_path:
        die("QOR_TOOL_OUT is not set")
    with open(out_path, "w", encoding="utf-8", errors="surrogateescape") as handle:
        json.dump(data, handle, ensure_ascii=False)
        handle.write("\n")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ("detect", "inject"):
        die("unknown action: %s" % action)
    data = load_input()
    if action == "detect":
        detect(data)
    else:
        inject(data)


main()
PY
    fi
}

run_json_tool() {
    # run_json_tool <detect|inject> <input_file> [output_file]
    local action="$1" in_file="$2" out_file="${3:-}"
    prepare_json_tool
    env \
        PYTHONUTF8=1 \
        PYTHONIOENCODING=utf-8 \
        QOR_TOOL_IN="$in_file" \
        QOR_TOOL_OUT="$out_file" \
        QOR_TOOL_PROJECT_ID="$PROJECT_ID" \
        QOR_TOOL_VERSION="$VERSION" \
        QOR_TOOL_MODULE_ID="$MODULE_ID" \
        QOR_TOOL_FULL_DIR="$FULL_DIR" \
        QOR_TOOL_RELEASE_DIR="$RELEASE_DIR" \
        QOR_TOOL_MARK_RELEASED="$MARK_RELEASED" \
        python3 "$TMP_TOOL_PY" "$action"
}

http_fail_hints() {
    local code="$1" body="$2"
    case "$code" in
        400)
            echo "[FAIL] 上传失败（HTTP 400）。"
            if printf '%s' "$body" | grep -q '缺少上传文件'; then
                echo "        服务端仍只认旧字段 file，未接受 files。"
                echo "        请 IT 在 Linux 服务器同步含 files 兼容的 django_app/api/views.py 并重启 qor_recorder。"
            fi
            if printf '%s' "$body" | grep -qi 'full_dir'; then
                echo "        JSON 接口要求 upload.full_dir。请加 --full-dir /path/to/run。"
            fi
            ;;
        401)
            echo "[FAIL] 认证失败（HTTP 401）。请检查 QOR_API_KEY 是否正确、是否已撤销。"
            ;;
        403)
            echo "[FAIL] 无权限（HTTP 403）。Key 的 scope 需含 upload；账户 must_change_password 须为 False。"
            ;;
        422)
            echo "[FAIL] 服务端未保存任何记录（HTTP 422）。"
            if [ "${INPUT_IS_JSON:-0}" = "1" ] && [ "${FORCE_MULTIPART:-0}" = "1" ]; then
                echo "        JSON 文件被 multipart 接口当成 CSV 解析了（skipped=总行数）。"
                echo "        去掉 --multipart，让脚本走 JSON 接口 /api/v1/qor/upload。"
            else
                echo "        请检查文件内容是否与所选接口匹配、字段是否可被识别。"
            fi
            ;;
        *)
            echo "[FAIL] 上传失败（HTTP ${code}）"
            ;;
    esac
}

do_curl_post() {
    local url="$1"; shift
    local response curl_rc http_code body
    set +e
    response="$(curl -sS -X POST "$url" "$@" -w "\n%{http_code}" 2>&1)"
    curl_rc=$?
    set -e

    if [ "$curl_rc" -ne 0 ]; then
        echo "[ERROR] 无法连接服务器（curl 退出码 ${curl_rc}）。"
        echo "        请检查 QOR_SERVER=${SERVER}、网络、防火墙、以及服务是否在跑。"
        if [ -n "$response" ]; then
            echo "[ERROR] curl 输出:"
            echo "$response"
        fi
        exit 2
    fi

    http_code="$(printf '%s\n' "$response" | tail -n1)"
    body="$(printf '%s\n' "$response" | sed '$d')"

    echo "[INFO] HTTP 状态: ${http_code}"
    echo "[INFO] 响应正文:"
    echo "${body}"

    if [ "$http_code" = "200" ]; then
        echo "[OK] 上传成功"
        exit 0
    fi
    http_fail_hints "$http_code" "$body"
    exit 2
}

# =========================================================================
# JSON mode
# =========================================================================
if [ "$USE_JSON" = "1" ]; then
    TMP_JSON=""
    TMP_CONVERTED_JSON=""
    TMP_TOOL_PY=""
    UPLOAD_BODY_FILE=""

    cleanup_tmp() {
        local file
        for file in "${TMP_JSON:-}" "${TMP_CONVERTED_JSON:-}" "${TMP_TOOL_PY:-}"; do
            if [ -n "$file" ] && [ -f "$file" ]; then
                rm -f "$file"
            fi
        done
    }
    trap cleanup_tmp EXIT

    if [ "$INPUT_IS_JSON" = "1" ]; then
        if ! command -v python3 >/dev/null 2>&1; then
            if [ -n "$FULL_DIR" ] || [ -n "$MODULE_ID" ] || [ -n "$RELEASE_DIR" ] || [ "$MARK_RELEASED" = "1" ]; then
                echo "[ERROR] 需要注入 --full-dir/--module-id/--release 等字段时必须有 python3。"
                echo "        或者把这些字段写进 JSON 的 upload 对象后再上传。"
                exit 1
            fi
            if input_looks_like_dc_report; then
                echo "[ERROR] 输入疑似原生 DC 报告，转换成 §6.5 需要 python3。"
                echo "        请在工作机安装 python3，或先在别处用 dc_report_to_json.py 转换后再上传。"
                exit 1
            fi
            # No overrides: send file as-is (must already contain upload.full_dir).
            UPLOAD_BODY_FILE="$INPUT_FILE"
        else
            if ! JSON_KIND="$(run_json_tool detect "$INPUT_FILE")"; then
                echo "[ERROR] 无法读取输入 JSON；请修正上述问题后重试。"
                exit 1
            fi

            JSON_SOURCE="$INPUT_FILE"
            if [ "$JSON_KIND" = "dc" ]; then
                DC_REPORT_TO_JSON_PATH="$(resolve_dc_report_to_json)" || {
                    print_dc_kit_hint
                    exit 1
                }
                TMP_CONVERTED_JSON="$(mktemp "${TMPDIR:-/tmp}/qor_dc_converted.XXXXXX.json")"
                DC_ARGS=(--project-id "$PROJECT_ID" --version "$VERSION")
                if [ -n "$FULL_DIR" ]; then
                    DC_ARGS+=(--full-dir "$FULL_DIR")
                fi
                if [ -n "$RELEASE_DIR" ]; then
                    DC_ARGS+=(--release-dir "$RELEASE_DIR")
                fi
                if [ "$MARK_RELEASED" = "1" ]; then
                    DC_ARGS+=(--mark-released)
                fi
                echo "[INFO] 检测到原生 DC 报告 -> JSON §6.5（$DC_REPORT_TO_JSON_PATH）"
                if ! run_py "$DC_REPORT_TO_JSON_PATH" \
                    "${DC_ARGS[@]}" "$INPUT_FILE" -o "$TMP_CONVERTED_JSON"; then
                    echo "[ERROR] DC 报告 -> JSON §6.5 转换失败"
                    exit 3
                fi
                JSON_SOURCE="$TMP_CONVERTED_JSON"
            else
                echo "[INFO] 检测到 JSON §6.5 -> 注入上传字段"
            fi

            TMP_JSON="$(mktemp "${TMPDIR:-/tmp}/qor_upload.XXXXXX.json")"
            if ! run_json_tool inject "$JSON_SOURCE" "$TMP_JSON"; then
                echo "[ERROR] 无法准备 JSON；请修正上述具体问题后重试。"
                exit 1
            fi
            UPLOAD_BODY_FILE="$TMP_JSON"
        fi
    else
        # CSV -> JSON via client kit
        if [ -z "$FULL_DIR" ]; then
            echo "[ERROR] JSON 模式上传 CSV 时必须提供 --full-dir（JSON API 要求 upload.full_dir）。"
            echo "        示例: --full-dir \"\$PWD\"  或  --full-dir /scratch/runs/v1.0"
            exit 1
        fi
        if ! command -v python3 >/dev/null 2>&1; then
            echo "[ERROR] CSV -> JSON 需要 python3。"
            exit 1
        fi
        CSV_TO_JSON_PATH="$(resolve_csv_to_json)" || {
            print_kit_hint
            exit 1
        }
        # Kit root must contain django_app/services/*.py (csv_to_json imports those).
        KIT_ROOT=""
        for root in \
            "${QOR_CLIENT_ROOT:-}" \
            "${SCRIPT_DIR}/lib" \
            "$(cd "$(dirname "$CSV_TO_JSON_PATH")/.." && pwd)" \
            "$(cd "$(dirname "$CSV_TO_JSON_PATH")" && pwd)" \
            "${SCRIPT_DIR}/.."
        do
            [ -n "$root" ] || continue
            if [ -f "${root}/django_app/services/csv_upload_paths.py" ]; then
                KIT_ROOT="$(cd "$root" && pwd)"
                break
            fi
        done
        if [ -z "$KIT_ROOT" ]; then
            echo "[ERROR] 找不到 django_app/services/csv_upload_paths.py（转换包不完整）"
            print_kit_hint
            exit 1
        fi

        echo "[INFO] CSV -> JSON（$CSV_TO_JSON_PATH）"
        echo "       kit_root=${KIT_ROOT} full_dir=${FULL_DIR}"
        # Absolute path so conversion still works after cd into kit root.
        if command -v realpath >/dev/null 2>&1; then
            ABS_INPUT="$(realpath "$INPUT_FILE")"
        else
            ABS_INPUT="$(cd "$(dirname "$INPUT_FILE")" && pwd)/$(basename "$INPUT_FILE")"
        fi
        CSV_ARGS=(--project-id "$PROJECT_ID" --version "$VERSION" --full-dir "$FULL_DIR" --data-type qor)
        if [ -n "$RELEASE_DIR" ]; then
            CSV_ARGS+=(--release-dir "$RELEASE_DIR")
        fi
        # Write to a file instead of stdout: the converter emits non-ASCII with
        # ensure_ascii=False, which a C/POSIX-locale stdout cannot encode.
        TMP_CONVERTED_JSON="$(mktemp "${TMPDIR:-/tmp}/qor_csv_converted.XXXXXX.json")"
        if ! (
            cd "$KIT_ROOT" && PYTHONPATH="${KIT_ROOT}${PYTHONPATH:+:$PYTHONPATH}" \
                run_py "$CSV_TO_JSON_PATH" "${CSV_ARGS[@]}" "$ABS_INPUT" -o "$TMP_CONVERTED_JSON"
        ); then
            echo "[ERROR] CSV -> JSON 转换失败"
            exit 3
        fi
        # Inject mark_released / module_id after conversion.
        TMP_JSON="$(mktemp "${TMPDIR:-/tmp}/qor_upload.XXXXXX.json")"
        if ! run_json_tool inject "$TMP_CONVERTED_JSON" "$TMP_JSON"; then
            echo "[ERROR] 注入 upload 字段失败；请查看上述具体原因。"
            exit 3
        fi
        UPLOAD_BODY_FILE="$TMP_JSON"
    fi

    ENC_VERSION="$(urlencode "$VERSION")"
    UPLOAD_URL="${SERVER}/api/v1/qor/upload?project_id=${PROJECT_ID}&version=${ENC_VERSION}"
    echo "[INFO] 上传 ${INPUT_FILE}"
    echo "       POST ${UPLOAD_URL}"
    echo "       project_id=${PROJECT_ID} version=${VERSION} release=${MARK_RELEASED} mode=json"
    if [ -n "$MODULE_ID" ]; then
        echo "       module_id=${MODULE_ID}"
    fi
    if [ -n "$FULL_DIR" ]; then
        echo "       full_dir=${FULL_DIR}"
    fi
    if [ -n "$RELEASE_DIR" ]; then
        echo "       release_dir=${RELEASE_DIR}"
    fi

    do_curl_post "$UPLOAD_URL" \
        -H "X-API-Key: ${API_KEY}" \
        -H "Content-Type: application/json" \
        --data-binary @"${UPLOAD_BODY_FILE}"
fi

# =========================================================================
# multipart CSV (default)
# =========================================================================
UPLOAD_URL="${SERVER}/api/v1/upload"

FORM_ARGS=(
    -H "X-API-Key: ${API_KEY}"
    -F "project_id=${PROJECT_ID}"
    -F "version=${VERSION}"
    -F "data_type=qor"
    -F "files=@${INPUT_FILE}"
    -F "file=@${INPUT_FILE}"
)

if [ -n "$MODULE_ID" ]; then
    FORM_ARGS+=(-F "module_id=${MODULE_ID}")
fi
if [ "$MARK_RELEASED" = "1" ]; then
    FORM_ARGS+=(-F "mark_released=1")
fi
if [ -n "$RELEASE_DIR" ]; then
    FORM_ARGS+=(-F "release_dir=${RELEASE_DIR}")
fi
if [ -n "$FULL_DIR" ]; then
    FORM_ARGS+=(-F "full_dir=${FULL_DIR}")
fi

echo "[INFO] 上传 ${INPUT_FILE}"
echo "       POST ${UPLOAD_URL}"
echo "       project_id=${PROJECT_ID} version=${VERSION} release=${MARK_RELEASED} mode=multipart"
if [ -n "$MODULE_ID" ]; then
    echo "       module_id=${MODULE_ID}"
fi
if [ -n "$RELEASE_DIR" ]; then
    echo "       release_dir=${RELEASE_DIR}"
fi

do_curl_post "$UPLOAD_URL" "${FORM_ARGS[@]}"
