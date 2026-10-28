#!/usr/bin/env bash
# Start the PowerContext Server used by LabTrace (embedded seekdb storage).
# Run inside WSL2/Linux/macOS. Usage: bash scripts/start-powercontext.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QODER_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${POWERCONTEXT_ENV_FILE:-$HOME/labtrace-data/powercontext.env}"

export PATH="$HOME/.local/bin:$PATH"

if ! command -v powercontext >/dev/null 2>&1; then
  echo "powercontext CLI not found. Install it first:" >&2
  echo "  uv tool install --force --with 'pymysql<1.2' 'powercontext[cli,server,seekdb]==1.2.0'" >&2
  echo "  pymysql must stay below 1.2: aiomysql 0.3.2 still calls the escape_bytes_prefixed" >&2
  echo "  helper that pymysql 1.2 turned into a sentinel string, which breaks bytes parameters." >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  sed "s|__LABTRACE_HOME__|$HOME|g" "$SCRIPT_DIR/powercontext.env.example" > "$ENV_FILE"
  echo "created $ENV_FILE from template"
fi

echo "starting PowerContext Server with $ENV_FILE"
exec powercontext server run --env-file "$ENV_FILE"
