"""Pydantic schemas for the GrudgeTown API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ActionType = Literal[
    "start_game",
    "reset",
    "move",
    "view",
    "chat",
    "lie_identity",
    "steal",
    "buy",
    "give_gift",
    "help",
    "apologize",
    "compensate",
    "threaten",
    "spread_rumor",
]


class Intent(BaseModel):
    """Dify 意图 LLM / 命令解析节点输出的结构化意图。"""

    action_type: ActionType
    target: str | None = None
    view_kind: str | None = None
    amount: int | None = None
    content: str | None = None


class TurnRequest(BaseModel):
    """Dify turn 端点统一入口：命令与自然语言互动共用。

    intent_json：Dify 侧（Code/LLM 节点）产出的意图 JSON 字符串。
    后端会解析并做白名单校验，无法解析或非法 action_type 一律降级为 chat。
    """

    player_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    intent: Intent | None = None
    intent_json: str | None = Field(default=None, max_length=4000)
    request_id: str | None = Field(default=None, max_length=128)


class StartRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=64)


class StateRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=64)


class ResetRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=64)


class ViewRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=64)
    view_kind: Literal["status", "inventory", "quests", "news"] = "status"


class RecallRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=64)
    npc_id: Literal["baker", "guard", "witch"] | None = None
    query: str = Field(default="", max_length=256)


class RememberRequest(BaseModel):
    player_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)
    event_id: str | None = None


class Relationship(BaseModel):
    affection: int
    trust: int


class PlayerState(BaseModel):
    player_id: str
    day: int
    turn: int
    coins: int
    reputation: int
    location: str
    location_name: str
    inventory: list[str]
    relationships: dict[str, Relationship]
    quests: dict[str, str]
    game_over: bool
    ending: str | None = None


class MemoryStatus(BaseModel):
    powercontext_reachable: bool
    scope_id_masked: str | None = None
    last_operation: str | None = None
    last_success: bool | None = None
    detail: str | None = None


class TurnResponse(BaseModel):
    """turn 端点响应。reply_type=direct 时 Dify 直接渲染 rendered_text；
    reply_type=npc 时 Dify 用 context_text 驱动对应 NPC 的 LLM 节点。"""

    reply_type: Literal["direct", "npc"]
    rendered_text: str = ""
    npc: str | None = None
    npc_name: str | None = None
    day: int = 1
    turn: int = 0
    day_label: str = ""
    location: str = ""
    location_name: str = ""
    context_text: str = ""
    changes_block: str = ""
    news_block: str = ""
    ending_block: str = ""
    memory_status: str = "skipped"
    event_id: str | None = None
    ending: str | None = None
    game_over: bool = False
    error: str | None = None


class StateResponse(BaseModel):
    exists: bool
    state: PlayerState | None = None
    rendered_text: str = ""


class NewsResponse(BaseModel):
    news: list[str]
    rendered_text: str


class RecallResponse(BaseModel):
    npc_id: str | None = None
    scope_id_masked: str | None = None
    prepared_content: str | None = None
    memories: list[str] = []
    verified_facts: list[str] = []
    rumors: list[str] = []
    context_text: str = ""
    powercontext_reachable: bool = True


class RememberResponse(BaseModel):
    success: bool
    event_id: str | None = None
    scope_id_masked: str | None = None
    detail: str = ""


class ResetResponse(BaseModel):
    success: bool
    scope_regenerated: bool
    detail: str = ""


class ErrorResponse(BaseModel):
    error: dict
