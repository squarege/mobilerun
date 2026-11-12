"""Versioned workflow sidecar registry built around native Macro v2 files."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from mobilerun.macro.contracts import RunResult
from mobilerun.macro.replay import MacroPlayer
from mobilerun.macro.state import MACRO_SCHEMA_VERSION

_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
_ALLOWED_ACTIONS = {
    "start_app",
    "tap",
    "tap_selector",
    "swipe",
    "drag",
    "input_text",
    "type_secret",
    "key_press",
    "button_press",
    "back",
    "wait",
}


@dataclass(frozen=True)
class ValidationReport:
    workflow_id: str
    version: int
    valid: bool
    errors: list[str]
    warnings: list[str]
    action_count: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WorkflowRegistry:
    def __init__(self, root: str | Path = "workflows"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _workflow_dir(self, workflow_id: str) -> Path:
        self._check_id(workflow_id)
        return self.root / workflow_id

    @staticmethod
    def _check_id(workflow_id: str) -> None:
        if not _SAFE_ID.fullmatch(workflow_id):
            raise ValueError(
                "workflow_id must contain only letters, numbers, '.', '_' or '-'."
            )

    def import_macro(
        self,
        source_macro: str | Path,
        *,
        workflow_id: str,
        name: Optional[str] = None,
        platform: str = "android",
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        source = Path(source_macro)
        if source.is_dir():
            source = source / "macro.json"
        if not source.exists():
            raise FileNotFoundError(source)
        macro = json.loads(source.read_text(encoding="utf-8"))
        if macro.get("macro_schema_version") != MACRO_SCHEMA_VERSION:
            raise ValueError("Only Macro schema v2 can be imported")

        workflow_dir = self._workflow_dir(workflow_id)
        version = self._next_version(workflow_dir)
        version_dir = workflow_dir / "versions" / f"{version:04d}"
        version_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source, version_dir / "macro.json")
        metadata = {
            "workflow_schema": 1,
            "id": workflow_id,
            "name": name or macro.get("description") or workflow_id,
            "source_macro": str(source),
            "platform": platform,
            "status": "draft",
            "version": version,
            "parameters": parameters or {},
            "entry_check": {},
            "completion_check": {},
            "policy": {
                "on_divergence": "stop",
                "max_recoveries": 1,
                "max_agent_actions_per_recovery": 5,
                "max_recovery_seconds": 45,
                "state_timeout": 60,
                "state_threshold": 0.85,
                "allow_side_effect_retry": False,
                "auto_publish_repair": False,
            },
            "created_at": time.time(),
        }
        self._write_json(version_dir / "workflow.json", metadata)
        return metadata

    def inspect(self, workflow_id: str, version: Optional[int] = None) -> Dict[str, Any]:
        version_dir = self._version_dir(workflow_id, version)
        metadata = self._read_json(version_dir / "workflow.json")
        metadata["macro_path"] = str(version_dir / "macro.json")
        return metadata

    def list(self) -> list[Dict[str, Any]]:
        workflows = []
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir():
                continue
            try:
                metadata = self.inspect(directory.name)
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue
            workflows.append(metadata)
        return workflows

    def validate(self, workflow_id: str, version: Optional[int] = None) -> ValidationReport:
        metadata = self.inspect(workflow_id, version)
        version = int(metadata["version"])
        macro_path = Path(metadata["macro_path"])
        errors: list[str] = []
        warnings: list[str] = []
        try:
            macro = json.loads(macro_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ValidationReport(workflow_id, version, False, [str(exc)], [], 0)

        completion_check = metadata.get("completion_check") or {}
        if completion_check and completion_check.get("type") not in {"ui_selector_exists", "package"}:
            errors.append(
                f"unsupported completion check: {completion_check.get('type')!r}"
            )

        actions = macro.get("actions")
        if not isinstance(actions, list) or not actions:
            errors.append("macro must contain a non-empty actions list")
            actions = []
        if macro.get("macro_schema_version") != MACRO_SCHEMA_VERSION:
            errors.append("macro schema version is not supported")

        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                errors.append(f"step {index}: action must be an object")
                continue
            action_type = action.get("action_type", action.get("type"))
            if action_type not in _ALLOWED_ACTIONS:
                errors.append(f"step {index}: unsupported action type {action_type!r}")
            if "pre_state" not in action:
                errors.append(f"step {index}: missing pre_state")
            elif not isinstance(action["pre_state"], dict):
                errors.append(f"step {index}: pre_state must be an object")
            elif not (
                action["pre_state"].get("nodes")
                or action["pre_state"].get("phone_state")
            ):
                warnings.append(f"step {index}: pre_state contains no matchable evidence")
            if action_type == "type_secret" and not action.get("secret_id"):
                errors.append(f"step {index}: type_secret requires secret_id")
            if action_type == "input_text" and "text" not in action:
                warnings.append(f"step {index}: input_text contains a fixed value")

        return ValidationReport(
            workflow_id=workflow_id,
            version=version,
            valid=not errors,
            errors=errors,
            warnings=warnings,
            action_count=len(actions),
        )

    def activate(self, workflow_id: str, *, version: int) -> Dict[str, Any]:
        report = self.validate(workflow_id, version)
        if not report.valid:
            raise ValueError("workflow validation failed: " + "; ".join(report.errors))
        workflow_dir = self._workflow_dir(workflow_id)
        version_dir = self._version_dir(workflow_id, version)
        metadata = self._read_json(version_dir / "workflow.json")
        metadata["status"] = "active"
        self._write_json(version_dir / "workflow.json", metadata)
        active_path = workflow_dir / "active.json"
        temporary = active_path.with_suffix(".tmp")
        self._write_json(temporary, {"workflow_id": workflow_id, "version": version})
        temporary.replace(active_path)
        return metadata

    async def run(
        self,
        workflow_id: str,
        *,
        version: Optional[int] = None,
        device_serial: Optional[str] = None,
        on_divergence: Optional[str] = None,
        recovery_runner=None,
        params: Optional[Dict[str, Any]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        config_path: Optional[str] = None,
    ) -> RunResult:
        metadata = self.inspect(workflow_id, version)
        if metadata.get("status") != "active":
            return RunResult(
                status="BLOCKED",
                failure_reason="workflow version is not active",
            )
        report = self.validate(workflow_id, int(metadata["version"]))
        if not report.valid:
            return RunResult(
                status="FAILED",
                total_steps=report.action_count,
                failure_reason="workflow validation failed: " + "; ".join(report.errors),
            )
        macro = json.loads(Path(metadata["macro_path"]).read_text(encoding="utf-8"))
        try:
            params = self._resolve_params(metadata.get("parameters") or {}, params or {})
        except ValueError as exc:
            return RunResult(status="FAILED", failure_reason=str(exc))
        macro["actions"] = self.render_actions(macro.get("actions", []), params)

        workflow_dir = self._workflow_dir(workflow_id)
        run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        run_dir = workflow_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        policy = metadata.get("policy") or {}
        player = MacroPlayer(
            device_serial=device_serial,
            on_mismatch=on_divergence or policy.get("on_divergence", "stop"),
            provider=provider,
            model=model,
            config_path=config_path,
            recovery_runner=recovery_runner,
            state_timeout=float(policy.get("state_timeout", 60)),
            state_threshold=float(policy.get("state_threshold", 0.85)),
            journal_path=str(run_dir / "journal.jsonl"),
            max_recoveries=int(policy.get("max_recoveries", 1)),
            max_recovery_actions=int(policy.get("max_agent_actions_per_recovery", 5)),
            max_recovery_seconds=float(policy.get("max_recovery_seconds", 45)),
        )
        result = await player.replay_macro_result(macro)
        if result.success and metadata.get("completion_check"):
            ok, reason = await self._check_completion(player, metadata["completion_check"])
            if not ok:
                result.status = "FAILED"
                result.failure_reason = reason
                result.details["completion_check"] = "failed"
        if result.status == "RECOVERED_AND_RESUMED":
            self._write_json(
                run_dir / "repair_proposal.json",
                {
                    "status": "pending_review",
                    "workflow_id": workflow_id,
                    "workflow_version": metadata["version"],
                    "divergence": player.last_divergence,
                    "run_result": result.as_dict(),
                    "journal": str(run_dir / "journal.jsonl"),
                    "auto_publish": False,
                },
            )
        self._write_json(run_dir / "result.json", result.as_dict())
        return result

    @staticmethod
    async def _check_completion(player: MacroPlayer, check: Dict[str, Any]) -> tuple[bool, str]:
        check_type = check.get("type")
        last_reason = "completion check did not match"
        for _ in range(20):
            state = await player.get_current_state_snapshot()
            if check_type == "ui_selector_exists":
                selector = check.get("selector") or {}
                matches = [
                    node
                    for node in state.get("nodes", [])
                    if all(node.get(key) == value for key, value in selector.items())
                ]
                if len(matches) == 1:
                    return True, ""
                last_reason = f"completion selector matched {len(matches)} nodes"
            elif check_type == "package":
                expected = check.get("package")
                observed = (state.get("phone_state") or {}).get("package")
                if observed == expected:
                    return True, ""
                last_reason = f"completion package expected {expected!r}, observed {observed!r}"
            else:
                return False, f"unsupported completion check: {check_type!r}"
            await asyncio.sleep(0.5)
        return False, last_reason

    @staticmethod
    def render_actions(actions: list[Dict[str, Any]], params: Dict[str, Any]) -> list[Dict[str, Any]]:
        """Safely substitute ``{{parameter}}`` placeholders without evaluating code."""
        def render(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: render(item) for key, item in value.items()}
            if isinstance(value, list):
                return [render(item) for item in value]
            if not isinstance(value, str):
                return value
            result = value
            for key, replacement in params.items():
                result = result.replace("{{" + key + "}}", str(replacement))
            return result

        return [render(action) for action in actions]

    @staticmethod
    def _resolve_params(
        schema: Dict[str, Any], supplied: Dict[str, Any]
    ) -> Dict[str, Any]:
        resolved = dict(supplied)
        for name, spec in schema.items():
            if isinstance(spec, dict):
                required = bool(spec.get("required", False))
                if name not in resolved and "default" in spec:
                    resolved[name] = spec["default"]
            else:
                required = False
            if required and name not in resolved:
                raise ValueError(f"missing required workflow parameter: {name}")
        unknown = set(resolved) - set(schema)
        if unknown and schema:
            raise ValueError("unknown workflow parameters: " + ", ".join(sorted(unknown)))
        return resolved

    def runs(self, workflow_id: str) -> list[Dict[str, Any]]:
        runs_dir = self._workflow_dir(workflow_id) / "runs"
        if not runs_dir.exists():
            return []
        results = []
        for result_path in sorted(runs_dir.glob("*/result.json")):
            try:
                results.append(self._read_json(result_path))
            except json.JSONDecodeError:
                continue
        return results

    def _version_dir(self, workflow_id: str, version: Optional[int]) -> Path:
        workflow_dir = self._workflow_dir(workflow_id)
        if version is None:
            active_path = workflow_dir / "active.json"
            if active_path.exists():
                version = int(self._read_json(active_path)["version"])
            else:
                versions = sorted((workflow_dir / "versions").glob("[0-9]*/"))
                if not versions:
                    raise FileNotFoundError(f"workflow {workflow_id!r} has no versions")
                version = int(versions[-1].name)
        version_dir = workflow_dir / "versions" / f"{int(version):04d}"
        if not version_dir.exists():
            raise FileNotFoundError(f"workflow {workflow_id!r} version {version} not found")
        return version_dir

    @staticmethod
    def _next_version(workflow_dir: Path) -> int:
        versions_dir = workflow_dir / "versions"
        if not versions_dir.exists():
            return 1
        versions = [int(path.name) for path in versions_dir.iterdir() if path.name.isdigit()]
        return max(versions, default=0) + 1

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, value: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
