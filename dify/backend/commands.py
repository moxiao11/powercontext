"""确定性命令解析：不依赖 LLM，保证命令行为可复现。

Dify 侧由 Code 节点完成同样的解析（见 dsl/grudge_town_chatflow.yml）；
后端保留一份实现，便于脚本与测试在不经过 Dify 的情况下驱动同一套流程。
"""

from __future__ import annotations

import re

_MOVE_ALIASES = [
    (r"前往面包店|去面包店|走进面包店|面包店", "bakery"),
    (r"前往城门|去城门|走向城门|城门口|找守卫|见守卫", "gate"),
    (r"前往魔法屋|去魔法屋|走进魔法屋|魔法屋|找女巫|见女巫", "witch_hut"),
    (r"回广场|去广场|小镇广场|返回广场", "square"),
]

_VIEW_ALIASES = [
    (r"查看状态|我的状态|当前状态", "status"),
    (r"查看背包|我的背包|打开背包", "inventory"),
    (r"查看任务|我的任务|任务列表", "quests"),
    (r"查看小镇新闻|小镇新闻|查看新闻|最新消息", "news"),
]


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def parse_command(message: str) -> dict | None:
    """返回结构化意图 dict，未匹配命令时返回 None（进入自然语言互动流程）。"""
    text = normalize(message)
    if not text:
        return None
    if re.fullmatch(r"开始游戏|开始新游戏|新游戏|开局", text):
        return {"action_type": "start_game"}
    if re.fullmatch(r"重新开始|重置游戏|重新来过|重来", text):
        return {"action_type": "reset"}
    for pattern, view_kind in _VIEW_ALIASES:
        if re.fullmatch(pattern, text):
            return {"action_type": "view", "view_kind": view_kind}
    for pattern, location in _MOVE_ALIASES:
        if re.fullmatch(pattern, text):
            return {"action_type": "move", "target": location}
    if re.fullmatch(r"前往.{0,6}", text) and len(text) <= 8:
        return {"action_type": "unknown_move"}
    return None
