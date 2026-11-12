"""
Macro Replay Module - Replay recorded UI automation sequences.

This module provides functionality to load and replay macro JSON files
that were generated during MobileAgent trajectory recording.
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from mobilerun_core_local.driver.android import AndroidDriver

from mobilerun.agent.utils.trajectory import Trajectory
from mobilerun.macro.contracts import RecoveryOutcome, RunResult
from mobilerun.macro.handoff import run_agent_handoff
from mobilerun.macro.journal import RunJournal
from mobilerun.macro.matcher import StateMatchResult, compare_states
from mobilerun.macro.recovery_agent import ScopedRecoveryAgent
from mobilerun.macro.state import (
    MACRO_SCHEMA_VERSION,
    UNSUPPORTED_SCHEMA_MESSAGE,
    normalize_ui_state,
)
from mobilerun.tools.filters import DetailedFilter
from mobilerun.tools.formatters import IndexedFormatter
from mobilerun.tools.ui.provider import AndroidStateProvider

logger = logging.getLogger("mobilerun-macro")

# Reverse map for legacy key_press macro entries
_KEYCODE_TO_BUTTON = {4: "back", 3: "home", 66: "enter"}


class MacroPlayer:
    """
    A class for loading and replaying Mobilerun macro sequences.

    This player can execute recorded UI actions (taps, swipes, text input, key presses)
    on Android devices using AndroidDriver.
    """

    def __init__(
        self,
        device_serial: str = None,
        delay_between_actions: float = 1.0,
        on_mismatch: str = "stop",
        state_timeout: float = 5.0,
        state_threshold: float = 0.85,
        state_poll_interval: float = 0.5,
        handoff_runner=None,
        recovery_runner=None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        config_path: Optional[str] = None,
        journal_path: Optional[str] = None,
        max_recoveries: int = 1,
        max_recovery_actions: int = 5,
        max_recovery_seconds: float = 45.0,
    ):
        """
        Initialize the MacroPlayer.

        Args:
            device_serial: Serial number of the target device. If None, uses ANDROID_SERIAL or the only connected device.
            delay_between_actions: Delay in seconds between each action (default: 1.0s)
        """
        self.device_serial = device_serial
        self.delay_between_actions = delay_between_actions
        self.on_mismatch = on_mismatch
        self.state_timeout = state_timeout
        self.state_threshold = state_threshold
        self.state_poll_interval = state_poll_interval
        self.handoff_runner = handoff_runner or run_agent_handoff
        self.recovery_runner = recovery_runner
        if self.recovery_runner is None and on_mismatch == "recover":
            self.recovery_runner = ScopedRecoveryAgent(self)
        self.provider = provider
        self.model = model
        self.config_path = config_path
        self.max_recoveries = max(0, max_recoveries)
        self.max_recovery_actions = max(0, max_recovery_actions)
        self.max_recovery_seconds = max(0.0, max_recovery_seconds)
        self.journal = RunJournal(journal_path)
        self.last_divergence: Optional[Dict[str, Any]] = None
        self.state_provider = None
        self._auto_state_provider = False
        self.driver: AndroidDriver | None = None
        self.credential_manager = None
        self._credential_load_error: Optional[str] = None

    async def _initialize_driver(self) -> AndroidDriver:
        """Initialize AndroidDriver for the target device."""
        if self.driver is None:
            self.driver = AndroidDriver(serial=self.device_serial)
            await self.driver.connect()
            logger.info(f"🤖 Initialized driver for device: {self.device_serial}")
        return self.driver

    def load_macro_from_file(self, macro_file_path: str) -> Dict[str, Any]:
        """
        Load macro data from a JSON file.

        Args:
            macro_file_path: Path to the macro JSON file

        Returns:
            Dictionary containing the macro data
        """
        return Trajectory.load_macro_sequence(macro_file_path)

    def load_macro_from_folder(self, trajectory_folder: str) -> Dict[str, Any]:
        """
        Load macro data from a trajectory folder.

        Args:
            trajectory_folder: Path to the trajectory folder containing macro.json

        Returns:
            Dictionary containing the macro data
        """
        return Trajectory.load_macro_sequence(trajectory_folder)

    def _load_credential_manager(self):
        if self.credential_manager is not None:
            return self.credential_manager

        from mobilerun.config_manager.loader import ConfigLoader
        from mobilerun.credential_manager import FileCredentialManager

        config_path = self.config_path
        if config_path is None:
            user_config_path = ConfigLoader.get_user_config_path()
            if not user_config_path.exists():
                self._credential_load_error = "no Mobilerun config file was found"
                return None
            config_path = str(user_config_path)

        try:
            config = ConfigLoader.load(config_path)
            credential_manager = FileCredentialManager(config.credentials)
        except Exception as e:
            self._credential_load_error = str(e)
            logger.debug("Failed to load credentials for macro replay: %s", e)
            return None

        if not credential_manager.secrets:
            self._credential_load_error = "credentials are disabled or empty"
            return None

        self.credential_manager = credential_manager
        self._credential_load_error = None
        return self.credential_manager

    async def get_current_state_snapshot(self) -> Dict[str, Any]:
        driver = await self._initialize_driver()
        if self.state_provider is None and isinstance(driver, AndroidDriver):
            self.state_provider = AndroidStateProvider(
                driver,
                tree_filter=DetailedFilter(),
                tree_formatter=IndexedFormatter(),
                use_normalized=False,
            )
            self._auto_state_provider = True
        if self.state_provider is not None:
            try:
                return normalize_ui_state(await self.state_provider.get_state())
            except Exception as e:
                logger.debug("Falling back to raw driver state: %s", e)
        try:
            raw_state = await driver.get_ui_tree()
            return normalize_ui_state(raw_state)
        except Exception as e:
            logger.debug("Falling back to file-based UI dump: %s", e)
            return normalize_ui_state(await self._get_file_based_ui_state(driver))

    async def _get_file_based_ui_state(self, driver: AndroidDriver) -> Dict[str, Any]:
        """Read an Android UI dump through a file when /dev/tty is unavailable."""
        device = getattr(driver, "device", None)
        if device is None:
            raise RuntimeError("Android driver does not expose an ADB device")
        path = "/sdcard/mobilerun_macro_window.xml"
        await device.shell(f"uiautomator dump {path}")
        raw_xml = await device.shell(f"cat {path}")
        start = raw_xml.find("<?xml")
        end = raw_xml.find("</hierarchy>", start)
        if start < 0 or end < 0:
            raise ValueError("file-based UI dump did not contain XML")
        root = ET.fromstring(raw_xml[start : end + len("</hierarchy>")])

        def convert(element):
            attrs = element.attrib
            node = {
                "resourceId": attrs.get("resource-id", ""),
                "className": attrs.get("class", ""),
                "text": attrs.get("text", ""),
                "contentDescription": attrs.get("content-desc", ""),
                "clickable": attrs.get("clickable", "false"),
                "enabled": attrs.get("enabled", "true"),
                "focused": attrs.get("focused", "false"),
                "bounds": attrs.get("bounds", ""),
                "children": [convert(child) for child in element],
            }
            return node

        children = [convert(child) for child in root]
        package = next(
            (node.attrib.get("package") for node in root.iter() if node.attrib.get("package")),
            None,
        )
        return {
            "a11y_tree": children,
            "phone_state": {"packageName": package},
        }

    async def wait_for_pre_state(
        self, pre_state: Optional[Dict[str, Any]], step_number: int
    ) -> tuple[bool, Optional[Dict[str, Any]], Optional[StateMatchResult]]:
        if not pre_state:
            return True, None, None

        deadline = time.monotonic() + self.state_timeout
        last_state = None
        last_result = None

        while True:
            current_state = await self.get_current_state_snapshot()
            result = compare_states(pre_state, current_state, self.state_threshold)
            if result.matches:
                return True, current_state, result

            last_state = current_state
            last_result = result
            if time.monotonic() >= deadline:
                logger.error(
                    "State mismatch before step %s: %s", step_number, result.reason
                )
                return False, last_state, last_result

            await asyncio.sleep(self.state_poll_interval)

    async def replay_action(
        self, action: Dict[str, Any], current_state: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Replay a single action.

        Args:
            action: Action dictionary containing type and parameters

        Returns:
            True if action was executed successfully, False otherwise
        """
        driver = await self._initialize_driver()
        action_type = action.get("action_type", action.get("type", "unknown"))

        try:
            if action_type == "start_app":
                package = action.get("package")
                activity = action.get("activity", None)
                if package and getattr(driver, "device", None) is not None:
                    # ``monkey`` reliably starts apps whose launcher activity
                    # has an intermediate splash screen; it also avoids
                    # resuming a stale transaction page between workflow runs.
                    await driver.device.shell(f"am force-stop {package}")
                    result = await driver.device.shell(f"monkey -p {package} 1")
                else:
                    result = await driver.start_app(package, activity)
                if isinstance(result, str) and result.lower().startswith("failed"):
                    return False
                await asyncio.sleep(5.0)
                return result is not False

            elif action_type == "tap_selector":
                selector = action.get("selector") or {}
                state = current_state or await self.get_current_state_snapshot()
                matches = [
                    node
                    for node in state.get("nodes", [])
                    if all(node.get(key) == value for key, value in selector.items())
                ]
                if len(matches) != 1:
                    logger.error(
                        "❌ Selector matched %s nodes; refusing ambiguous tap: %s",
                        len(matches),
                        selector,
                    )
                    return False
                bounds = matches[0].get("bounds") or {}
                if "center_x" not in bounds or "center_y" not in bounds:
                    return False
                logger.info(
                    "🫰 Tapping selector %s at (%s, %s)",
                    selector,
                    bounds["center_x"],
                    bounds["center_y"],
                )
                result = await driver.tap(bounds["center_x"], bounds["center_y"])
                return result is not False

            elif action_type == "tap":
                x = action.get("x", 0)
                y = action.get("y", 0)
                logger.info(f"🫰 Tapping at ({x}, {y})")
                result = await driver.tap(x, y)
                return result is not False

            elif action_type == "swipe":
                start_x = action.get("start_x", 0)
                start_y = action.get("start_y", 0)
                end_x = action.get("end_x", 0)
                end_y = action.get("end_y", 0)
                duration_ms = action.get("duration_ms", 300)

                logger.info(
                    f"👆 Swiping from ({start_x}, {start_y}) to ({end_x}, {end_y}) in {duration_ms}ms"
                )
                await driver.swipe(start_x, start_y, end_x, end_y, duration_ms)
                # Additional wait after swipe for UI to settle
                await asyncio.sleep(2)
                return True

            elif action_type == "drag":
                start_x = action.get("start_x", 0)
                start_y = action.get("start_y", 0)
                end_x = action.get("end_x", 0)
                end_y = action.get("end_y", 0)
                duration = action.get(
                    "duration", action.get("duration_ms", 300) / 1000.0
                )

                logger.info(
                    f"👆 Dragging from ({start_x}, {start_y}) to ({end_x}, {end_y})"
                )
                await driver.drag(start_x, start_y, end_x, end_y, duration)
                return True

            elif action_type == "input_text":
                text = action.get("text", "")
                clear = action.get("clear", False)
                logger.info(f"⌨️  Inputting text: '{text}'")
                result = await driver.input_text(text, clear)
                return result is not False

            elif action_type == "type_secret":
                secret_id = action.get("secret_id")
                clear = action.get("clear", False)
                if not secret_id:
                    logger.error("❌ Secret macro action is missing secret_id")
                    return False

                credential_manager = self._load_credential_manager()
                if credential_manager is None:
                    detail = (
                        f": {self._credential_load_error}"
                        if self._credential_load_error
                        else ""
                    )
                    logger.error(
                        "❌ Cannot replay secret '%s'; no credentials are available%s",
                        secret_id,
                        detail,
                    )
                    return False

                try:
                    secret_value = await credential_manager.resolve_key(secret_id)
                except Exception as e:
                    logger.error("❌ Secret '%s' is not available: %s", secret_id, e)
                    return False

                logger.info("⌨️  Inputting secret: '%s'", secret_id)
                result = await driver.input_text(secret_value, clear)
                return result is not False

            elif action_type == "key_press":
                keycode = action.get("keycode", 0)
                button = _KEYCODE_TO_BUTTON.get(keycode)
                if button:
                    logger.info(f"🔘 Pressing button: {button}")
                    await driver.press_button(button)
                else:
                    logger.warning(f"⚠️  Unknown keycode {keycode}")
                    return False
                return True

            elif action_type == "button_press":
                button = action.get("button", "")
                logger.info(f"🔘 Pressing button: {button}")
                await driver.press_button(button)
                return True

            elif action_type == "back":
                logger.info("⬅️  Pressing back button")
                await driver.press_button("back")
                return True

            elif action_type == "wait":
                duration = action.get("duration", 1.0)
                logger.info(f"⏳ Waiting for {duration} seconds")
                await asyncio.sleep(duration)
                return True

            else:
                logger.warning(f"⚠️  Unknown action type: {action_type}")
                return False

        except Exception as e:
            logger.error(f"❌ Error executing action {action_type}: {e}")
            return False

    async def replay_macro_result(
        self,
        macro_data: Dict[str, Any],
        start_from_step: int = 0,
        max_steps: Optional[int] = None,
    ) -> RunResult:
        """Replay a macro and return an auditable structured result."""
        if not macro_data or "actions" not in macro_data:
            logger.error("❌ Invalid macro data - no actions found")
            return RunResult(status="FAILED", failure_reason="no actions found")
        if macro_data.get("macro_schema_version") != MACRO_SCHEMA_VERSION:
            raise ValueError(UNSUPPORTED_SCHEMA_MESSAGE)

        all_actions = macro_data["actions"]
        description = macro_data.get("description", "Unknown macro")
        total_actions = len(all_actions)
        actions = all_actions[start_from_step:]
        if max_steps is not None:
            actions = actions[:max_steps]

        result = RunResult(
            status="MACRO_SUCCESS",
            total_steps=len(actions),
            last_verified_checkpoint=start_from_step - 1,
            journal_path=str(self.journal.path) if self.journal.path else None,
        )
        recovered = False
        recovery_attempts = 0

        logger.info(f"🎬 Starting macro replay: '{description}'")
        logger.info(f"📊 Total actions to execute: {len(actions)} / {total_actions}")

        for offset, action in enumerate(actions):
            step_index = start_from_step + offset
            step_number = step_index + 1
            action_type = action.get("action_type", action.get("type", "unknown"))
            self.journal.append(
                "step",
                index=step_index,
                step=step_number,
                status="PENDING",
                action_type=action_type,
            )

            while True:
                # Entry actions are responsible for establishing their own app
                # context; requiring the recorder's launcher snapshot here makes
                # replay depend on launcher layout, date widgets, and icons.
                if action_type in {"start_app", "wait"}:
                    # start_app establishes context; wait is deliberately a
                    # state-agnostic settling barrier. The next side-effecting
                    # action still performs the guarded precondition check.
                    current_state, match_result = None, None
                    state_matched = True
                else:
                    state_matched, current_state, match_result = await self.wait_for_pre_state(
                        action.get("pre_state"), step_number
                    )
                if state_matched:
                    break

                self.last_divergence = {
                    "step": step_number,
                    "step_index": step_index,
                    "action_type": action_type,
                    "reason": match_result.reason if match_result else "state mismatch",
                    "score": match_result.score if match_result else None,
                    "expected_pre_state": action.get("pre_state") or {},
                    "observed_state": current_state or {},
                    "last_verified_checkpoint": result.last_verified_checkpoint,
                    "remaining_actions": all_actions[step_index:],
                }
                self.journal.append("divergence", **self.last_divergence)

                if self.on_mismatch == "agent":
                    logger.warning("🤖 Handing off to agent after macro divergence")
                    fallback = await self.handoff_runner(
                        goal=description,
                        device_serial=self.device_serial,
                        provider=self.provider,
                        model=self.model,
                        config_path=self.config_path,
                        divergence=self.last_divergence,
                        current_state=current_state or {},
                        remaining_actions=all_actions[step_index:],
                    )
                    return RunResult(
                        status="FALLBACK_COMPLETED" if fallback else "BLOCKED",
                        total_steps=len(actions),
                        steps_completed=offset,
                        llm_calls=1,
                        recovery_attempts=1,
                        last_verified_checkpoint=result.last_verified_checkpoint,
                        failure_reason=None if fallback else "agent handoff failed",
                        journal_path=result.journal_path,
                    )

                if self.on_mismatch != "recover":
                    return self._failed_result(result, offset, self.last_divergence["reason"])
                if recovery_attempts >= self.max_recoveries:
                    return self._failed_result(result, offset, "recovery budget exhausted")
                if self.recovery_runner is None:
                    return self._failed_result(
                        result, offset, "no scoped recovery runner configured"
                    )

                recovery_attempts += 1
                result.recovery_attempts = recovery_attempts
                outcome = await self._run_recovery(
                    description=description,
                    divergence=self.last_divergence,
                    current_state=current_state or {},
                    remaining_actions=all_actions[step_index:],
                    failed_step_index=step_index,
                    failed_step_action=action,
                    last_verified_checkpoint=result.last_verified_checkpoint,
                    recovery_attempts=recovery_attempts,
                    recovery_budget={
                        "max_recoveries": self.max_recoveries,
                        "max_actions": self.max_recovery_actions,
                        "max_seconds": self.max_recovery_seconds,
                    },
                )
                result.llm_calls += outcome.llm_calls
                if outcome.agent_actions > self.max_recovery_actions:
                    return self._failed_result(
                        result, offset, "recovery action budget exceeded"
                    )
                self.journal.append(
                    "recovery",
                    step_index=step_index,
                    status=outcome.status,
                    reason=outcome.reason,
                    agent_actions=outcome.agent_actions,
                    llm_calls=outcome.llm_calls,
                    metadata=outcome.metadata,
                )
                if not outcome.recovered:
                    failure_status = (
                        "UNKNOWN_OUTCOME"
                        if outcome.status == "UNKNOWN_OUTCOME"
                        else "BLOCKED"
                    )
                    return self._failed_result(
                        result,
                        offset,
                        outcome.reason or outcome.status,
                        status=failure_status,
                    )
                if outcome.status == "RECOVERED_TO_CHECKPOINT" and (
                    outcome.checkpoint is None or outcome.checkpoint != step_index
                ):
                    return self._failed_result(
                        result,
                        offset,
                        "recovery may only resume at the failed step without an explicit verifier",
                    )
                recovered = True

            self.journal.append(
                "step",
                index=step_index,
                step=step_number,
                status="STARTED",
                action_type=action_type,
            )
            success = await self.replay_action(action, current_state=current_state)
            if not success:
                status = "UNKNOWN_OUTCOME" if self._is_high_risk(action) else "FAILED"
                self.journal.append(
                    "step",
                    index=step_index,
                    step=step_number,
                    status=status,
                    action_type=action_type,
                )
                return self._failed_result(
                    result,
                    offset,
                    f"{status.lower()}: action failed: {action_type}",
                    status=status,
                )

            post_state = action.get("post_state")
            if post_state:
                verified, observed, post_match = await self.wait_for_pre_state(
                    post_state, step_number
                )
                if not verified:
                    reason = post_match.reason if post_match else "postcondition failed"
                    self.journal.append(
                        "step",
                        index=step_index,
                        step=step_number,
                        status="FAILED",
                        action_type=action_type,
                        reason=reason,
                    )
                    return self._failed_result(
                        result,
                        offset,
                        reason,
                        status="UNKNOWN_OUTCOME" if self._is_high_risk(action) else "FAILED",
                    )

            result.steps_completed = offset + 1
            result.last_verified_checkpoint = step_index
            self.journal.append(
                "step",
                index=step_index,
                step=step_number,
                status="VERIFIED",
                action_type=action_type,
            )
            if offset < len(actions) - 1 and self.delay_between_actions:
                await asyncio.sleep(self.delay_between_actions)

        result.status = "RECOVERED_AND_RESUMED" if recovered else "MACRO_SUCCESS"
        result.recovery_attempts = recovery_attempts
        return result

    async def replay_macro(
        self,
        macro_data: Dict[str, Any],
        start_from_step: int = 0,
        max_steps: Optional[int] = None,
    ) -> bool:
        """Backward-compatible boolean wrapper around :meth:`replay_macro_result`."""
        return (
            await self.replay_macro_result(
                macro_data, start_from_step=start_from_step, max_steps=max_steps
            )
        ).success

    async def _run_recovery(self, **context: Any) -> RecoveryOutcome:
        try:
            if self.max_recovery_seconds <= 0:
                return RecoveryOutcome.unrecoverable("recovery time budget is zero")
            outcome = await asyncio.wait_for(
                self.recovery_runner(**context), timeout=self.max_recovery_seconds
            )
        except asyncio.TimeoutError:
            return RecoveryOutcome.unrecoverable("recovery time budget exhausted")
        if isinstance(outcome, RecoveryOutcome):
            return outcome
        if isinstance(outcome, dict):
            return RecoveryOutcome(**outcome)
        return RecoveryOutcome.unrecoverable(
            "recovery runner must return RecoveryOutcome"
        )

    @staticmethod
    def _is_high_risk(action: Dict[str, Any]) -> bool:
        if str(action.get("risk", "")).lower() == "high":
            return True
        action_type = action.get("action_type", action.get("type", ""))
        return action_type in {
            "send",
            "submit",
            "purchase",
            "pay",
            "delete",
            "authorize",
            "confirm",
        }

    @staticmethod
    def _failed_result(
        result: RunResult,
        offset: int,
        reason: str,
        *,
        status: Optional[str] = None,
    ) -> RunResult:
        result.status = status or (
            "BLOCKED" if "recovery" in reason or "human" in reason else "FAILED"
        )
        result.steps_completed = offset
        result.failure_reason = reason
        return result


# Utility functions for convenience


async def replay_macro_file_result(
    macro_file_path: str,
    device_serial: str = None,
    delay_between_actions: float = 1.0,
    start_from_step: int = 0,
    max_steps: Optional[int] = None,
    on_mismatch: str = "stop",
    state_timeout: float = 5.0,
    state_threshold: float = 0.85,
    recovery_runner=None,
) -> RunResult:
    """
    Convenience function to replay a macro from a file.

    Args:
        macro_file_path: Path to the macro JSON file
        device_serial: Target device serial (optional)
        delay_between_actions: Delay between actions in seconds
        start_from_step: Step to start from (0-based)
        max_steps: Maximum steps to execute

    Returns:
        Structured run result.
    """
    player = MacroPlayer(
        device_serial=device_serial,
        delay_between_actions=delay_between_actions,
        on_mismatch=on_mismatch,
        state_timeout=state_timeout,
        state_threshold=state_threshold,
        recovery_runner=recovery_runner,
    )

    try:
        macro_data = player.load_macro_from_file(macro_file_path)
        return await player.replay_macro_result(
            macro_data, start_from_step=start_from_step, max_steps=max_steps
        )
    except Exception as e:
        logger.error(f"❌ Error replaying macro file {macro_file_path}: {e}")
        return RunResult(status="FAILED", failure_reason=str(e))


async def replay_macro_file(
    macro_file_path: str,
    device_serial: str = None,
    delay_between_actions: float = 1.0,
    start_from_step: int = 0,
    max_steps: Optional[int] = None,
    on_mismatch: str = "stop",
    state_timeout: float = 5.0,
    state_threshold: float = 0.85,
) -> bool:
    """Backward-compatible boolean wrapper for file replay."""
    result = await replay_macro_file_result(
        macro_file_path,
        device_serial=device_serial,
        delay_between_actions=delay_between_actions,
        start_from_step=start_from_step,
        max_steps=max_steps,
        on_mismatch=on_mismatch,
        state_timeout=state_timeout,
        state_threshold=state_threshold,
    )
    return result.success


async def replay_macro_folder(
    trajectory_folder: str,
    device_serial: str = None,
    delay_between_actions: float = 1.0,
    start_from_step: int = 0,
    max_steps: Optional[int] = None,
    on_mismatch: str = "stop",
    state_timeout: float = 5.0,
    state_threshold: float = 0.85,
) -> bool:
    """
    Convenience function to replay a macro from a trajectory folder.

    Args:
        trajectory_folder: Path to the trajectory folder containing macro.json
        device_serial: Target device serial (optional)
        delay_between_actions: Delay between actions in seconds
        start_from_step: Step to start from (0-based)
        max_steps: Maximum steps to execute

    Returns:
        True if replay was successful, False otherwise
    """
    player = MacroPlayer(
        device_serial=device_serial,
        delay_between_actions=delay_between_actions,
        on_mismatch=on_mismatch,
        state_timeout=state_timeout,
        state_threshold=state_threshold,
    )

    try:
        macro_data = player.load_macro_from_folder(trajectory_folder)
        return await player.replay_macro(
            macro_data, start_from_step=start_from_step, max_steps=max_steps
        )
    except Exception as e:
        logger.error(f"❌ Error replaying macro folder {trajectory_folder}: {e}")
        return False
