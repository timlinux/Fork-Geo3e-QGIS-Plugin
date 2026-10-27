#!/usr/bin/env bash
# SPDX-FileCopyrightText: Kartoza
# SPDX-License-Identifier: MIT
#
# Lifecycle commands for the GeoE3 mkdocs site: one script, modes — not
# parallel start/stop scripts. Requires the nix devShell's .venv to be
# active (mkdocs/mkdocs-material come from requirements-dev.txt).
set -euo pipefail

PID_FILE="${TMPDIR:-/tmp}/geoe3-mkdocs-serve.pid"
LOG_FILE="${TMPDIR:-/tmp}/geoe3-mkdocs-serve.log"
ADDR="${GEOE3_DOCS_ADDR:-127.0.0.1:8005}"

require_mkdocs() {
  if ! command -v mkdocs >/dev/null 2>&1; then
    echo "mkdocs not found on PATH — run this from inside 'nix develop'." >&2
    exit 1
  fi
}

is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

cmd_serve() {
  require_mkdocs
  if is_running; then
    echo "mkdocs serve already running (pid $(cat "$PID_FILE")) at http://$ADDR"
    return 0
  fi
  echo "Starting mkdocs serve at http://$ADDR (log: $LOG_FILE)"
  nohup mkdocs serve --dev-addr "$ADDR" >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  sleep 1
  if is_running; then
    echo "Running (pid $(cat "$PID_FILE")). Stop with: scripts/docs.sh stop"
  else
    echo "Failed to start — see $LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
  fi
}

cmd_stop() {
  if ! is_running; then
    echo "mkdocs serve is not running"
    rm -f "$PID_FILE"
    return 0
  fi
  pid="$(cat "$PID_FILE")"
  kill "$pid"
  rm -f "$PID_FILE"
  echo "Stopped mkdocs serve (pid $pid)"
}

cmd_status() {
  if is_running; then
    echo "mkdocs serve running (pid $(cat "$PID_FILE")) at http://$ADDR"
  else
    echo "mkdocs serve is not running"
  fi
}

cmd_build() {
  require_mkdocs
  mkdocs build --strict
}

case "${1:-}" in
  serve) cmd_serve ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  build) cmd_build ;;
  *)
    echo "Usage: $0 {serve|stop|status|build}" >&2
    exit 1
    ;;
esac
