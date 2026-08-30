#!/bin/bash
# TDT评审专家打分系统 — macOS 启动脚本（对应 Windows 的 start.cmd）
# 行为与 start.cmd 保持一致：完整性检查 -> 环境就绪 -> launcher 决定复用或新起
# -> 校验 /api/health 的 project_id 与 build_id -> 打开浏览器
# 注意：本文件必须为 LF 行尾（见仓库根 .gitattributes）。

set -uo pipefail
cd "$(dirname "$0")" || exit 1

PROJECT_ID="tdt-expert-review-quality"

fail() {
  echo
  echo "[ERROR] $1"
  echo
  read -r -p "按回车关闭窗口…" _
  exit 1
}

# --- 1. 项目完整性 ---
[ -f "pyproject.toml" ] || fail "当前目录不是完整的项目（缺 pyproject.toml）。"
[ -f "src/tdt_scoring/api.py" ] || fail "当前目录不是完整的项目（缺 src/tdt_scoring/api.py）。"

# --- 2. 准备虚拟环境 ---
if [ ! -x ".venv/bin/python" ]; then
  echo "[SETUP] 未找到虚拟环境，正在创建…"
  UV=""
  for candidate in "$(command -v uv || true)" "$HOME/.local/bin/uv" "$HOME/Library/Python/3.9/bin/uv"; do
    [ -n "$candidate" ] && [ -x "$candidate" ] && UV="$candidate" && break
  done

  if [ -n "$UV" ]; then
    "$UV" venv --python 3.12 .venv || fail "创建虚拟环境失败。"
  else
    PY=""
    for candidate in python3.13 python3.12; do
      command -v "$candidate" >/dev/null 2>&1 && PY="$candidate" && break
    done
    [ -n "$PY" ] || fail "未找到 Python 3.12+，也未找到 uv。
安装方式任选其一：
  python3 -m pip install --user uv && ~/Library/Python/3.9/bin/uv python install 3.12
  或从 https://www.python.org/downloads/macos/ 安装 Python 3.12+
（macOS 自带的 python3 是 3.9，依赖链要求 3.10+，无法运行本系统。）"
    "$PY" -m venv .venv || fail "创建虚拟环境失败。"
  fi
fi

# --- 3. 依赖 ---
if ! .venv/bin/python -c "import fastapi, openpyxl, uvicorn" >/dev/null 2>&1; then
  echo "[SETUP] 正在安装项目依赖…"
  .venv/bin/python -m pip install -q --upgrade pip || fail "升级 pip 失败。"
  .venv/bin/python -m pip install -e . || fail "安装依赖失败。"
fi

# --- 4. 由 launcher 决定复用还是新起 ---
LAUNCH_OUTPUT="$(.venv/bin/python -m tdt_scoring.launcher)" || fail "启动器执行失败。"
read -r ACTION PORT BUILD_ID <<<"$LAUNCH_OUTPUT"
[ -n "${ACTION:-}" ] && [ -n "${PORT:-}" ] && [ -n "${BUILD_ID:-}" ] || fail "启动器返回异常：$LAUNCH_OUTPUT"

APP_URL="http://127.0.0.1:${PORT}/?build=${BUILD_ID}"

if [ "$ACTION" = "reuse" ]; then
  echo "[RUNNING] 最新构建已在端口 ${PORT} 运行，直接打开。"
  open "$APP_URL"
  exit 0
fi

[ "$ACTION" = "launch" ] || fail "启动器返回未知动作：$ACTION"

# --- 5. 启动服务 ---
mkdir -p output
SERVICE_LOG="output/local-service-${PORT}-${BUILD_ID}-$$.log"
printf '==== Starting build %s on port %s ====\n' "$BUILD_ID" "$PORT" >"$SERVICE_LOG" || fail "无法写入日志文件。"

echo "[RUNNING] 正在启动：http://127.0.0.1:${PORT}/"
echo "[RUNNING] 服务日志：$(pwd)/${SERVICE_LOG}"

# 后台等待服务就绪，校验身份后再开浏览器（与 start.cmd 的 powershell 轮询等价）
(
  for _ in $(seq 1 40); do
    HEALTH="$(curl -s --max-time 1 "http://127.0.0.1:${PORT}/api/health" 2>/dev/null)"
    if [ -n "$HEALTH" ] && printf '%s' "$HEALTH" | .venv/bin/python -c "
import json, sys
try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(1)
sys.exit(0 if data.get('project_id') == '${PROJECT_ID}' and data.get('build_id') == '${BUILD_ID}' else 1)
" >/dev/null 2>&1; then
      open "$APP_URL"
      exit 0
    fi
    sleep 0.25
  done
  echo "[WARN] 服务未在预期时间内通过健康校验，未自动打开浏览器。" >&2
) &

echo "[RUNNING] 使用期间请保持本窗口开启。"
.venv/bin/python -u -m uvicorn tdt_scoring.api:app --host 127.0.0.1 --port "$PORT" >>"$SERVICE_LOG" 2>&1
EXIT_CODE=$?

echo
if [ "$EXIT_CODE" -eq 0 ]; then
  echo "[STOPPED] 本地打分服务已停止。"
else
  echo "[ERROR] 本地打分服务异常退出，退出码 ${EXIT_CODE}。"
fi
echo "日志：$(pwd)/${SERVICE_LOG}"
echo "重新运行 start.command 后请使用新打开的页面，并重新导入评审表再打分。"
read -r -p "按回车关闭窗口…" _
exit "$EXIT_CODE"
