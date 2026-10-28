"""Request contract validation: the API rejects malformed payloads before touching any store."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas import (
    ChatRequest,
    ExperimentCreate,
    MemoryWriteRequest,
    ProjectCreate,
    ReportRequest,
    SaveProgressRequest,
    SearchRequest,
)


def test_search_request_defaults_to_hybrid_and_clamps_limits() -> None:
    payload = SearchRequest(project_id="prj_1", query="场景记忆")
    assert payload.mode == "hybrid"
    assert payload.limit == 8

    with pytest.raises(ValidationError):
        SearchRequest(project_id="prj_1", query="场景记忆", limit=0)
    with pytest.raises(ValidationError):
        SearchRequest(project_id="prj_1", query="场景记忆", limit=51)
    with pytest.raises(ValidationError):
        SearchRequest(project_id="prj_1", query="场景记忆", mode="semantic")
    with pytest.raises(ValidationError):
        SearchRequest(project_id="prj_1", query="")


def test_project_create_requires_a_name() -> None:
    assert ProjectCreate(name="EQA 研究").description is None
    with pytest.raises(ValidationError):
        ProjectCreate(name="")


def test_experiment_create_accepts_the_model_config_alias() -> None:
    payload = ExperimentCreate.model_validate(
        {
            "project_id": "prj_1",
            "name": "HSM v1",
            "model_config": {"lr": 0.001},
            "metrics": {"accuracy": 58.7},
            "status": "completed",
        }
    )
    assert payload.model_config_json == {"lr": 0.001}
    assert payload.metrics == {"accuracy": 58.7}


def test_experiment_create_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        ExperimentCreate(project_id="prj_1", name="x", status="exploded")


def test_experiment_create_defaults_to_planned() -> None:
    assert ExperimentCreate(project_id="prj_1", name="x").status == "planned"


def test_memory_write_requires_kind_and_text() -> None:
    payload = MemoryWriteRequest(project_id="prj_1", kind="decision", text="改用房间 ID 硬约束")
    assert payload.reason is None

    with pytest.raises(ValidationError):
        MemoryWriteRequest(project_id="prj_1", kind="", text="x")
    with pytest.raises(ValidationError):
        MemoryWriteRequest(project_id="prj_1", kind="decision", text="")
    with pytest.raises(ValidationError):
        MemoryWriteRequest(project_id="prj_1", kind="decision", text="x" * 4001)


def test_chat_request_bounds_the_message() -> None:
    assert ChatRequest(project_id="prj_1", message="问题").session_id is None
    with pytest.raises(ValidationError):
        ChatRequest(project_id="prj_1", message="")
    with pytest.raises(ValidationError):
        ChatRequest(project_id="prj_1", message="x" * 8001)


def test_save_progress_request_defaults_to_empty_collections() -> None:
    payload = SaveProgressRequest(project_id="prj_1", session_id="sess_1")
    assert payload.completed == []
    assert payload.decisions == []
    assert payload.messages == []


def test_save_progress_request_validates_message_roles() -> None:
    with pytest.raises(ValidationError):
        SaveProgressRequest.model_validate(
            {"project_id": "prj_1", "session_id": "s", "messages": [{"role": "system", "content": "x"}]}
        )


def test_report_request_parses_iso_dates() -> None:
    payload = ReportRequest(project_id="prj_1", start_date="2026-10-20", end_date="2026-10-26")
    assert payload.start_date == date(2026, 10, 20)
    assert payload.title is None

    with pytest.raises(ValidationError):
        ReportRequest(project_id="prj_1", start_date="not-a-date", end_date="2026-10-26")
