"""八卦传播引擎：确定性、可复现、有来源、可追溯。

每条传闻都必须追溯到一条真实事件（root_event_id / source_event_id），
传播只产生新的「传闻版本」，永不修改原始事件记录。
"""

from __future__ import annotations

import random
from typing import Any

from backend.database import Database


class RumorEngine:
    def __init__(self, db: Database, npc_config: dict):
        self.db = db
        self.npc_config = npc_config
        self.edges = {(e["from"], e["to"]): float(e["probability"]) for e in npc_config["social_graph"]["edges"]}
        self.exaggeration = npc_config["exaggeration"]

    # -- creation -----------------------------------------------------------

    def create_rumor(
        self,
        rng: random.Random,
        player_id: str,
        event: dict[str, Any],
        origin: str,
        day: int,
        turn: int,
        confidence: float = 0.7,
        content: str | None = None,
        truth_status: str = "unverified",
    ) -> dict[str, Any] | None:
        """目击者把事件变成传闻（origin 同时是第一任持有者）。"""
        npc_names = {k: v["name"] for k, v in self.npc_config["npcs"].items()}
        base = content or event["description"]
        rumor = {
            "rumor_id": f"rumor_{event['event_id']}_{origin}",
            "player_id": player_id,
            "root_event_id": event["event_id"],
            "source_event_id": event["event_id"],
            "origin": origin,
            "holder": origin,
            "content": f"{npc_names.get(origin, origin)}目击：{base}",
            "truth_status": truth_status,
            "confidence": confidence,
            "spread_count": 1,
            "day": day,
            "turn": turn,
        }
        inserted = self.db.insert_rumor(rumor)
        return rumor if inserted else None

    def create_player_rumor(
        self,
        player_id: str,
        event: dict[str, Any],
        listener: str,
        day: int,
        turn: int,
        confidence: float,
        content: str,
    ) -> dict[str, Any] | None:
        """玩家主动向某个 NPC 散播的流言：来源仍是真实的 spread_rumor 事件。"""
        rumor = {
            "rumor_id": f"rumor_{event['event_id']}_{listener}",
            "player_id": player_id,
            "root_event_id": event["event_id"],
            "source_event_id": event["event_id"],
            "origin": "player",
            "holder": listener,
            "content": content,
            "truth_status": "unverified",
            "confidence": confidence,
            "spread_count": 1,
            "day": day,
            "turn": turn,
        }
        inserted = self.db.insert_rumor(rumor)
        return rumor if inserted else None

    def create_clarification_rumor(
        self,
        player_id: str,
        resolved_event: dict[str, Any],
        origin: str,
        listener: str,
        day: int,
        turn: int,
        content: str,
    ) -> dict[str, Any] | None:
        """澄清性传闻（例如老板赔偿后主动向守卫澄清），覆盖同事件同持有者的旧坏传闻。"""
        rumor = {
            "rumor_id": f"rumor_{resolved_event['event_id']}_clarify_{listener}",
            "player_id": player_id,
            "root_event_id": resolved_event["event_id"],
            "source_event_id": resolved_event["event_id"],
            "origin": origin,
            "holder": listener,
            "content": content,
            "truth_status": "verified",
            "confidence": 0.9,
            "spread_count": 2,
            "day": day,
            "turn": turn,
        }
        inserted = self.db.upsert_rumor(rumor)
        return rumor if inserted else None

    # -- spreading ----------------------------------------------------------

    def _neighbors(self, npc_id: str) -> list[tuple[str, float]]:
        return [(to, prob) for (frm, to), prob in self.edges.items() if frm == npc_id]

    def spread_tick(self, rng: random.Random, player_id: str, day: int, turn: int, guaranteed_event_ids: set[str] | None = None) -> list[dict[str, Any]]:
        """每个回合结算一次传播。

        guaranteed_event_ids：重要度极高（>=8）的事件首跳保底传播，保证演示可复现。
        去重由数据库 UNIQUE(root_event_id, holder) 保证，origin 不再接收自己的传闻，
        spread_count 达到上限后停止，因此不存在无限循环。
        """
        guaranteed_event_ids = guaranteed_event_ids or set()
        npc_names = {k: v["name"] for k, v in self.npc_config["npcs"].items()}
        spread: list[dict[str, Any]] = []
        rumors = self.db.list_rumors(player_id)
        seen_root_holders = {(r["root_event_id"], r["holder"]) for r in rumors}
        for rumor in rumors:
            if rumor["spread_count"] >= self.exaggeration["max_spread_count"]:
                continue
            guaranteed = rumor["root_event_id"] in guaranteed_event_ids and rumor["spread_count"] == 1
            for target, prob in self._neighbors(rumor["holder"]):
                if target == rumor["holder"] or target == rumor["origin"]:
                    continue
                if (rumor["root_event_id"], target) in seen_root_holders:
                    continue
                if not guaranteed and rng.random() > prob:
                    continue
                level = min(rumor["spread_count"], len(self.exaggeration["levels"]) - 1)
                template = self.exaggeration["levels"][level]
                new_content = template.format(
                    origin=npc_names.get(rumor["holder"], rumor["holder"]),
                    content=rumor["content"],
                )
                new_rumor = {
                    "rumor_id": f"rumor_{rumor['root_event_id']}_{target}_{rumor['spread_count'] + 1}",
                    "player_id": player_id,
                    "root_event_id": rumor["root_event_id"],
                    "source_event_id": rumor["source_event_id"],
                    "origin": rumor["origin"],
                    "holder": target,
                    "content": new_content,
                    "truth_status": "unverified",
                    "confidence": round(rumor["confidence"] * self.exaggeration["confidence_decay"], 3),
                    "spread_count": rumor["spread_count"] + 1,
                    "day": day,
                    "turn": turn,
                }
                if self.db.insert_rumor(new_rumor):
                    seen_root_holders.add((rumor["root_event_id"], target))
                    spread.append(new_rumor)
        return spread
