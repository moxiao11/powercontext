"""Configure an official Dify 1.18.0 Docker checkout for local GrudgeTown.

Creates fresh private runtime settings; never overwrites an existing .env.
"""
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import secrets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-dir", required=True)
    parser.add_argument("--backend-ip", required=True, help="IPv4 address resolved by host.docker.internal inside Docker")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Invalid published port")
    backend_ip = ipaddress.IPv4Address(args.backend_ip)
    folder = Path(args.docker_dir).resolve()
    target = folder / ".env"
    override = folder / "docker-compose.override.yaml"
    if target.exists() or override.exists():
        parser.error("Existing .env or Compose override found; preserve it and configure manually")
    text = (folder / ".env.example").read_text(encoding="utf-8")
    database_password, redis_password = secrets.token_hex(16), secrets.token_hex(16)
    sandbox_key, vector_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    base = f"http://localhost:{args.port}"
    values = {key: base for key in ("CONSOLE_API_URL", "CONSOLE_WEB_URL", "SERVICE_API_URL", "APP_API_URL", "APP_WEB_URL", "FILES_URL", "TRIGGER_URL")}
    values.update({
        "ENDPOINT_URL_TEMPLATE": base + "/e/{hook_id}",
        "NEXT_PUBLIC_SOCKET_URL": f"ws://localhost:{args.port}",
        "SECRET_KEY": secrets.token_urlsafe(42),
        "DB_PASSWORD": database_password,
        "REDIS_PASSWORD": redis_password,
        "CELERY_BROKER_URL": f"redis://:{redis_password}@redis:6379/1",
        "PLUGIN_DAEMON_KEY": secrets.token_urlsafe(42),
        "PLUGIN_DIFY_INNER_API_KEY": secrets.token_urlsafe(42),
        "DIFY_AGENT_API_TOKEN": secrets.token_urlsafe(32),
        "DIFY_AGENT_SERVER_SECRET_KEY": secrets.token_urlsafe(32),
        "DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN": secrets.token_urlsafe(32),
        "CODE_EXECUTION_API_KEY": sandbox_key,
        "SANDBOX_API_KEY": sandbox_key,
        "WEAVIATE_API_KEY": vector_key,
        "WEAVIATE_AUTHENTICATION_APIKEY_ALLOWED_KEYS": vector_key,
        "EXPOSE_NGINX_PORT": str(args.port),
        "EXPOSE_NGINX_SSL_PORT": "8443",
        "EXPOSE_PLUGIN_DEBUGGING_PORT": "5003",
        "SSRF_PROXY_ALLOW_PRIVATE_IPS": f"{backend_ip}/32",
    })
    for key, value in values.items():
        text, count = re.subn(r"^" + re.escape(key) + r"=.*$", lambda _: key + "=" + value, text, flags=re.M)
        if count != 1:
            raise ValueError(f"Unexpected Dify template field: {key}; use release 1.18.0")
    text += "\nCOMPOSE_PROJECT_NAME=grudgetown-dify\n"
    target.write_text(text, encoding="utf-8")
    override.write_text(
        'services:\n  nginx:\n    ports: !override\n'
        f'      - "127.0.0.1:{args.port}:80"\n'
        '      - "127.0.0.1:8443:443"\n'
        '  plugin_daemon:\n    ports: !override\n      - "127.0.0.1:5003:5003"\n',
        encoding="utf-8",
    )
    print(f"Configured {folder}; private values omitted. Run docker compose up -d there.")


if __name__ == "__main__":
    main()
