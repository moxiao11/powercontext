"""重置演示玩家：恢复初始状态、清空事件与传闻、轮换记忆 scope 代际。

用法：
    .venv/Scripts/python scripts/reset_demo.py --player player_demo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.database import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", default="player_demo")
    parser.add_argument("--db", default=None, help="覆盖数据库路径")
    args = parser.parse_args()

    settings = Settings.load()
    if args.db:
        settings.db_path = Path(args.db)
    db = Database(settings.db_path)
    old = db.get_player(args.player)
    generation = (old["scope_generation"] + 1) if old else 0
    db.delete_player_state(args.player)
    print(f"玩家 {args.player} 已重置。")
    print(f"历史事件、传闻与处理记录已清空；记忆 scope 切换到 gen{generation}（幂等键 grudgetown-{args.player}-gen{generation}）。")
    print(f"数据库：{settings.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
