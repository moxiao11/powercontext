from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    research_profile: str | None = Field(default=None, max_length=4000)


class ProjectOut(BaseModel):
    project_id: str
    name: str
    description: str | None
    pc_scope_id: str | None
    document_count: int = 0
    experiment_count: int = 0
    created_at: str
    updated_at: str


class SearchRequest(BaseModel):
    project_id: str
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["hybrid", "keyword", "vector"] = "hybrid"
    limit: int = Field(default=8, ge=1, le=50)
    doc_id: str | None = None


class SearchResult(BaseModel):
    query: str
    mode: str
    engine: str
    sql_mode: str
    hits: list[dict[str, Any]]
    citations: list[dict[str, Any]]


class ExperimentCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=255)
    objective: str | None = None
    hypothesis: str | None = None
    method: str | None = None
    model_config_json: dict[str, Any] | None = Field(default=None, alias="model_config")
    dataset: str | None = Field(default=None, max_length=255)
    result_summary: str | None = None
    metrics: dict[str, float] | None = None
    issues: str | None = None
    failure_reason: str | None = None
    next_steps: str | None = None
    status: Literal["planned", "running", "completed", "failed", "abandoned"] = "planned"
    log_markdown: str | None = None

    model_config = {"populate_by_name": True, "protected_namespaces": ()}


class ExperimentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    objective: str | None = None
    hypothesis: str | None = None
    method: str | None = None
    model_config_json: dict[str, Any] | None = Field(default=None, alias="model_config")
    dataset: str | None = None
    result_summary: str | None = None
    metrics: dict[str, float] | None = None
    issues: str | None = None
    failure_reason: str | None = None
    next_steps: str | None = None
    status: Literal["planned", "running", "completed", "failed", "abandoned"] | None = None
    log_markdown: str | None = None

    model_config = {"populate_by_name": True, "protected_namespaces": ()}


class ExperimentOut(BaseModel):
    experiment_id: str
    project_id: str
    name: str
    objective: str | None
    hypothesis: str | None
    method: str | None
    model_config_json: dict[str, Any] | None = Field(default=None, alias="model_config")
    dataset: str | None
    result_summary: str | None
    metrics: dict[str, float] | None
    issues: str | None
    failure_reason: str | None
    next_steps: str | None
    status: str
    log_markdown: str | None
    created_at: str
    updated_at: str

    model_config = {"populate_by_name": True, "protected_namespaces": ()}


class ExperimentQueryRequest(BaseModel):
    project_id: str
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=50)


class ChatRequest(BaseModel):
    project_id: str
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class SaveProgressRequest(BaseModel):
    project_id: str
    session_id: str
    summary: str | None = Field(default=None, max_length=8000)
    messages: list[ChatMessage] = Field(default_factory=list)
    completed: list[str] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    decisions: list[dict[str, str]] = Field(default_factory=list)
    failures: list[dict[str, str]] = Field(default_factory=list)
    evidence: dict[str, Any] | None = None


class ExperimentMemoryRequest(BaseModel):
    """Write an experiment's conclusions into PowerContext long-term memory."""

    project_id: str
    conclusion: str | None = Field(default=None, max_length=2000)
    decision: str | None = Field(default=None, max_length=2000)
    next_steps: str | None = Field(default=None, max_length=2000)
    include_failure: bool = True


class MemoryWriteRequest(BaseModel):
    project_id: str
    kind: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)
    reason: str | None = Field(default=None, max_length=1000)
    evidence: dict[str, Any] | None = None


class MemorySearchRequest(BaseModel):
    project_id: str
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=50)


class MemoryReviseRequest(BaseModel):
    project_id: str
    citation: dict[str, Any]
    kind: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)
    reason: str | None = Field(default=None, max_length=1000)


class MemoryRetireRequest(BaseModel):
    project_id: str
    citation: dict[str, Any]
    reason: str | None = Field(default=None, max_length=1000)


class ReportRequest(BaseModel):
    project_id: str
    start_date: date
    end_date: date
    title: str | None = Field(default=None, max_length=255)


class HealthOut(BaseModel):
    status: str
    seekdb: dict[str, Any]
    powercontext: dict[str, Any]
    llm: dict[str, Any]
    embedding: dict[str, Any]
