"""Research long-term memory built on PowerContext.

LabTrace memory kinds (PowerContext `kind` is a free-form label):
  research_profile  - the user's research direction and long-term goals
  project_context   - background and task of the current project
  decision          - an important research decision and its reason
  failure           - an attempt that failed and why
  progress          - what has been completed
  next_action       - the planned next step

Evidence linkage: writes record traceable identifiers (experiment_id, doc_id,
chunk_id, session_id) in the `reason` field. `reason` is write-only in
PowerContext — it is never returned by list or search — so anything a user must
be able to see is also tagged into the entry text, e.g. ` [exp:<experiment_id>]`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.db.seekdb import SeekDB
from app.services import experiments as exp_service
from app.services import projects as project_service
from app.services.powercontext import (
    PowerContextClient,
    PowerContextError,
    source_citation,
    statement,
)

logger = logging.getLogger(__name__)

MEMORY_KINDS = (
    "research_profile",
    "project_context",
    "decision",
    "failure",
    "progress",
    "next_action",
)

KIND_LABELS = {
    "research_profile": "研究方向",
    "project_context": "项目背景",
    "decision": "研究决策",
    "failure": "失败记录",
    "progress": "进展",
    "next_action": "下一步",
}

# RememberMemoryRequest.reason is capped at 512 characters (PowerContext 1.2.0 OpenAPI schema).
_REASON_MAX_CHARS = 512


class MemoryError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _reason(reason: str | None, evidence: dict[str, Any] | None) -> str | None:
    """Compose the provenance string accepted by /v1/memory/remember.

    PowerContext caps `reason` at 512 characters and never returns it on list or search, so the
    human-readable part is kept intact and the evidence blob is only appended when it still fits.
    """
    head = reason.strip() if reason and reason.strip() else ""
    if not evidence:
        return head[:_REASON_MAX_CHARS] or None
    blob = "evidence: " + json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    joined = f"{head} | {blob}" if head else blob
    if len(joined) <= _REASON_MAX_CHARS:
        return joined
    return head[:_REASON_MAX_CHARS] or None


async def write_memory(
    pc: PowerContextClient,
    *,
    scope_id: str,
    kind: str,
    text: str,
    reason: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if kind not in MEMORY_KINDS:
        raise MemoryError(f"unknown memory kind '{kind}'; expected one of {', '.join(MEMORY_KINDS)}")
    try:
        result = await pc.remember(
            scope_id=scope_id, kind=kind, text=text.strip(), reason=_reason(reason, evidence)
        )
    except PowerContextError as exc:
        raise MemoryError(str(exc)) from exc
    entry = result.get("entry") or {}
    return {
        "citation": entry.get("citation"),
        "kind": entry.get("kind", kind),
        "kind_label": KIND_LABELS.get(kind, kind),
        "text": entry.get("text", text),
        "version": entry.get("version"),
        "state": entry.get("state"),
        "memory_ref": result.get("memory"),
        "saved_at": _utc_now(),
    }


async def search_memories(
    pc: PowerContextClient, *, scope_id: str, query: str, limit: int = 10
) -> dict[str, Any]:
    try:
        result = await pc.search_memory(scope_id=scope_id, query=query, limit=limit)
    except PowerContextError as exc:
        raise MemoryError(str(exc)) from exc
    return {"mode": result.get("mode"), "hits": [_shape_hit(hit) for hit in result.get("hits", [])]}


async def list_memories(
    pc: PowerContextClient, *, scope_id: str, include_inactive: bool = False
) -> dict[str, Any]:
    try:
        result = await pc.list_entries(scope_id=scope_id, include_inactive=include_inactive)
    except PowerContextError as exc:
        raise MemoryError(str(exc)) from exc
    entries = [_shape_entry(entry) for entry in result.get("entries", [])]
    grouped: dict[str, list[dict[str, Any]]] = {kind: [] for kind in MEMORY_KINDS}
    for entry in entries:
        grouped.setdefault(entry["kind"], []).append(entry)
    return {"memory_ref": result.get("memory"), "entries": entries, "grouped": grouped, "total": len(entries)}


def _shape_entry(entry: dict[str, Any]) -> dict[str, Any]:
    kind = entry.get("kind", "")
    return {
        "citation": entry.get("citation"),
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
        "text": entry.get("text"),
        "version": entry.get("version"),
        "state": entry.get("state"),
        "source_refs": entry.get("source_refs", []),
        "artifact_refs": entry.get("artifact_refs", []),
    }


def _shape_hit(hit: dict[str, Any]) -> dict[str, Any]:
    entry = hit.get("entry") or hit
    shaped = _shape_entry(entry)
    for key in ("score", "matched_text", "reason"):
        if key in hit:
            shaped[key] = hit[key]
    return shaped


async def revise_memory(
    pc: PowerContextClient,
    *,
    scope_id: str,
    citation: dict[str, Any],
    kind: str,
    text: str,
    reason: str | None = None,
) -> dict[str, Any]:
    if kind not in MEMORY_KINDS:
        raise MemoryError(f"unknown memory kind '{kind}'")
    reason = _reason(reason, None)
    try:
        result = await pc.revise_entry(
            scope_id=scope_id, citation=citation, kind=kind, text=text, reason=reason
        )
    except PowerContextError as exc:
        refreshed = await _retry_on_stale_revision(pc, scope_id=scope_id, citation=citation, error=exc)
        if refreshed is None:
            raise MemoryError(str(exc)) from exc
        try:
            result = await pc.revise_entry(
                scope_id=scope_id, citation=refreshed, kind=kind, text=text, reason=_reason(reason, None)
            )
        except PowerContextError as retry_exc:
            raise MemoryError(str(retry_exc)) from retry_exc
    return _shape_entry(result.get("entry") or {})


async def retire_memory(
    pc: PowerContextClient, *, scope_id: str, citation: dict[str, Any], reason: str | None = None
) -> dict[str, Any]:
    reason = _reason(reason, None)
    try:
        result = await pc.retire_entry(scope_id=scope_id, citation=citation, reason=reason)
    except PowerContextError as exc:
        refreshed = await _retry_on_stale_revision(pc, scope_id=scope_id, citation=citation, error=exc)
        if refreshed is None:
            raise MemoryError(str(exc)) from exc
        try:
            result = await pc.retire_entry(scope_id=scope_id, citation=refreshed, reason=reason)
        except PowerContextError as retry_exc:
            raise MemoryError(str(retry_exc)) from retry_exc
    return {"retired": True, "memory": result.get("memory"), "entry": _shape_entry(result.get("entry") or {})}


async def _retry_on_stale_revision(
    pc: PowerContextClient, *, scope_id: str, citation: dict[str, Any], error: PowerContextError
) -> dict[str, Any] | None:
    """Re-read one entry's citation after a `revision_conflict`, or return None if not retryable.

    A MemoryCitation pins the memory artifact revision, and every successful mutation bumps that
    revision. Citations collected in one batch therefore go stale as soon as the first mutation
    lands, which PowerContext reports as HTTP 409 `revision_conflict`.
    """
    if error.status_code != 409 or "revision_conflict" not in str(error.detail or ""):
        return None
    try:
        stored = await pc.list_entries(scope_id=scope_id, include_inactive=True)
    except PowerContextError:
        return None
    entry_id = (citation or {}).get("entry_id")
    for entry in stored.get("entries", []):
        found = entry.get("citation") or {}
        if found.get("entry_id") == entry_id:
            # An unrelated entry can advance the artifact revision. Only retry when this
            # entry's content version is unchanged; otherwise a retry would overwrite a
            # concurrent correction or retirement made by another session.
            if found.get("entry_version_id") != citation.get("entry_version_id"):
                return None
            return found
    return None


async def prepare_research_context(
    pc: PowerContextClient, *, scope_id: str, query: str, max_bytes: int = 8000
) -> dict[str, Any]:
    """Bounded historical context for one model request (untrusted evidence)."""
    try:
        prepared = await pc.prepare_context(scope_id=scope_id, query=query, max_bytes=max_bytes)
    except PowerContextError as exc:
        raise MemoryError(str(exc)) from exc
    return {
        "status": prepared.get("status"),
        "content": prepared.get("content"),
        "content_bytes": prepared.get("content_bytes"),
        "max_bytes": max_bytes,
        "schema": prepared.get("schema"),
    }


async def save_progress(
    pc: PowerContextClient,
    *,
    scope_id: str,
    project_name: str,
    session_id: str,
    summary: str | None,
    messages: list[dict[str, str]],
    completed: list[str] | None = None,
    conclusions: list[str] | None = None,
    open_questions: list[str] | None = None,
    next_steps: list[str] | None = None,
    decisions: list[dict[str, str]] | None = None,
    failures: list[dict[str, str]] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the current research session: Source evidence + Memory entries + committed Handoff."""
    transcript = _render_transcript(messages)
    source_content = _render_source(
        project_name=project_name,
        session_id=session_id,
        summary=summary,
        completed=completed,
        conclusions=conclusions,
        open_questions=open_questions,
        next_steps=next_steps,
        transcript=transcript,
        decisions=decisions,
        failures=failures,
    )
    source_id = f"labtrace-session-{session_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    try:
        captured = await pc.capture_source(
            scope_id=scope_id,
            source_id=source_id,
            content=source_content,
            metadata={
                "origin": "labtrace-save-progress",
                "session_id": session_id,
                "project": project_name,
                **(evidence or {}),
            },
        )
    except PowerContextError as exc:
        raise MemoryError(f"failed to capture research session source: {exc}") from exc
    source_ref = captured["source"]
    citation = source_citation(source_ref)

    written: list[dict[str, Any]] = []
    for item in completed or []:
        written.append(await _safe_write(pc, scope_id, "progress", item, evidence, session_id))
    for item in conclusions or []:
        written.append(await _safe_write(pc, scope_id, "decision", item, evidence, session_id))
    for item in decisions or []:
        written.append(
            await _safe_write(
                pc, scope_id, "decision", _with_reason(item), evidence, session_id, item.get("reason")
            )
        )
    for item in failures or []:
        written.append(
            await _safe_write(
                pc, scope_id, "failure", _with_reason(item), evidence, session_id, item.get("reason")
            )
        )
    for item in next_steps or []:
        written.append(await _safe_write(pc, scope_id, "next_action", item, evidence, session_id))
    failed_writes = [item for item in written if item and item.get("error")]
    written = [item for item in written if item and not item.get("error")]

    objective = summary.strip() if summary and summary.strip() else f"{project_name} 的当前研究任务"
    state_statements = [
        statement(text, [citation])
        for text in (
            [objective]
            + list(completed or [])
            + list(conclusions or [])
            + [_with_reason(item) for item in (decisions or []) + (failures or [])]
        )
        if text and text.strip()
    ][:64]
    if not state_statements:
        state_statements = [statement("本次会话未提供可确认的研究状态。", [citation])]

    next_text = "; ".join(item for item in (next_steps or []) if item.strip()) or "待用户明确下一步研究计划。"
    draft = {
        "objective": objective[:8000],
        "state": state_statements,
        "disposition": "blocked" if (open_questions and not next_steps) else "continuable",
        "next_action": statement(next_text[:8000], [citation]),
        "omissions": [
            {"text": question[:8000], "citation": citation}
            for question in (open_questions or [])
            if question.strip()
        ][:64],
    }

    handoff: dict[str, Any] = {"status": "skipped"}
    try:
        prepared = await pc.finalize_handoff(scope_id=scope_id, draft=draft)
        committed = await pc.commit_handoff(scope_id=scope_id, prepared=prepared)
        handoff = {"status": "committed", "reference": committed.get("reference")}
    except PowerContextError as exc:
        logger.warning("handoff commit failed for scope %s: %s", scope_id, exc)
        handoff = {"status": "failed", "error": str(exc)}

    return {
        "status": "partial" if failed_writes or handoff.get("status") == "failed" else "saved",
        "failed_writes": failed_writes,
        "scope_id": scope_id,
        "session_id": session_id,
        "source": source_ref,
        "source_position": captured.get("position"),
        "memories": written,
        "handoff": handoff,
        "saved_at": _utc_now(),
    }


async def _safe_write(
    pc: PowerContextClient,
    scope_id: str,
    kind: str,
    text: str,
    evidence: dict[str, Any] | None,
    session_id: str,
    reason: str | None = None,
) -> dict[str, Any] | None:
    if not text or not text.strip():
        return None
    try:
        return await write_memory(
            pc,
            scope_id=scope_id,
            kind=kind,
            text=f"{text.strip()} [session:{session_id}]",
            reason=reason or f"session {session_id}",
            evidence=evidence,
        )
    except MemoryError as exc:
        logger.warning("memory write (%s) failed: %s", kind, exc)
        return {"kind": kind, "text": text, "error": str(exc)}


def _with_reason(item: dict[str, str]) -> str:
    text = item.get("text", "").strip()
    reason = item.get("reason", "").strip()
    return f"{text}；原因：{reason}" if text and reason else text


async def restore_progress(pc: PowerContextClient, *, scope_id: str, project_name: str) -> dict[str, Any]:
    """Restore saved research context in a brand-new session."""
    result: dict[str, Any] = {
        "scope_id": scope_id,
        "project": project_name,
        "handoff": None,
        "handoff_error": None,
        "memories": [],
        "prepared_context": None,
        "restored_at": _utc_now(),
    }
    try:
        resolution = await pc.continue_handoff(scope_id=scope_id, selection="latest")
        result["handoff"] = {
            "status": resolution.get("status"),
            "selected_revision": resolution.get("selected_revision"),
            "content": resolution.get("content"),
            "evidence_checks": resolution.get("evidence_checks", []),
        }
    except PowerContextError as exc:
        result["handoff_error"] = str(exc)

    try:
        listing = await list_memories(pc, scope_id=scope_id)
        result["memories"] = listing["entries"]
        result["grouped"] = listing["grouped"]
    except MemoryError as exc:
        result["memory_error"] = str(exc)

    try:
        prepared = await prepare_research_context(pc, scope_id=scope_id, query="当前研究进展与下一步计划")
        result["prepared_context"] = prepared
    except MemoryError as exc:
        result["prepared_context_error"] = str(exc)

    result["answer"] = _render_restore_answer(result)
    return result


def _render_restore_answer(result: dict[str, Any]) -> str:
    # Handoff is an immutable session snapshot. A later correction/retirement must
    # take precedence when presenting the project's current research state.
    if "grouped" in result and not result.get("memory_error"):
        lines = []
        for kind in MEMORY_KINDS:
            for entry in result["grouped"].get(kind, []):
                if entry.get("state", "active") == "active":
                    lines.append(f"- {KIND_LABELS.get(kind, kind)}：{entry.get('text')}")
        if lines:
            return "已从 PowerContext 恢复当前有效的记忆条目：\n" + "\n".join(lines)
        if result.get("handoff"):
            return (
                "PowerContext 中当前没有有效记忆。上次会话 Handoff 仍保留为历史快照，"
                "其中内容可能已修订或停用；请在历史面板核对后再继续研究。"
            )
    handoff = result.get("handoff") or {}
    content = handoff.get("content") or {}
    lines: list[str] = []
    if content.get("objective"):
        lines.append(f"研究目标：{content['objective']}")
    for item in content.get("state", []) or []:
        if item.get("text"):
            lines.append(f"- 已确认状态：{item['text']}")
    next_action = content.get("next_action") or {}
    if next_action.get("text"):
        lines.append(f"下一步：{next_action['text']}")
    for omission in content.get("omissions", []) or []:
        if omission.get("text"):
            lines.append(f"- 未解决/未覆盖：{omission['text']}")
    if not lines:
        grouped = result.get("grouped") or {}
        for kind in ("progress", "decision", "failure", "next_action"):
            for entry in grouped.get(kind, [])[:3]:
                lines.append(f"- {KIND_LABELS.get(kind, kind)}：{entry.get('text')}")
    if not lines:
        return "PowerContext 中没有找到该项目已保存的研究进度。请先在会话中点击“保存本次研究进度”。"
    header = "已从 PowerContext 恢复此前保存的研究上下文：\n"
    if result.get("handoff_error"):
        header = "已恢复记忆条目（未找到已提交的 Handoff 记录）：\n"
    return header + "\n".join(lines)


def _render_transcript(messages: list[dict[str, str]], limit: int = 40) -> str:
    if not messages:
        return ""
    tail = messages[-limit:]
    return "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in tail)


def _render_source(
    *,
    project_name: str,
    session_id: str,
    summary: str | None,
    completed: list[str] | None,
    conclusions: list[str] | None,
    open_questions: list[str] | None,
    next_steps: list[str] | None,
    transcript: str,
    decisions: list[dict[str, str]] | None = None,
    failures: list[dict[str, str]] | None = None,
) -> str:
    sections = [
        "# LabTrace 研究进度快照",
        f"项目：{project_name}",
        f"会话：{session_id}",
        f"时间：{_utc_now()}",
    ]
    if summary:
        sections += ["", "## 本次会话总结", summary.strip()]
    if completed:
        sections += ["", "## 已完成事项"] + [f"- {item}" for item in completed if item.strip()]
    if conclusions:
        sections += ["", "## 关键结论"] + [f"- {item}" for item in conclusions if item.strip()]
    for title, items in (("研究决策及原因", decisions), ("失败尝试及原因", failures)):
        if items:
            sections += ["", f"## {title}"] + [f"- {_with_reason(item)}" for item in items]
    if open_questions:
        sections += ["", "## 未解决问题"] + [f"- {item}" for item in open_questions if item.strip()]
    if next_steps:
        sections += ["", "## 后续步骤"] + [f"- {item}" for item in next_steps if item.strip()]
    if transcript:
        sections += ["", "## 会话记录（截断）", transcript]
    return "\n".join(sections)


async def sync_experiment_to_memory(
    db: SeekDB,
    pc: PowerContextClient,
    *,
    project_id: str,
    experiment_id: str,
    conclusion: str | None = None,
    decision: str | None = None,
    next_steps: str | None = None,
    include_failure: bool = True,
) -> dict[str, Any]:
    """Write an experiment's conclusions, decisions and plans into PowerContext.

    Only text that already exists in the seekdb experiment record (or that the caller supplies
    explicitly) is written; nothing is inferred or generated here. Each entry is tagged with the
    experiment_id so a memory can be traced back to its seekdb record.
    """
    scope_id = await project_service.require_scope(db, project_id)
    row = await exp_service.get_experiment(db, experiment_id, project_id)
    if row is None:
        raise MemoryError(f"experiment {experiment_id} not found in project {project_id}")

    evidence = {
        "origin": "labtrace-experiment-sync",
        "experiment_id": experiment_id,
        "project_id": project_id,
        "experiment_name": row.get("name"),
        "status": row.get("status"),
    }
    reason = f"来自实验记录 {row.get('name')}（{experiment_id}）"
    # `reason` is write-only in PowerContext (never returned by list or search), so the traceable
    # link back to the seekdb record has to live in the entry text to stay visible to the user.
    trace_tag = f" [exp:{experiment_id}]"

    written: list[dict[str, Any]] = []
    skipped: list[str] = []

    async def record(kind: str, text: str, detail: str | None = None) -> None:
        text = (text or "").strip()
        if not text:
            skipped.append(kind)
            return
        entry = await write_memory(
            pc,
            scope_id=scope_id,
            kind=kind,
            text=f"{text}{trace_tag}",
            reason=detail or reason,
            evidence=evidence,
        )
        written.append(entry)

    progress_text = (row.get("result_summary") or "").strip()
    if progress_text:
        metrics = row.get("metrics")
        suffix = f"；指标：{json.dumps(metrics, ensure_ascii=False)}" if metrics else ""
        await record("progress", f"{row.get('name')}：{progress_text}{suffix}")
    else:
        skipped.append("progress")

    await record("decision", decision or "", reason)
    if conclusion and conclusion.strip():
        await record("decision", conclusion.strip(), reason)
    if not decision and not conclusion:
        skipped.append("decision")

    if include_failure and row.get("status") in {"failed", "abandoned"}:
        failure_text = (row.get("failure_reason") or row.get("issues") or "").strip()
        if failure_text:
            await record("failure", f"{row.get('name')}：{failure_text}", reason)
        else:
            skipped.append("failure")

    plan = (next_steps or row.get("next_steps") or "").strip()
    for item in [part.strip() for part in plan.replace("；", "\n").split("\n") if part.strip()]:
        await record("next_action", item, reason)
    if not plan:
        skipped.append("next_action")

    logger.info(
        "synced experiment %s to PowerContext scope %s: %d memories written",
        experiment_id,
        scope_id,
        len(written),
    )
    return {
        "experiment_id": experiment_id,
        "experiment_name": row.get("name"),
        "scope_id": scope_id,
        "written": written,
        "skipped": sorted(set(skipped)),
        "evidence": evidence,
    }
