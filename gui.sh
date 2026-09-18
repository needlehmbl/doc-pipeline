#!/usr/bin/env bash
# doc-pipeline GUI launcher — one command to run or stop the whole stack.
#
#   ./gui.sh           # start backend (:8001) + frontend (:5174)
#   ./gui.sh stop      # stop both
#   ./gui.sh restart   # stop, then start
#   ./gui.sh status    # show whether each server is up
#   ./gui.sh logs      # tail both logs
#
# First run auto-installs missing deps (pip packages + npm packages).

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8001
FRONTEND_PORT=5174
RUN_DIR="$ROOT/.gui"
BACKEND_PID="$RUN_DIR/backend.pid"
FRONTEND_PID="$RUN_DIR/frontend.pid"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"

if [ -x "$ROOT/venv/bin/python" ]; then
  PY="$ROOT/venv/bin/python"
else
  PY="python3"
fi

mkdir -p "$RUN_DIR"

is_up() { curl -sf -o /dev/null "http://localhost:$1/api/health" 2>/dev/null || curl -sf -o /dev/null "http://localhost:$1/" 2>/dev/null; }

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

start_server() { # name, pidfile, logfile, cmd...
  local name="$1" pidfile="$2" logfile="$3"; shift 3
  if [ -f "$pidfile" ] && pid_alive "$(cat "$pidfile")"; then
    echo "- $name already running (pid $(cat "$pidfile"))"
    return 0
  fi
  echo "+ starting $name..."
  # shellcheck disable=SC2086
  nohup "$@" >"$logfile" 2>&1 &
  echo $! >"$pidfile"
}

ensure_backend_deps() {
  if "$PY" -c "import fastapi, uvicorn" 2>/dev/null; then return 0; fi
  echo "+ installing backend deps (fastapi, uvicorn, python-multipart) with $PY..."
  "$PY" -m pip install --quiet fastapi "uvicorn>=0.29" python-multipart \
    || { echo "ERROR: pip install failed. Try manually:"; echo "  $PY -m pip install fastapi uvicorn python-multipart"; exit 1; }
}

ensure_frontend_deps() {
  if [ -d "$ROOT/gui/node_modules" ]; then return 0; fi
  echo "+ installing frontend deps (npm install)..."
  (cd "$ROOT/gui" && npm install) || { echo "ERROR: npm install failed"; exit 1; }
}

cmd_start() {
  ensure_backend_deps
  ensure_frontend_deps
  start_server "backend (:$BACKEND_PORT)" "$BACKEND_PID" "$BACKEND_LOG" \
    "$PY" -m uvicorn api.server:app --port "$BACKEND_PORT"
  start_server "frontend (:$FRONTEND_PORT)" "$FRONTEND_PID" "$FRONTEND_LOG" \
    npm run dev --prefix "$ROOT/gui" -- --port "$FRONTEND_PORT" --strictPort

  echo "+ waiting for servers..."
  for i in $(seq 1 30); do
    sleep 1
    if is_up "$BACKEND_PORT" && is_up "$FRONTEND_PORT"; then break; fi
  done

  echo ""
  is_up "$BACKEND_PORT" \
    && echo "  backend:  http://localhost:$BACKEND_PORT  (docs: http://localhost:$BACKEND_PORT/docs)" \
    || echo "  backend:  FAILED to come up — see $BACKEND_LOG"
  is_up "$FRONTEND_PORT" \
    && echo "  frontend: http://localhost:$FRONTEND_PORT" \
    || echo "  frontend: FAILED to come up — see $FRONTEND_LOG"
}

stop_one() { # name, pidfile, pattern
  local name="$1" pidfile="$2" pattern="$3" pid=""
  [ -f "$pidfile" ] && pid="$(cat "$pidfile")"
  if pid_alive "$pid"; then
    kill "$pid" 2>/dev/null
    for _ in $(seq 1 10); do pid_alive "$pid" || break; sleep 0.5; done
    pid_alive "$pid" && kill -9 "$pid" 2>/dev/null
    echo "- $name stopped (pid $pid)"
  else
    # Fall back to pattern match in case PIDs went stale.
    if pkill -f "$pattern" 2>/dev/null; then
      echo "- $name stopped (by pattern)"
    else
      echo "- $name not running"
    fi
  fi
  rm -f "$pidfile"
}

cmd_stop() {
  stop_one "frontend" "$FRONTEND_PID" "vite.*$FRONTEND_PORT|vite.*gui"
  stop_one "backend" "$BACKEND_PID" "uvicorn api.server.*$BACKEND_PORT"
}

cmd_status() {
  is_up "$BACKEND_PORT" && echo "backend (:$BACKEND_PORT):  UP" || echo "backend (:$BACKEND_PORT):  DOWN"
  is_up "$FRONTEND_PORT" && echo "frontend (:$FRONTEND_PORT): UP" || echo "frontend (:$FRONTEND_PORT): DOWN"
}

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
}

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; echo ""; cmd_start ;;
  status)  cmd_status ;;
  logs)    tail -n 50 -f "$BACKEND_LOG" "$FRONTEND_LOG" 2>/dev/null || echo "No logs yet — run ./gui.sh first." ;;
  -h|--help|help) usage ;;
  *) echo "Unknown command: $1"; usage; exit 1 ;;
esac
