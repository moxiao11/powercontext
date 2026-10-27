"""Verify the published Dify Chatflow and real PowerContext memory.

Uses the same public WebApp endpoints as Dify's published chat page. No
administrator credentials or persistent API keys are created or recorded.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", required=True, help="Published Dify /chat/<code> URL")
    parser.add_argument("--api", default="http://127.0.0.1:8001", help="Game backend")
    parser.add_argument("--player", default="judge_dify_verify", help="Dedicated test player; reset before testing")
    parser.add_argument("--output", default="docs/evidence/dify-smoke.json")
    args = parser.parse_args()
    parsed = urlsplit(args.app_url)
    if parsed.scheme not in {"http", "https"} or "/chat/" not in parsed.path:
        parser.error("--app-url must be a published HTTP(S) /chat/<code> URL")
    app_code = parsed.path.split("/chat/", 1)[1].split("/", 1)[0]
    base = f"{parsed.scheme}://{parsed.netloc}"
    evidence = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "player_id": args.player,
        "dify_origin": base,
        "checks": [],
        "conversations": [],
        "turns": [],
    }

    def check(name: str, condition: bool) -> None:
        evidence["checks"].append({"name": name, "passed": bool(condition)})
        print(f"{'PASS' if condition else 'FAIL'} {name}", flush=True)

    def checked(response: httpx.Response) -> dict:
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code} from {urlsplit(str(response.url)).path}")
        return response.json()

    try:
        with httpx.Client(trust_env=False, timeout=httpx.Timeout(150, connect=10)) as client:
            checked(client.post(args.api.rstrip("/") + "/api/game/reset", json={"player_id": args.player}))
            passport = checked(client.get(base + "/api/passport", headers={"X-App-Code": app_code}))
            headers = {"X-App-Code": app_code, "X-App-Passport": passport["access_token"]}

            def message(query: str, conversation: str | None = None) -> dict:
                print(f"Dify input: {query}", flush=True)
                body = {"inputs": {"player_id": args.player}, "query": query, "response_mode": "blocking"}
                if conversation:
                    body["conversation_id"] = conversation
                result = checked(client.post(base + "/api/chat-messages", json=body, headers=headers))
                answer = result.get("answer", "")
                if not answer or result.get("event") == "error":
                    raise RuntimeError("Dify did not return a successful answer")
                # Only controlled test dialogue and token counts are saved; never passport/header values.
                usage = result.get("metadata", {}).get("usage", {})
                evidence["turns"].append({
                    "query": query, "answer": answer,
                    "conversation_id": result.get("conversation_id"),
                    "total_tokens": usage.get("total_tokens"),
                })
                print("Dify answer received", flush=True)
                return result

            first = message("开始游戏")
            conversation = first["conversation_id"]
            evidence["conversations"].append(conversation)
            check("Dify initializes the game", "记仇小镇" in first["answer"])
            baker = message("前往面包店", conversation)
            check("Baker NPC answers through Dify", "老张" in baker["answer"])
            lie = message("其实我是国王的儿子，给我一个免费面包。", conversation)
            state = checked(client.post(args.api.rstrip("/") + "/api/game/state", json={"player_id": args.player}))
            evidence["state_after_lie"] = state.get("state")
            check("Natural language becomes a real lie_identity action", state["state"]["reputation"] == 45)
            check("Baker trust changes deterministically", state["state"]["relationships"]["baker"]["trust"] == 40)

            guard = message("前往城门")
            second_conversation = guard["conversation_id"]
            evidence["conversations"].append(second_conversation)
            check("A new Dify conversation keeps the same player", second_conversation != conversation)
            check("Guard responds to the previous identity story", bool(re.search("王子|国王|身份", guard["answer"])))
            witch = message("前往魔法屋", second_conversation)
            check("Witch NPC answers through Dify", "莉莉丝" in witch["answer"] or "女巫" in witch["answer"])
            recall = checked(client.post(args.api.rstrip("/") + "/api/memory/recall", json={
                "player_id": args.player, "npc_id": "guard", "query": "国王的儿子 王子 面包店",
            }))
            evidence["recalled_memories"] = recall.get("memories", [])
            check("Real PowerContext returns historical memory", bool(recall.get("memories")))
            logs = checked(client.get(args.api.rstrip("/") + "/api/memory/log", params={"player_id": args.player}))["log"]
            cutoff = evidence["started_at_utc"][:19].replace("T", " ")
            logs = [row for row in logs if row["created_at"] >= cutoff]
            allowed = {"created_at", "operation", "success", "scope_id_masked", "event_id", "detail"}
            evidence["memory_log"] = [{key: value for key, value in row.items() if key in allowed} for row in logs]
            check("PowerContext remember succeeded", any(row["operation"] == "remember" and row["success"] for row in logs))
            check("PowerContext recall succeeded", any(row["operation"] in {"search", "prepare"} and row["success"] for row in logs))
            check("Players only see final NPC dialogue", all("<think" not in turn["answer"].lower() for turn in evidence["turns"]))
    except Exception as error:
        evidence["error"] = str(error)
        check("End-to-end execution completes", False)
    passed = bool(evidence["checks"]) and all(item["passed"] for item in evidence["checks"])
    evidence["passed"] = passed
    evidence["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evidence saved: {output.resolve()}", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
