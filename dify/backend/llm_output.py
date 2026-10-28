"""Standalone helpers also embedded in Dify Code nodes (stdlib only)."""
from __future__ import annotations

import json
import re

INTENT_ACTIONS = {
    "chat", "lie_identity", "steal", "buy", "give_gift", "help",
    "apologize", "compensate", "threaten", "spread_rumor",
}


def strip_thinking(text: str) -> str:
    """Keep final output when a provider merges reasoning into its text field."""
    cleaned = re.sub(r"<think\b[^>]*>.*?</think\s*>", "", text or "", flags=re.I | re.S)
    cleaned = re.sub(r"<think\b[^>]*>.*\Z", "", cleaned, flags=re.I | re.S)
    return re.sub(r"<!--.*?-->", "", cleaned, flags=re.S).strip()


def parse_intent_output(text: str) -> dict:
    cleaned = strip_thinking(text)
    decoder = json.JSONDecoder()
    for opening in re.finditer(r"\{", cleaned):
        try:
            value, _ = decoder.raw_decode(cleaned[opening.start():])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("action_type") in INTENT_ACTIONS:
            return {"intent_json": json.dumps(value, ensure_ascii=False)}
    return {"intent_json": json.dumps({"action_type": "chat"})}


def format_npc_reply(text: str) -> dict:
    return {"text": strip_thinking(text) or "对方若有所思，暂时没有回答。请再说一句。"}
