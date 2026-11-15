import asyncio
import json

import pytest

from mobilerun.macro.replay import MacroPlayer
from mobilerun.workflow.registry import WorkflowRegistry


def _node(text, x, y):
    return {
        "text": text,
        "bounds": {"left": x - 80, "top": y - 25, "right": x + 80, "bottom": y + 25},
    }


def _state():
    return {
        "nodes": [
            _node("1,234.07", 525, 750),
            _node("0.00", 197, 750),
            _node("1,234.07", 197, 650),
        ]
    }


def _action(**overrides):
    action = {
        "action_type": "verify_money_sum",
        "label": "funds check",
        "sources": [
            {"label": "available", "x": 525, "y": 750},
            {"label": "market_value", "x": 197, "y": 750},
        ],
        "target": {"label": "total_assets", "x": 197, "y": 650},
        "tolerance": 0.01,
    }
    action.update(overrides)
    return action


def test_verify_money_sum_passes_and_journals_evidence(tmp_path):
    journal = tmp_path / "journal.jsonl"
    player = MacroPlayer(journal_path=str(journal))

    assert asyncio.run(player.replay_action(_action(), current_state=_state())) is True
    event = json.loads(journal.read_text().splitlines()[-1])
    assert event["event"] == "money_verification"
    assert event["calculated_value"] == 1234.07
    assert event["target_value"] == 1234.07
    assert event["difference"] == 0
    assert event["verified"] is True


def test_verify_money_sum_fails_beyond_tolerance(tmp_path):
    journal = tmp_path / "journal.jsonl"
    player = MacroPlayer(journal_path=str(journal))
    state = _state()
    state["nodes"][2] = _node("1,300.00", 197, 650)

    assert asyncio.run(player.replay_action(_action(), current_state=state)) is False
    event = json.loads(journal.read_text().splitlines()[-1])
    assert event["difference"] == pytest.approx(-65.93)
    assert event["verified"] is False


def test_workflow_accepts_money_sum_action(tmp_path):
    source = tmp_path / "macro.json"
    source.write_text(
        json.dumps(
            {
                "macro_schema_version": "2.0",
                "version": "2.0",
                "actions": [
                    {
                        "action_type": "verify_money_sum",
                        "sources": [{"label": "available", "x": 1, "y": 2}],
                        "target": {"label": "total", "x": 3, "y": 4},
                        "pre_state": {"nodes": []},
                    }
                ],
            }
        )
    )
    registry = WorkflowRegistry(tmp_path / "workflows")
    registry.import_macro(source, workflow_id="audit")
    report = registry.validate("audit", version=1)
    assert report.valid


def test_active_cancel_target_only_selects_unique_current_order():
    state = {
        "nodes": [
            {"text": "状态", "bounds": {"top": 376, "bottom": 481}},
            {"text": "买入全部撤单", "bounds": {"top": 500, "bottom": 600}},
            {"text": "其他", "bounds": {"top": 700, "bottom": 800}},
            {"text": "买入全部撤单", "bounds": {"top": 900, "bottom": 1000}},
        ]
    }
    action = {"history_header_text": "其他"}
    target = MacroPlayer._active_cancel_target(state, action)
    assert target is not None
    assert target["bounds"]["top"] == 500

    state["nodes"].append({"text": "买入全部撤单", "bounds": {"top": 550, "bottom": 650}})
    assert MacroPlayer._active_cancel_target(state, action) is None


def test_workflow_requires_cancellation_scope(tmp_path):
    source = tmp_path / "macro.json"
    source.write_text(
        json.dumps(
            {
                "macro_schema_version": "2.0",
                "version": "2.0",
                "actions": [{"action_type": "cancel_active_order", "pre_state": {"nodes": []}}],
            }
        )
    )
    registry = WorkflowRegistry(tmp_path / "workflows")
    registry.import_macro(source, workflow_id="cancel")
    report = registry.validate("cancel", version=1)
    assert not report.valid
    assert any("history_header_text" in error for error in report.errors)


def test_verify_order_status_journals_phase_and_matches_visible_text(tmp_path):
    journal = tmp_path / "journal.jsonl"
    player = MacroPlayer(journal_path=str(journal))
    state = {"nodes": [{"text": "买入 已申报（股票）", "bounds": {}}]}
    action = {
        "action_type": "verify_order_status",
        "label": "pending delegate",
        "phase": "pending",
        "status_texts": ["买入 已申报（股票）", "买入 未报"],
    }

    assert asyncio.run(player.replay_action(action, current_state=state)) is True
    event = json.loads(journal.read_text().splitlines()[-1])
    assert event["event"] == "order_status_verification"
    assert event["phase"] == "pending"
    assert event["verified"] is True


def test_workflow_accepts_session_and_order_status_actions(tmp_path):
    source = tmp_path / "macro.json"
    source.write_text(
        json.dumps(
            {
                "macro_schema_version": "2.0",
                "version": "2.0",
                "actions": [
                    {
                        "action_type": "ensure_broker_session",
                        "broker_name": "{{broker_name}}",
                        "secret_id": "{{password_secret_id}}",
                        "pre_state": {"phone_state": {"package": "com.example"}},
                    },
                    {
                        "action_type": "verify_order_status",
                        "phase": "pending",
                        "status_texts": ["pending"],
                        "pre_state": {"nodes": []},
                    },
                ],
            }
        )
    )
    registry = WorkflowRegistry(tmp_path / "workflows")
    registry.import_macro(source, workflow_id="audit")
    report = registry.validate("audit", version=1)
    assert report.valid
