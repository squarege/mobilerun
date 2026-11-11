import asyncio
import json
from types import SimpleNamespace

from mobilerun.macro.contracts import RecoveryOutcome
from mobilerun.macro.recovery_agent import ScopedRecoveryAgent
from mobilerun.macro.replay import MacroPlayer
from mobilerun.macro.state import normalize_ui_state


class FakeDriver:
    platform = "android"

    def __init__(self, states, *, fail_taps=False):
        self.states = list(states)
        self.taps = []
        self.inputs = []
        self.fail_taps = fail_taps

    async def connect(self):
        return None

    async def get_ui_tree(self):
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]

    async def tap(self, x, y):
        if self.fail_taps:
            raise RuntimeError("tap failed")
        self.taps.append((x, y))

    async def input_text(self, text, clear=False):
        self.inputs.append((text, clear))
        return True


def _raw_state(text="Continue"):
    return {
        "a11y_tree": [
            {
                "resourceId": "com.example:id/continue",
                "className": "android.widget.Button",
                "text": text,
                "clickable": True,
                "enabled": True,
                "bounds": "10,20,110,60",
            }
        ],
        "phone_state": {"package": "com.example", "activity": ".MainActivity"},
        "screen_width": 400,
        "screen_height": 800,
    }


def _tap(pre_state):
    return {
        "action_type": "tap",
        "x": 60,
        "y": 40,
        "pre_state": pre_state,
    }


def _macro(actions):
    return {
        "macro_schema_version": "2.0",
        "description": "continue",
        "actions": actions,
    }


def test_recovery_resumes_same_step_and_does_not_restart_verified_steps(tmp_path):
    expected = normalize_ui_state(_raw_state())
    popup = normalize_ui_state(_raw_state("Close ad"))
    driver = FakeDriver([expected, popup, popup])
    calls = []

    async def recover(**context):
        calls.append(context)
        driver.states = [expected]
        return RecoveryOutcome.recovered_to_same_step(
            reason="popup closed", agent_actions=1, llm_calls=1
        )

    player = MacroPlayer(
        delay_between_actions=0,
        on_mismatch="recover",
        state_timeout=0.01,
        state_poll_interval=0,
        recovery_runner=recover,
        journal_path=str(tmp_path / "journal.jsonl"),
    )
    player.driver = driver

    result = asyncio.run(
        player.replay_macro_result(
            _macro([_tap(expected), _tap(expected)]),
        )
    )

    assert result.status == "RECOVERED_AND_RESUMED"
    assert result.llm_calls == 1
    assert result.recovery_attempts == 1
    assert driver.taps == [(60, 40), (60, 40)]
    assert len(calls) == 1
    assert calls[0]["failed_step_index"] == 1
    records = [json.loads(line) for line in (tmp_path / "journal.jsonl").read_text().splitlines()]
    assert any(record["event"] == "recovery" for record in records)
    assert any(record.get("status") == "VERIFIED" for record in records)


def test_failed_recovery_is_blocked_and_does_not_continue():
    expected = normalize_ui_state(_raw_state())
    popup = normalize_ui_state(_raw_state("Close ad"))
    driver = FakeDriver([popup, popup])

    async def recover(**context):
        return RecoveryOutcome.unrecoverable("captcha requires a human")

    player = MacroPlayer(
        delay_between_actions=0,
        on_mismatch="recover",
        state_timeout=0.01,
        state_poll_interval=0,
        recovery_runner=recover,
    )
    player.driver = driver

    result = asyncio.run(player.replay_macro_result(_macro([_tap(expected)])))

    assert result.status == "BLOCKED"
    assert result.steps_completed == 0
    assert driver.taps == []


def test_failed_action_is_fail_fast_and_does_not_execute_following_action():
    expected = normalize_ui_state(_raw_state())
    driver = FakeDriver([expected], fail_taps=True)
    player = MacroPlayer(delay_between_actions=0)
    player.driver = driver

    result = asyncio.run(
        player.replay_macro_result(_macro([_tap(expected), _tap(expected)]))
    )

    assert result.status == "FAILED"
    assert result.steps_completed == 0
    assert driver.taps == []


def test_macro_tap_selector_refuses_ambiguous_target_and_taps_unique_target():
    expected = normalize_ui_state(_raw_state())
    driver = FakeDriver([expected])
    player = MacroPlayer(delay_between_actions=0)
    player.driver = driver

    success = asyncio.run(
        player.replay_action(
            {
                "action_type": "tap_selector",
                "selector": {"resource_id": "com.example:id/continue"},
            },
            current_state=expected,
        )
    )

    assert success
    assert driver.taps == [(60, 40)]


def test_scoped_recovery_agent_backs_out_of_account_overlay_without_llm():
    class BackDriver(FakeDriver):
        def __init__(self):
            super().__init__([_raw_state()])
            self.buttons = []

        async def press_button(self, button):
            self.buttons.append(button)

    driver = BackDriver()
    player = MacroPlayer(delay_between_actions=0)
    player.driver = driver
    agent = ScopedRecoveryAgent(player)
    state = {"nodes": [{"text": "在线开户", "class": "TextView"}, {"text": "已有交易账户？直接登录", "class": "TextView"}]}

    outcome = asyncio.run(
        agent(
            current_state=state,
            divergence={"reason": "OVERLAY_DETECTED"},
            failed_step_index=0,
            recovery_budget={"max_actions": 5, "max_seconds": 10},
        )
    )

    assert outcome.status == "RECOVERED_TO_SAME_STEP"
    assert outcome.llm_calls == 0
    assert driver.buttons == ["back"]


def test_scoped_recovery_agent_closes_a_known_overlay_without_llm():
    driver = FakeDriver([_raw_state()])
    player = MacroPlayer(delay_between_actions=0)
    player.driver = driver
    agent = ScopedRecoveryAgent(player)
    state = {
        "screen": {"width": 1080, "height": 2400},
        "nodes": [
            {"resource_id": "pop-layer-ad", "class": "View", "bounds": {"left": 100, "top": 500, "right": 900, "bottom": 1700}},
            {"resource_id": "", "text": "pop页面属性", "class": "TextView", "bounds": {"left": 0, "top": 0, "right": 1080, "bottom": 2400}},
            {"resource_id": "", "class": "View", "bounds": {"left": 500, "top": 1760, "right": 580, "bottom": 1840, "center_x": 540, "center_y": 1800}},
        ],
    }

    outcome = asyncio.run(
        agent(
            current_state=state,
            divergence={"reason": "OVERLAY_DETECTED"},
            failed_step_index=0,
            recovery_budget={"max_actions": 5, "max_seconds": 10},
        )
    )

    assert outcome.status == "RECOVERED_TO_SAME_STEP"
    assert outcome.llm_calls == 0
    assert driver.taps == [(540, 1800)]


def test_scoped_recovery_agent_only_taps_a_unique_selector():
    expected = normalize_ui_state(_raw_state())
    driver = FakeDriver([expected])
    player = MacroPlayer(delay_between_actions=0)
    player.driver = driver
    agent = ScopedRecoveryAgent(player)

    class FakeLLM:
        def __init__(self):
            self.responses = [
                {
                    "action": "tap",
                    "selector": {"resource_id": "com.example:id/continue"},
                },
                {"action": "done"},
            ]

        async def achat(self, messages):
            return SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(self.responses.pop(0)))
            )

    agent.llm = FakeLLM()
    outcome = asyncio.run(
        agent(
            current_state=expected,
            divergence={"reason": "OVERLAY_DETECTED"},
            failed_step_index=0,
            recovery_budget={"max_actions": 2, "max_seconds": 1},
        )
    )

    assert outcome.status == "RECOVERED_TO_SAME_STEP"
    assert driver.taps == [(60, 40)]


def test_high_risk_action_failure_is_unknown_outcome_and_not_retried():
    expected = normalize_ui_state(_raw_state())
    driver = FakeDriver([expected], fail_taps=True)
    player = MacroPlayer(delay_between_actions=0)
    player.driver = driver
    action = _tap(expected)
    action["risk"] = "high"

    result = asyncio.run(player.replay_macro_result(_macro([action])))

    assert result.status == "UNKNOWN_OUTCOME"
    assert result.steps_completed == 0


def test_normal_replay_reports_zero_llm_calls_and_does_not_load_model(monkeypatch):
    expected = normalize_ui_state(_raw_state())
    monkeypatch.setattr(
        ScopedRecoveryAgent,
        "_load_llm",
        lambda self: (_ for _ in ()).throw(AssertionError("model must not load")),
    )
    driver = FakeDriver([expected])
    player = MacroPlayer(delay_between_actions=0, on_mismatch="recover")
    player.driver = driver

    result = asyncio.run(player.replay_macro_result(_macro([_tap(expected)])))

    assert result.status == "MACRO_SUCCESS"
    assert result.llm_calls == 0
