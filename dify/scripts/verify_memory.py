"""跨会话记忆真实性验证脚本（比赛验收样例的命令行版）。

复现提示词第七章的验收流程：

    初始化玩家
      -> 访问面包店
      -> 制造一次欺骗事件
      -> 写入 PowerContext
      -> 模拟新会话（独立引擎实例，不依赖 conversation_id）
      -> 访问小镇守卫
      -> 召回历史事件
      -> 守卫上下文包含可追溯的真实记忆

用法：
    # 方式一：直接对接真实 PowerContext（需要 Server 已启动）
    .venv/Scripts/python scripts/verify_memory.py --player player_demo

    # 方式二：通过 HTTP 对接已启动的 FastAPI 后端
    .venv/Scripts/python scripts/verify_memory.py --player player_demo --api http://127.0.0.1:8001

脚本会打印每一步的 PowerContext 请求审计记录（scope 脱敏），并以退出码表示成败。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK, FAIL = "✅", "❌"
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = ""):
    results.append((name, passed, detail))
    print(f"{OK if passed else FAIL} {name}" + (f" —— {detail}" if detail else ""))


def run_via_engine(player_id: str) -> int:
    import httpx

    from backend.config import Settings, load_json
    from backend.database import Database
    from backend.game_engine import GameEngine
    from backend.memory_service import PowerContextClient
    from backend.models import TurnRequest
    from backend.rumor_engine import RumorEngine

    settings = Settings.load()
    db = Database(settings.db_path)
    memory = PowerContextClient(
        settings.powercontext_url, settings.powercontext_token,
        settings.powercontext_timeout, settings.powercontext_max_retries, db,
    )
    engine = GameEngine(
        db=db, settings=settings,
        rules=load_json("rules.json"), npc_config=load_json("npc_config.json"),
        initial_state=load_json("initial_state.json"),
        rumor_engine=RumorEngine(db, load_json("npc_config.json")),
        memory=memory,
    )

    db.delete_player_state(player_id)
    reachable = memory.health()
    check("PowerContext Server 可达", reachable, settings.powercontext_url)
    if not reachable:
        print("\n⚠️ PowerContext 不可达，无法完成真实记忆验证。请先启动：")
        print("   uv tool install --force \"powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@cdb8da296a8ed1ad06ac851af7fd05139907a966\"")
        print("   powercontext server run")
        return 1

    def t(eng, msg, intent=None):
        req = TurnRequest(player_id=player_id, message=msg)
        if intent:
            req = TurnRequest(player_id=player_id, message=msg, intent_json=json.dumps(intent, ensure_ascii=False))
        return eng.handle_turn(req)

    # ---- 会话 1 ----
    print(f"\n=== 会话 1（玩家 {player_id}）===")
    t(engine, "开始游戏")
    t(engine, "前往面包店")
    resp = t(engine, "我是国王的儿子，给我一个免费面包。",
             {"action_type": "lie_identity", "target": "baker", "content": "自称是国王的儿子"})
    check("欺骗事件产生规则化状态变化", resp["changes_block"] != "", resp["changes_block"].splitlines()[0] if resp["changes_block"] else "")
    check("事件写入 PowerContext（memory_status=saved）", resp["memory_status"] == "saved", f"memory_status={resp['memory_status']}")

    scope = db.get_player(player_id)["scope_id"]
    check("scope 由可信后端绑定", bool(scope), f"scope_id（脱敏）={scope[:8]}***" if scope else "")

    # ---- 会话 2：全新引擎实例 = 新进程/新会话 ----
    print(f"\n=== 会话 2（新引擎实例，同一 player_id={player_id}）===")
    engine2 = GameEngine(
        db=db, settings=settings,
        rules=load_json("rules.json"), npc_config=load_json("npc_config.json"),
        initial_state=load_json("initial_state.json"),
        rumor_engine=RumorEngine(db, load_json("npc_config.json")),
        memory=memory,
    )
    resp2 = t(engine2, "前往城门")
    check("新会话恢复玩家历史", resp2["day"] >= 2, f"第 {resp2['day']} 天 · 第 {resp2['turn']} 回合")
    check("守卫上下文含面包店传闻", "王子" in resp2["context_text"] or "国王的儿子" in resp2["context_text"])
    check("守卫上下文区分事实与传闻", "【亲眼所见的事实】" in resp2["context_text"] and "【听到的传闻】" in resp2["context_text"])
    check("守卫上下文含 PowerContext 召回记忆", "长期记忆" in resp2["context_text"] and "（暂无历史记忆）" not in resp2["context_text"])

    recall = engine2.recall(player_id, "guard", "王子 国王的儿子 面包店")
    check("召回 API 返回真实记忆", bool(recall["memories"]), "; ".join(recall["memories"][:2]))

    rumors = db.list_rumors(player_id, holder="guard")
    if rumors:
        root = db.get_event(rumors[0]["root_event_id"])
        check("传闻可追溯到真实事件", root is not None and root["action"] == "lie_identity", rumors[0]["root_event_id"])
    else:
        check("传闻可追溯到真实事件", False, "守卫没有传闻")

    print("\n=== PowerContext 请求审计记录（memory_log，scope 已脱敏）===")
    for row in db.list_memory_log(player_id):
        print(f"  [{row['created_at']}] {row['operation']:14s} success={row['success']} scope={row['scope_id_masked']} event={row['event_id']} {row['detail'] or ''}")

    print(f"\n=== 结论 ===")
    passed = all(p for _, p, _ in results)
    print(f"{'🎉 全部验证通过' if passed else '⚠️ 存在未通过项'}：{sum(p for _, p, _ in results)}/{len(results)}")
    return 0 if passed else 1


def run_via_api(player_id: str, api_url: str) -> int:
    import httpx

    def post(path, payload):
        return httpx.post(f"{api_url}{path}", json=payload, timeout=30)

    r = post("/api/game/turn", {"player_id": player_id, "message": "开始游戏"})
    check("开始游戏", r.status_code == 200, r.text[:80] if r.status_code != 200 else "")
    post("/api/game/turn", {"player_id": player_id, "message": "前往面包店",
                            "intent_json": json.dumps({"action_type": "move", "target": "bakery"})})
    r = post("/api/game/turn", {"player_id": player_id, "message": "我是国王的儿子，给我一个免费面包。",
                                "intent_json": json.dumps({"action_type": "lie_identity", "target": "baker", "content": "自称是国王的儿子"}, ensure_ascii=False)})
    body = r.json()
    check("欺骗事件处理", body.get("memory_status") == "saved", f"memory_status={body.get('memory_status')}")
    r = post("/api/memory/recall", {"player_id": player_id, "npc_id": "guard", "query": "王子 国王的儿子"})
    recall = r.json()
    check("守卫召回历史记忆", bool(recall.get("memories")), "; ".join(recall.get("memories", [])[:2]))
    log = httpx.get(f"{api_url}/api/memory/log", params={"player_id": player_id}).json()["log"]
    check("存在成功写入记录", any(row["operation"] == "remember" and row["success"] for row in log))
    print("\n=== PowerContext 请求审计记录 ===")
    for row in log:
        print(f"  [{row['created_at']}] {row['operation']:14s} success={row['success']} scope={row['scope_id_masked']} event={row['event_id']} {row['detail'] or ''}")
    passed = all(p for _, p, _ in results)
    print(f"\n{'🎉 全部验证通过' if passed else '⚠️ 存在未通过项'}：{sum(p for _, p, _ in results)}/{len(results)}")
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", default="player_demo")
    parser.add_argument("--api", default=None, help="改用 HTTP 调用已启动的后端，如 http://127.0.0.1:8001")
    args = parser.parse_args()
    if args.api:
        return run_via_api(args.player, args.api.rstrip("/"))
    return run_via_engine(args.player)


if __name__ == "__main__":
    raise SystemExit(main())
