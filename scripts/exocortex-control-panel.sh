#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(
  CDPATH= cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd
)
REPO_ROOT=$(
  CDPATH= cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd
)
PORTS_FILE="${REPO_ROOT}/.env.ports"
CONTROL_PANEL_DIR="${REPO_ROOT}/exocortex/control-panel"
RUNTIME_DIR="${TMPDIR:-/tmp}/self-hosted-memory-assistants"
PID_FILE="${RUNTIME_DIR}/exocortex-control-panel.pid"
LOG_FILE="${RUNTIME_DIR}/exocortex-control-panel.log"

if [ -f "${PORTS_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${PORTS_FILE}"
  set +a
fi

EXOCORTEX_CONTROL_PANEL_PORT="${EXOCORTEX_CONTROL_PANEL_PORT:-3333}"

usage() {
  cat <<'EOF'
Usage: ./scripts/exocortex-control-panel.sh {start|stop|status}
EOF
}

log() {
  printf '[exocortex-control-panel] %s\n' "$*"
}

warn() {
  printf '[exocortex-control-panel] warning: %s\n' "$*" >&2
}

ensure_checkout() {
  if [ ! -d "${CONTROL_PANEL_DIR}" ]; then
    warn "Missing ${CONTROL_PANEL_DIR}; initialize the exocortex submodule first"
    exit 1
  fi
}

ensure_prereqs() {
  if ! command -v node >/dev/null 2>&1; then
    warn "node is required to run the exocortex control panel"
    exit 1
  fi

  if [ ! -d "${CONTROL_PANEL_DIR}/node_modules" ]; then
    warn "Missing dependencies in ${CONTROL_PANEL_DIR}"
    warn "Run: npm ci --prefix ${REPO_ROOT}/exocortex/control-panel"
    exit 1
  fi
}

read_pid() {
  [ -f "${PID_FILE}" ] || return 1
  tr -d '[:space:]' <"${PID_FILE}"
}

is_running() {
  local pid

  pid="$1"
  [ -n "${pid}" ] || return 1
  kill -0 "${pid}" 2>/dev/null
}

start_service() {
  local pid

  ensure_checkout
  ensure_prereqs
  mkdir -p "${RUNTIME_DIR}"

  if pid=$(read_pid) && is_running "${pid}"; then
    log "Already running on http://localhost:${EXOCORTEX_CONTROL_PANEL_PORT} (pid ${pid})"
    return 0
  fi

  rm -f "${PID_FILE}"
  : >"${LOG_FILE}"

  (
    cd "${CONTROL_PANEL_DIR}"
    nohup env PORT="${EXOCORTEX_CONTROL_PANEL_PORT}" node server.js >>"${LOG_FILE}" 2>&1 &
    echo "$!" >"${PID_FILE}"
  )

  sleep 1
  pid=$(read_pid)
  if ! is_running "${pid}"; then
    warn "Failed to start exocortex control panel. See ${LOG_FILE}"
    exit 1
  fi

  log "Started on http://localhost:${EXOCORTEX_CONTROL_PANEL_PORT} (pid ${pid})"
  log "Log: ${LOG_FILE}"
}

stop_service() {
  local pid

  if ! pid=$(read_pid); then
    log "Not running"
    return 0
  fi

  if ! is_running "${pid}"; then
    rm -f "${PID_FILE}"
    log "Not running (removed stale pid file)"
    return 0
  fi

  kill "${pid}"

  for _ in 1 2 3 4 5; do
    if ! is_running "${pid}"; then
      rm -f "${PID_FILE}"
      log "Stopped"
      return 0
    fi
    sleep 1
  done

  warn "Process ${pid} is still running; check it manually"
  exit 1
}

status_service() {
  local pid

  if pid=$(read_pid) && is_running "${pid}"; then
    log "Running on http://localhost:${EXOCORTEX_CONTROL_PANEL_PORT} (pid ${pid})"
    log "Log: ${LOG_FILE}"
    return 0
  fi

  [ -f "${PID_FILE}" ] && rm -f "${PID_FILE}"
  log "Not running"
}

case "${1:-status}" in
  start)
    start_service
    ;;
  stop)
    stop_service
    ;;
  status)
    status_service
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
