#!/bin/sh
set -eu

BASE=$(CDPATH= cd "$(dirname "$0")" && pwd)

stop_pid_tree() {
  local pid children child count
  pid=$1
  case "$pid" in
    ""|*[!0-9]*|0|1) return 0 ;;
  esac
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  children=$(pgrep -P "$pid" 2>/dev/null || true)
  for child in $children; do
    stop_pid_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
  count=0
  while kill -0 "$pid" 2>/dev/null && [ "$count" -lt 5 ]; do
    sleep 1
    count=$((count + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
  return 0
}

stop_from_pid_file() {
  local name pid_file pid
  name=$1
  pid_file=$2
  [ -f "$pid_file" ] || return 0
  pid=$(cat "$pid_file" 2>/dev/null || true)
  echo "停止 $name（PID 文件：${pid:-无效}）..."
  stop_pid_tree "$pid"
  rm -f "$pid_file"
  return 0
}

stop_matching_processes() {
  local name pattern pids pid
  name=$1
  pattern=$2
  pids=$(pgrep -f "$pattern" 2>/dev/null || true)
  [ -n "$pids" ] || return 0
  echo "停止检测到的 $name 进程：$pids"
  for pid in $pids; do
    stop_pid_tree "$pid"
  done
  return 0
}

# 先按上次启动记录停止，再发现并清理手动启动的同类服务。
stop_from_pid_file "前端" "$BASE/.frontend.pid"
stop_from_pid_file "后端" "$BASE/.backend.pid"
stop_matching_processes "前端" "^npm run dev --host 0.0.0.0$"
stop_matching_processes "后端" "uvicorn app.main:app --host 0.0.0.0 --port 8421"

rm -f "$BASE/.frontend.pid" "$BASE/.backend.pid"
sleep 1
exec "$BASE/start.sh"