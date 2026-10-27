import argparse
import sys
import time
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from sdd_context.common import load_env
from sdd_context.store import EngineeringStore
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    load_env(BASE / ".env")
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            store = EngineeringStore()
            import pymysql
            with pymysql.connect(**store.config) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT VERSION() AS version")
                    version = cursor.fetchone()["version"]
            url = os.getenv("SDD_POWERCONTEXT_URL", "http://127.0.0.1:18080")
            headers = {"Authorization": "Bearer " + os.environ["SDD_POWERCONTEXT_TOKEN"]} if os.getenv("SDD_POWERCONTEXT_TOKEN") else {}
            response = httpx.get(url + "/health/ready", headers=headers, timeout=5)
            if response.status_code == 200 and response.json()["status"] == "ready":
                print("seekdb version:", version)
                print("PowerContext: ready")
                return 0
        except (OSError, ValueError, pymysql.Error, httpx.HTTPError):
            pass
        time.sleep(1)
    print("Services not ready. Check database port, PowerContext process, and .env.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
