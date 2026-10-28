"""Embedding fallback vectors and vector literal formatting."""

from __future__ import annotations

import math

import httpx
import pytest

from app.config import Settings
from app.services.embeddings import EmbeddingError, EmbeddingService, format_vector, local_hash_embedding


def test_local_hash_embedding_is_deterministic_and_normalised() -> None:
    first = local_hash_embedding("三段式场景记忆 hierarchical scene memory", 384)
    second = local_hash_embedding("三段式场景记忆 hierarchical scene memory", 384)

    assert first == second
    assert len(first) == 384
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0, rel_tol=1e-9)


def test_local_hash_embedding_separates_different_text() -> None:
    assert local_hash_embedding("物体摘要记忆", 64) != local_hash_embedding("全局外观嵌入", 64)


def test_local_hash_embedding_tokenises_chinese_per_character() -> None:
    # Without CJK tokenisation every Chinese query would collapse to the same bucket set.
    assert local_hash_embedding("记忆", 64) != local_hash_embedding("回忆", 64)


def test_local_hash_embedding_returns_zero_vector_without_tokens() -> None:
    assert local_hash_embedding("！！！…", 32) == [0.0] * 32
    assert local_hash_embedding("", 32) == [0.0] * 32


def test_local_hash_embedding_honours_configured_dimension() -> None:
    assert len(local_hash_embedding("scene memory", 8)) == 8
    assert len(local_hash_embedding("scene memory", 1536)) == 1536


def test_format_vector_matches_seekdb_literal_syntax() -> None:
    assert format_vector([1.0, 2.5, -0.125]) == "[1.00000000,2.50000000,-0.12500000]"


async def test_service_reports_local_fallback_when_no_api_configured(settings: Settings) -> None:
    service = EmbeddingService(settings)
    assert service.provider == "local-hash-fallback"
    assert service.dimension == 16

    vectors = await service.embed(["场景记忆", "scene memory"])
    assert len(vectors) == 2
    assert all(len(vector) == 16 for vector in vectors)
    await service.close()


async def test_service_embed_returns_empty_list_for_no_input(settings: Settings) -> None:
    service = EmbeddingService(settings)
    assert await service.embed([]) == []
    await service.close()


async def test_configured_remote_service_does_not_mix_hash_vectors_on_failure() -> None:
    settings = Settings(
        _env_file=None,
        embedding_dimension=16,
        openai_base_url="http://127.0.0.1:1/v1",
        openai_api_key="test-key",
        embedding_model="text-embedding-test",
    )
    service = EmbeddingService(settings)
    assert service.provider == "openai-compatible"

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    service._client = httpx.AsyncClient(transport=httpx.MockTransport(unavailable))

    with pytest.raises(EmbeddingError, match="No hash vectors were written"):
        await service.embed_one("场景记忆")
    await service.close()


@pytest.mark.parametrize(
    "data",
    [
        [],
        [{"index": 1, "embedding": [0.1] * 16}],
        [{"index": 0, "embedding": [0.1] * 15}],
        [{"index": 0, "embedding": ["NaN"] * 16}],
        [{"index": 0, "embedding": ["invalid"] * 16}],
    ],
)
async def test_remote_embedding_rejects_incomplete_or_invalid_batches(data: list) -> None:
    service = EmbeddingService(
        Settings(
            _env_file=None,
            embedding_dimension=16,
            openai_base_url="http://embedding.test/v1",
            openai_api_key="test-key",
            embedding_model="test-model",
        )
    )
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": data}))
    )
    try:
        with pytest.raises(EmbeddingError):
            await service.embed(["证据"])
    finally:
        await service.close()


async def test_remote_embeddings_preserve_input_order() -> None:
    service = EmbeddingService(
        Settings(
            _env_file=None,
            embedding_dimension=16,
            openai_base_url="http://embedding.test/v1",
            openai_api_key="test-key",
            embedding_model="test-model",
        )
    )
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.2] * 16},
                        {"index": 0, "embedding": [0.1] * 16},
                    ]
                },
            )
        )
    )
    try:
        assert await service.embed(["第一段", "第二段"]) == [[0.1] * 16, [0.2] * 16]
    finally:
        await service.close()


def test_embedding_api_requires_all_three_settings() -> None:
    assert Settings(_env_file=None, openai_api_key="k", chat_model="m").embedding_api_enabled is False
    assert (
        Settings(
            _env_file=None,
            openai_api_key="k",
            embedding_model="e",
            openai_base_url="http://localhost/v1",
        ).embedding_api_enabled
        is True
    )


def test_llm_enabled_requires_key_model_and_base_url() -> None:
    assert Settings(_env_file=None).llm_enabled is False
    assert (
        Settings(
            _env_file=None,
            openai_api_key="k",
            chat_model="m",
            openai_base_url="http://localhost/v1/",
        ).llm_enabled
        is True
    )


def test_trailing_slash_is_stripped_from_base_urls() -> None:
    settings = Settings(_env_file=None, openai_base_url="http://x/v1/", powercontext_url="http://y/")
    assert settings.openai_base_url == "http://x/v1"
    assert settings.powercontext_url == "http://y"


def test_upload_limit_is_expressed_in_bytes() -> None:
    assert Settings(_env_file=None, labtrace_max_upload_mb=20).max_upload_bytes == 20 * 1024 * 1024


def test_cors_origins_are_parsed_and_trimmed() -> None:
    settings = Settings(_env_file=None, labtrace_cors_origins="http://a:5173, http://b:5173 ,")
    assert settings.cors_origins == ["http://a:5173", "http://b:5173"]


def test_rejected_configuration_values() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, embedding_dimension=4)
    with pytest.raises(ValueError):
        Settings(_env_file=None, seekdb_fulltext_parser="chinese")
