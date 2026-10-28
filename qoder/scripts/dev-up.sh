#!/usr/bin/env bash
# LabTrace local development bootstrap (WSL2 / Linux / macOS).
#
# Starts the PowerContext Server (embedded seekdb storage) and the LabTrace
# FastAPI backend, then waits until both report healthy.
#
# Usage:
#   bash scripts/dev-up.sh            # foreground-ish: starts both, prints status
#   PC_PORT=8010 API_PORT=8100 bash scripts/dev-up.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QODER_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="${LABTRACE_DATA_DIR:-$HOME/labtrace-data}"
PC_PORT="${PC_PORT:-8010}"
API_PORT="${API_PORT:-8100}"
VENV="${LABTRACE_VENV:-$HOME/labtrace-venv}"

export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$DATA_DIR"

log() { printf '[labtrace] %s\n' "$*"; }

# --- 1. PowerContext Server -------------------------------------------------
PC_ENV="$DATA_DIR/powercontext.env"
cat > "$PC_ENV" <<EOF
POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1
POWERCONTEXT_SERVER_HTTP_PORT=$PC_PORT
POWERCONTEXT_SERVER_DATABASE_KIND=seekdb
POWERCONTEXT_SERVER_DATABASE_PATH=$DATA_DIR/powercontext-seekdb
POWERCONTEXT_SERVER_ACCESS_MODE=disabled
POWERCONTEXT_SERVER_MCP_ENABLED=true
POWERCONTEXT_SERVER_LOGGING_LEVEL=INFO
EOF

if curl -fsS "http://127.0.0.1:$PC_PORT/health/live" >/dev/null 2>&1; then
  log "PowerContext Server already running on port $PC_PORT"
else
  if ! command -v powercontext >/dev/null 2>&1; then
    log "ERROR: powercontext CLI not found. Install with:"
    log "  uv tool install --force --with 'pymysql<1.2' 'powercontext[cli,server,seekdb]==1.2.0'"
    log "  (pymysql<1.2 is required: aiomysql 0.3.2 calls pymysql.converters.escape_bytes_prefixed,"
    log "   which pymysql 1.2 replaced with a sentinel string, breaking every bytes parameter.)"
    exit 1
  fi
  log "starting PowerContext Server on port $PC_PORT (embedded seekdb at $DATA_DIR/powercontext-seekdb)"
  # Redirected stdio + disown fully detach the server so this script (and any wrapper such as
  # `wsl -- bash -c`) can exit without waiting on it.
  nohup powercontext server run --env-file "$PC_ENV" \
    < /dev/null > "$DATA_DIR/powercontext.log" 2>&1 &
  echo $! > "$DATA_DIR/powercontext.pid"
  disown || true
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$PC_PORT/health/ready" >/dev/null 2>&1; then break; fi
    sleep 2
  done
fi

if curl -fsS "http://127.0.0.1:$PC_PORT/health/ready" >/dev/null 2>&1; then
  log "PowerContext Server ready on http://127.0.0.1:$PC_PORT"
else
  log "ERROR: PowerContext Server did not become ready; see $DATA_DIR/powercontext.log"
  tail -20 "$DATA_DIR/powercontext.log" || true
  exit 1
fi

# --- 2. LabTrace backend ----------------------------------------------------
if [[ ! -x "$VENV/bin/python" ]]; then
  log "ERROR: virtualenv not found at $VENV"
  log "  uv venv --python 3.12 $VENV"
  log "  uv pip install --python $VENV/bin/python -r $QODER_DIR/backend/requirements.txt"
  exit 1
fi

BACKEND_ENV="$QODER_DIR/.env"
if [[ ! -f "$BACKEND_ENV" ]]; then
  cat > "$BACKEND_ENV" <<EOF
SEEKDB_MODE=embedded
SEEKDB_PATH=$DATA_DIR/labtrace-seekdb
EMBEDDING_DIMENSION=384
POWERCONTEXT_URL=http://127.0.0.1:$PC_PORT
LABTRACE_HOST=0.0.0.0
LABTRACE_PORT=$API_PORT
LABTRACE_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
LABTRACE_MAX_UPLOAD_MB=20
EOF
  log "created $BACKEND_ENV"
fi

if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then
  log "LabTrace backend already running on port $API_PORT"
else
  log "starting LabTrace backend on port $API_PORT"
  ( cd "$QODER_DIR/backend" && set -a && . "$BACKEND_ENV" && set +a && \
    nohup "$VENV/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT" \
    < /dev/null > "$DATA_DIR/backend.log" 2>&1 & echo $! > "$DATA_DIR/backend.pid"; disown || true )
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then break; fi
    sleep 2
  done
fi

if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then
  log "LabTrace backend ready on http://127.0.0.1:$API_PORT"
  curl -s "http://127.0.0.1:$API_PORT/api/health"
  echo
else
  log "ERROR: backend did not become ready; see $DATA_DIR/backend.log"
  tail -30 "$DATA_DIR/backend.log" || true
  exit 1
fi
