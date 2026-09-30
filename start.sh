#!/bin/sh
set -eu

BASE=$(CDPATH= cd "$(dirname "$0")" && pwd)
LOG_DIR="$BASE/logs"

is_running() {
  pid_file=$1
  [ -f "$pid_file" ] || return 1
  pid=$(cat "$pid_file" 2>/dev/null || true)
  case "$pid" in
    ""|*[!0-9]*) return 1 ;;
  esac
  kill -0 "$pid" 2>/dev/null
}

start_frontend() {
  pid_file="$BASE/.frontend.pid"
  if is_running "$pid_file"; then
    echo "前端已在运行 (PID $(cat "$pid_file"))"
    return
  fi
  (
    cd "$BASE/frontend"
    nohup npm run dev -- --host 0.0.0.0 > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$pid_file"
  )
  echo "前端已启动，日志：$LOG_DIR/frontend.log"
}

start_backend() {
  pid_file="$BASE/.backend.pid"
  if is_running "$pid_file"; then
    echo "后端已在运行 (PID $(cat "$pid_file"))"
    return
  fi
  (
    cd "$BASE/backend"
    nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8421 > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$pid_file"
  )
  echo "后端已启动，日志：$LOG_DIR/backend.log"
}

mkdir -p "$LOG_DIR"
start_frontend
start_backend
echo "启动命令已提交；可使用 tail -f logs/frontend.log 或 tail -f logs/backend.log 查看日志。"