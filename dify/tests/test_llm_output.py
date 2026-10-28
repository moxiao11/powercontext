import json

import pytest

from backend.llm_output import format_npc_reply, parse_intent_output
from backend.models import TurnRequest


def test_reasoning_json_does_not_override_the_final_intent():
    raw = '<think>{"action_type":"chat"}</think>{"action_type":"lie_identity","target":"baker"}'
    result = json.loads(parse_intent_output(raw)["intent_json"])
    assert result == {"action_type": "lie_identity", "target": "baker"}


@pytest.mark.parametrize("raw", [
    '```json\n{"action_type":"buy","target":"baker"}\n```',
    'Final answer: {"action_type":"buy","target":"baker"}',
    '{"action_type":"buy","target":"baker"}',
])
def test_final_json_accepts_plain_fenced_and_prefixed_outputs(raw):
    assert json.loads(parse_intent_output(raw)["intent_json"])["action_type"] == "buy"


@pytest.mark.parametrize("raw", [
    "not JSON", '<think>incomplete', '{"action_type":"reset"}',
])
def test_unusable_model_output_is_safe_chat(raw):
    assert json.loads(parse_intent_output(raw)["intent_json"]) == {"action_type": "chat"}


def test_npc_answer_contains_only_final_dialogue():
    raw = '<think><!--provider-marker-->internal notes</think>欢迎来到面包店。'
    assert format_npc_reply(raw) == {"text": "欢迎来到面包店。"}
    assert "internal" not in format_npc_reply('<think>internal unfinished')["text"]


def test_reasoning_prefixed_intent_causes_real_state_and_memory_changes(engine):
    player = "reasoning_regression"
    engine.handle_turn(TurnRequest(player_id=player, message="开始游戏"))
    engine.handle_turn(TurnRequest(player_id=player, message="前往面包店"))
    intent = parse_intent_output('<think>notes</think>{"action_type":"lie_identity","target":"baker","content":"自称是国王的儿子"}')
    response = engine.handle_turn(TurnRequest(player_id=player, message="我是国王的儿子。", **intent))
    state = engine._load(player)
    assert state["reputation"] == 45
    assert state["relationships"]["baker"]["trust"] == 40
    assert response["memory_status"] == "saved"
