"""Configuration loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env")


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        return float(raw) if raw.strip() else default
    except ValueError:
        return default


@dataclass
class Settings:
    powercontext_url: str = "http://127.0.0.1:8000"
    powercontext_token: str = ""
    powercontext_timeout: float = 10.0
    powercontext_max_retries: int = 2

    database_url: str = "sqlite:///./grudgetown.db"
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "grudgetown.db")

    game_default_coins: int = 100
    game_max_turns: int = 10
    game_random_seed: int = 42
    game_turns_per_day: int = 2
    memory_importance_threshold: int = 5

    api_host: str = "127.0.0.1"
    api_port: int = 8001

    @classmethod
    def load(cls) -> "Settings":
        _load_env()
        database_url = os.environ.get("DATABASE_URL", "sqlite:///./grudgetown.db")
        if database_url.startswith("sqlite:///"):
            raw_path = database_url[len("sqlite:///"):]
            db_path = (PROJECT_ROOT / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path)
        else:
            db_path = PROJECT_ROOT / "grudgetown.db"
        return cls(
            powercontext_url=os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/"),
            powercontext_token=os.environ.get("POWERCONTEXT_TOKEN", ""),
            powercontext_timeout=_float_env("POWERCONTEXT_TIMEOUT", 10.0),
            powercontext_max_retries=_int_env("POWERCONTEXT_MAX_RETRIES", 2),
            database_url=database_url,
            db_path=db_path,
            game_default_coins=_int_env("GAME_DEFAULT_COINS", 100),
            game_max_turns=_int_env("GAME_MAX_TURNS", 10),
            game_random_seed=_int_env("GAME_RANDOM_SEED", 42),
            game_turns_per_day=_int_env("GAME_TURNS_PER_DAY", 2),
            memory_importance_threshold=_int_env("GAME_MEMORY_IMPORTANCE_THRESHOLD", 5),
            api_host=os.environ.get("API_HOST", "127.0.0.1"),
            api_port=_int_env("API_PORT", 8001),
        )


def load_json(name: str, data_dir: Path | None = None) -> dict:
    import json

    path = (data_dir or DEFAULT_DATA_DIR) / name
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
