"""Run the pinned real PowerContext server with an isolated local data directory."""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
os.environ.setdefault("POWERCONTEXT_HOME", str(BASE / "runtime" / "powercontext"))
os.environ.setdefault("POWERCONTEXT_SERVER_HTTP_HOST", "127.0.0.1")
os.environ.setdefault("POWERCONTEXT_SERVER_HTTP_PORT", "18080")
os.environ.setdefault("POWERCONTEXT_SERVER_DATABASE_KIND", "sqlite")
os.environ.setdefault("POWERCONTEXT_SERVER_ACCESS_MODE", "disabled")

if __name__ == "__main__":
    from powercontext.cli.app import main

    sys.argv = [sys.argv[0], "server", "run", "--no-env-file"]
    main()
