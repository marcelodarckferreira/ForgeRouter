#!/usr/bin/env bash
# Dev-mode launcher for the ForgeRouter dashboard frontend: hot-reload Vite
# dev server (frontend/vite.config.ts proxies /admin, /auth, /v1 to the
# backend on :2100).
#
# This script manages ONLY the frontend process. Unlike ForgeHub, ForgeRouter's
# backend is not a per-dev-instance service -- the container on :2100 is the
# live routing proxy every Hermes agent (Athos, Aegis, ...) depends on right
# now, so this script never starts, stops, or rebuilds it. Deploy backend
# changes explicitly with `docker compose build && docker compose up -d`
# (see CLAUDE.md); for host networking / local Ollama access use
# `docker compose -f docker-compose.local.yml up -d --build` instead.
#
# Usage:
#   ./dev.sh          start (or restart if already running)
#   ./dev.sh stop     stop the dev server
#   ./dev.sh status   show whether it's up + backend reachability
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
STATE_DIR="$ROOT_DIR/.dev"
LOG_DIR="$STATE_DIR/logs"
FRONTEND_PID_FILE="$STATE_DIR/frontend.pid"

FRONTEND_PORT=5173
BACKEND_URL="http://127.0.0.1:2100"

mkdir -p "$LOG_DIR"

color() { printf "\033[%sm%s\033[0m" "$1" "$2"; }
ok()    { echo "$(color 32 "✓") $1"; }
warn()  { echo "$(color 33 "!") $1"; }
err()   { echo "$(color 31 "✗") $1"; }
info()  { echo "$(color 36 "→") $1"; }

pid_alive() { [ -n "$1" ] && kill -0 "$1" 2>/dev/null; }
port_owner_pids() { lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null; }

# vite's `npm run dev` wrapper forks a child that ends up on a different pid
# than the one `$!` captures for the supervisor, so "stop" targets whoever is
# really listening on the port, plus the recorded supervisor pid, rather than
# trusting one pid to own it.
stop_by_port() {
  local name="$1" port="$2" pid_file="$3"
  local pids
  pids=$( { port_owner_pids "$port"; [ -f "$pid_file" ] && cat "$pid_file"; } | sort -u)
  rm -f "$pid_file"
  if [ -z "$pids" ]; then
    warn "$name not running"
    return
  fi
  for pid in $pids; do
    pid_alive "$pid" && kill -TERM "$pid" 2>/dev/null
  done
  for _ in $(seq 1 20); do
    [ -z "$(port_owner_pids "$port")" ] && break
    sleep 0.2
  done
  for pid in $(port_owner_pids "$port"); do
    kill -9 "$pid" 2>/dev/null
  done
  ok "Stopped $name"
}

cmd_stop() {
  stop_by_port "frontend" "$FRONTEND_PORT" "$FRONTEND_PID_FILE"
}

check_config() {
  local failed=0

  if [ ! -x "$FRONTEND_DIR/node_modules/.bin/vite" ]; then
    warn "frontend/node_modules missing or incomplete -- running npm install (first run only, takes a bit)."
    (cd "$FRONTEND_DIR" && npm install --silent) || { err "npm install failed"; failed=1; }
  fi

  if ! curl -sf -o /dev/null "$BACKEND_URL/health"; then
    err "Backend not reachable at $BACKEND_URL. This script never starts/stops it -- it's shared production infra for the whole Hermes ecosystem. Bring it up explicitly first: docker compose up -d (or docker-compose.local.yml for host networking / local Ollama)."
    failed=1
  fi

  if [ "$failed" -ne 0 ]; then
    err "Config checks failed -- fix the above before starting."
    exit 1
  fi
  ok "Config checks passed (frontend deps, backend reachable at $BACKEND_URL)"
}

start_frontend() {
  local existing
  existing=$(port_owner_pids "$FRONTEND_PORT")
  if [ -n "$existing" ]; then
    if [ -f "$FRONTEND_PID_FILE" ]; then
      ok "Frontend already running on :$FRONTEND_PORT"
      return
    fi
    err "Port $FRONTEND_PORT is already in use (pid(s): $existing) by something dev.sh didn't start -- stop it manually first."
    exit 1
  fi
  info "Starting frontend (vite dev) on :$FRONTEND_PORT ..."
  (
    cd "$FRONTEND_DIR" && \
    nohup npm run dev -- --port "$FRONTEND_PORT" --host 127.0.0.1 \
      > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$FRONTEND_PID_FILE"
    disown
  )
  wait_for_http "http://127.0.0.1:$FRONTEND_PORT" "frontend" "$LOG_DIR/frontend.log"
}

wait_for_http() {
  local url="$1" name="$2" log="$3"
  for _ in $(seq 1 60); do
    if curl -sf -o /dev/null "$url"; then
      ok "$name is up: $url"
      return 0
    fi
    sleep 0.5
  done
  err "$name didn't come up in time -- check $log"
  tail -n 20 "$log"
  exit 1
}

cmd_status() {
  local f_pids
  f_pids=$(port_owner_pids "$FRONTEND_PORT" | tr '\n' ' ')
  if [ -n "$f_pids" ]; then ok "Frontend up on :$FRONTEND_PORT (pid $f_pids)"; else warn "Frontend not running"; fi
  if curl -sf -o /dev/null "$BACKEND_URL/health"; then ok "Backend reachable at $BACKEND_URL"; else warn "Backend not reachable at $BACKEND_URL"; fi
}

cmd_start() {
  check_config
  start_frontend
  echo
  ok "Dev environment ready:"
  echo
  echo "    Frontend  →  http://127.0.0.1:$FRONTEND_PORT  (proxies /admin, /auth, /v1 to $BACKEND_URL)"
  echo
  info "Logs: $LOG_DIR/frontend.log"
  info "Stop with: ./dev.sh stop"
  info "Backend on :2100 is production Docker infra shared by the whole Hermes ecosystem -- this script never starts/stops/rebuilds it."
}

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  cmd_status ;;
  *) echo "Usage: $0 [start|stop|restart|status]"; exit 1 ;;
esac
