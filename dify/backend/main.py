"""GrudgeTown FastAPI 入口。

运行：uvicorn backend.main:app --host 127.0.0.1 --port 8001
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.config import Settings, load_json
from backend.database import Database
from backend.game_engine import GameEngine
from backend.memory_service import PowerContextClient
from backend.models import (
    NewsResponse,
    RecallRequest,
    RecallResponse,
    RememberRequest,
    RememberResponse,
    ResetRequest,
    ResetResponse,
    StartRequest,
    StateRequest,
    StateResponse,
    TurnRequest,
    TurnResponse,
    ViewRequest,
)
from backend.rumor_engine import RumorEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("grudgetown.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    rules = load_json("rules.json")
    npc_config = load_json("npc_config.json")
    initial_state = load_json("initial_state.json")

    db = Database(settings.db_path)
    memory = PowerContextClient(
        base_url=settings.powercontext_url,
        token=settings.powercontext_token,
        timeout=settings.powercontext_timeout,
        max_retries=settings.powercontext_max_retries,
        db=db,
    )
    engine = GameEngine(
        db=db,
        settings=settings,
        rules=rules,
        npc_config=npc_config,
        initial_state=initial_state,
        rumor_engine=RumorEngine(db, npc_config),
        memory=memory,
    )

    app = FastAPI(title="GrudgeTown 记仇小镇", version="1.0.0")
    app.state.engine = engine
    app.state.settings = settings

    def error_response(status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message, "details": {}}})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return error_response(422, "invalid_request", "请求参数不符合接口契约")

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception):
        logger.exception("未处理异常")
        return error_response(500, "internal_error", "服务器内部错误，请稍后重试")

    @app.get("/health")
    def health():
        reachable = memory.health()
        return {
            "status": "ok",
            "powercontext_reachable": reachable,
            "powercontext_url": settings.powercontext_url,
            "database": str(settings.db_path.name),
        }

    def _state_response(player_id: str, view_kind: str = "status") -> dict:
        state = engine._load(player_id)
        if state is None:
            return {"exists": False, "state": None, "rendered_text": "玩家不存在。请先输入「开始游戏」。"}
        rendered = engine.view(state, view_kind)["rendered_text"]
        from backend.models import PlayerState, Relationship

        player_state = PlayerState(
            player_id=state["player_id"], day=state["day"], turn=state["turn"],
            coins=state["coins"], reputation=state["reputation"],
            location=state["location"], location_name=engine.location_name(state["location"]),
            inventory=state["inventory"],
            relationships={k: Relationship(**v) for k, v in state["relationships"].items()},
            quests=state["quests"], game_over=state["game_over"], ending=state.get("ending"),
        )
        return {"exists": True, "state": player_state.model_dump(), "rendered_text": rendered}

    @app.post("/api/game/start")
    def start(req: StartRequest) -> StateResponse:
        response = engine.handle_turn(
            TurnRequest(player_id=req.player_id, message="开始游戏", intent=None, request_id=None)
        )
        state_view = _state_response(req.player_id)
        return StateResponse(
            exists=True,
            state=state_view.get("state"),
            rendered_text=response["rendered_text"] or state_view.get("rendered_text", ""),
        )

    @app.post("/api/game/state")
    def state(req: StateRequest) -> StateResponse:
        return StateResponse(**_state_response(req.player_id))

    @app.post("/api/game/turn")
    def turn(req: TurnRequest) -> TurnResponse:
        result = engine.handle_turn(req)
        return TurnResponse(**result)

    @app.post("/api/game/action")
    def action(req: TurnRequest) -> TurnResponse:
        """与 /api/game/turn 等价：处理一次玩家互动（命令或自然语言）。"""
        result = engine.handle_turn(req)
        return TurnResponse(**result)

    @app.post("/api/game/view")
    def view(req: ViewRequest) -> StateResponse:
        state_view = _state_response(req.player_id, req.view_kind)
        return StateResponse(**state_view)

    @app.post("/api/game/news")
    def news(req: StateRequest) -> NewsResponse:
        state = engine._load(req.player_id)
        if state is None:
            return NewsResponse(news=[], rendered_text="玩家不存在。请先「开始游戏」。")
        rendered = engine.view(state, "news")["rendered_text"]
        rumor_rows = engine.db.list_rumors(req.player_id)
        seen: dict[str, dict] = {}
        for row in rumor_rows:
            root = row["root_event_id"]
            if root not in seen or row["spread_count"] > seen[root]["spread_count"]:
                seen[root] = row
        return NewsResponse(news=[r["content"] for r in seen.values()], rendered_text=rendered)

    @app.post("/api/game/reset")
    def reset(req: ResetRequest) -> ResetResponse:
        engine.reset_player(req.player_id)
        return ResetResponse(success=True, scope_regenerated=True, detail="玩家状态已重置，记忆空间已切换到新一代。")

    @app.post("/api/memory/recall")
    def recall(req: RecallRequest) -> RecallResponse:
        result = engine.recall(req.player_id, req.npc_id, req.query)
        return RecallResponse(**result)

    @app.post("/api/memory/remember")
    def remember(req: RememberRequest) -> RememberResponse:
        result = engine.remember_direct(req.player_id, req.text, req.event_id)
        return RememberResponse(**result)

    @app.get("/api/memory/log")
    def memory_log(player_id: str):
        """PowerContext 请求审计日志（脱敏），用于验证记录。"""
        rows = db.list_memory_log(player_id)
        return {"log": rows}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = Settings.load()
    uvicorn.run("backend.main:app", host=settings.api_host, port=settings.api_port, reload=False)
