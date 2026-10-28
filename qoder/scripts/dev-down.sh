#!/usr/bin/env bash
# Stop the LabTrace development services started by scripts/dev-up.sh.
#
# Usage:
#   bash scripts/dev-down.sh            # stop backend + PowerContext Server
#   bash scripts/dev-down.sh backend    # stop only the LabTrace backend
set -euo pipefail

DATA_DIR="${LABTRACE_DATA_DIR:-$HOME/labtrace-data}"
WHICH="${1:-all}"

log() { printf '[labtrace] %s\n' "$*"; }

stop() {
  local name="$1" pidfile="$DATA_DIR/$2" pattern="$3"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 15); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
      done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
      log "stopped $name (pid $pid)"
    else
      log "$name is not running (stale pidfile)"
    fi
    rm -f "$pidfile"
  else
    log "$name has no pidfile at $pidfile"
  fi
  # A process started outside dev-up.sh has no pidfile; match it by command line. The bracket
  # keeps this pattern from matching the pkill invocation itself.
  if [[ -n "$pattern" ]]; then
    pkill -f "$pattern" 2>/dev/null || true
    # Wait until it is really gone, otherwise a following dev-up.sh can see the dying process
    # answer a health check and then skip starting a replacement.
    for _ in $(seq 1 30); do
      pgrep -f "$pattern" >/dev/null 2>&1 || break
      sleep 1
    done
    if pgrep -f "$pattern" >/dev/null 2>&1; then
      log "WARNING: $name is still running"
      pkill -9 -f "$pattern" 2>/dev/null || true
    fi
  fi
}

case "$WHICH" in
  backend) stop "LabTrace backend" backend.pid 'uvicorn app[.]main:app' ;;
  powercontext) stop "PowerContext Server" powercontext.pid 'powercontext server ru[n]' ;;
  all)
    stop "LabTrace backend" backend.pid 'uvicorn app[.]main:app'
    stop "PowerContext Server" powercontext.pid 'powercontext server ru[n]'
    ;;
  *)
    echo "usage: bash scripts/dev-down.sh [all|backend|powercontext]" >&2
    exit 2
    ;;
esac
