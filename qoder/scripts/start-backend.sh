#!/usr/bin/env bash
# Start the LabTrace FastAPI backend.
# Run inside WSL2/Linux/macOS (embedded seekdb requires a POSIX platform).
# Usage: bash scripts/start-backend.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QODER_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$QODER_DIR/backend"
VENV="${LABTRACE_VENV:-$HOME/labtrace-venv}"
PYTHON="$VENV/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "virtualenv not found at $VENV" >&2
  echo "create it with: uv venv --python 3.12 $VENV && uv pip install --python $PYTHON -r $BACKEND_DIR/requirements.txt" >&2
  exit 1
fi

cd "$BACKEND_DIR"
if [[ -f "$QODER_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$QODER_DIR/.env"
  set +a
fi

exec "$PYTHON" -m uvicorn app.main:app --host "${LABTRACE_HOST:-0.0.0.0}" --port "${LABTRACE_PORT:-8100}"
