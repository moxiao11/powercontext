"""初始化演示玩家：创建初始状态并可选预热 PowerContext scope。

用法：
    .venv/Scripts/python scripts/init_game.py --player player_demo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.database import Database  # noqa: E402
from backend.game_engine import GameEngine  # noqa: E402
from backend.memory_service import PowerContextClient  # noqa: E402
from backend.models import TurnRequest  # noqa: E402
from backend.rumor_engine import RumorEngine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", default="player_demo")
    args = parser.parse_args()

    settings = Settings.load()
    db = Database(settings.db_path)
    memory = PowerContextClient(
        settings.powercontext_url, settings.powercontext_token,
        settings.powercontext_timeout, settings.powercontext_max_retries, db,
    )
    from backend.config import load_json

    engine = GameEngine(
        db=db, settings=settings,
        rules=load_json("rules.json"), npc_config=load_json("npc_config.json"),
        initial_state=load_json("initial_state.json"),
        rumor_engine=RumorEngine(db, load_json("npc_config.json")),
        memory=memory,
    )
    response = engine.handle_turn(TurnRequest(player_id=args.player, message="开始游戏"))
    state = db.get_player(args.player)
    print(response["rendered_text"])
    print("-" * 40)
    print(f"玩家 {args.player} 初始化完成：coins={state['coins']} reputation={state['reputation']}")
    print(f"数据库：{settings.db_path}")
    print(f"PowerContext：{settings.powercontext_url} reachable={memory.health()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
