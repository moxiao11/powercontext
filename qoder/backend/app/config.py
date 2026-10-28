from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    seekdb_mode: Literal["embedded", "remote"] = "embedded"
    seekdb_path: str = "/tmp/labtrace-seekdb"
    seekdb_host: str = "127.0.0.1"
    seekdb_port: int = 2881
    seekdb_user: str = "root"
    seekdb_password: str = ""
    seekdb_database: str = "test"
    # LabTrace corpora are Chinese research notes with English technical terms. `space` and
    # `beng` cannot tokenize CJK at all (verified against seekdb 1.4.0), so the default is
    # `ik`; `ngram` also works but over-matches English phrases.
    seekdb_fulltext_parser: Literal["ik", "ngram", "space", "beng"] = "ik"

    embedding_dimension: int = Field(default=384, ge=8, le=4096)
    document_chunk_max_chars: int = Field(default=700, ge=200, le=4000)

    openai_base_url: str = ""
    openai_api_key: str = ""
    chat_model: str = ""
    embedding_model: str = ""

    powercontext_url: str = "http://127.0.0.1:8000"
    powercontext_token: str = ""

    labtrace_host: str = "0.0.0.0"
    labtrace_port: int = 8100
    labtrace_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    labtrace_max_upload_mb: int = 20

    @field_validator("openai_base_url", "powercontext_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.labtrace_cors_origins.split(",") if origin.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key and self.chat_model and self.openai_base_url)

    @property
    def embedding_api_enabled(self) -> bool:
        return bool(self.openai_api_key and self.embedding_model and self.openai_base_url)

    @property
    def max_upload_bytes(self) -> int:
        return self.labtrace_max_upload_mb * 1024 * 1024

    def resolved_seekdb_path(self) -> Path:
        return Path(self.seekdb_path).expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
