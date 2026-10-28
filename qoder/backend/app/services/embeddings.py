from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

import httpx

from app.config import Settings

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]")


class EmbeddingError(RuntimeError):
    pass


def local_hash_embedding(text: str, dim: int) -> list[float]:
    """Deterministic bag-of-tokens embedding used when no embedding API is configured.

    Not semantic: identical/similar surface tokens land in the same buckets, so
    keyword-style vector recall still works while the full ANN pipeline stays real.
    """
    vector = [0.0] * dim
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm > 0:
        vector = [value / norm for value in vector]
    return vector


def format_vector(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    @property
    def dimension(self) -> int:
        return self._settings.embedding_dimension

    @property
    def provider(self) -> str:
        return "openai-compatible" if self._settings.embedding_api_enabled else "local-hash-fallback"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._settings.embedding_api_enabled:
            try:
                return await self._embed_remote(texts)
            except httpx.HTTPError as exc:
                raise EmbeddingError(
                    "Embedding service unavailable. No hash vectors were written; "
                    "retry after the configured service recovers. Keyword search remains available."
                ) from exc
        return [local_hash_embedding(text, self.dimension) for text in texts]

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    async def _embed_remote(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        url = f"{self._settings.openai_base_url}/embeddings"
        response = await self._client.post(
            url,
            headers={"Authorization": f"Bearer {self._settings.openai_api_key}"},
            json={"model": self._settings.embedding_model, "input": texts},
        )
        if response.status_code != 200:
            raise EmbeddingError(f"Embedding service returned HTTP {response.status_code}; retry later.")
        try:
            items = sorted(response.json()["data"], key=lambda item: item["index"])
            if [item["index"] for item in items] != list(range(len(texts))):
                raise ValueError("response must contain exactly one indexed vector per input")
            vectors = [[float(value) for value in item["embedding"]] for item in items]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError("Embedding service returned an invalid vector batch.") from exc
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingError(
                    f"embedding dimension mismatch: model returned {len(vector)}, "
                    f"configured EMBEDDING_DIMENSION={self.dimension}"
                )
            if not all(math.isfinite(value) for value in vector):
                raise EmbeddingError("Embedding service returned non-finite values.")
        return vectors

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
