import asyncio
import json
from pathlib import Path

from mobilerun.macro.contracts import RunResult
from mobilerun.macro.replay import MacroPlayer
from mobilerun.workflow.registry import WorkflowRegistry


def _import_workflow(tmp_path):
    source = tmp_path / "macro.json"
    source.write_text(
        json.dumps(
            {
                "macro_schema_version": "2.0",
                "version": "2.0",
                "actions": [
                    {"action_type": "wait", "duration": 0, "pre_state": {"nodes": []}}
                ],
            }
        )
    )
    registry = WorkflowRegistry(tmp_path / "workflows")
    registry.import_macro(source, workflow_id="validation")
    return registry


def test_draft_requires_allow_draft(tmp_path):
    registry = _import_workflow(tmp_path)

    result = asyncio.run(registry.run("validation", version=1))

    assert result.status == "BLOCKED"
    assert "allow_draft" in result.failure_reason


def test_allow_draft_runs_explicit_version_and_marks_manifest(tmp_path, monkeypatch):
    registry = _import_workflow(tmp_path)

    async def fake_replay(self, macro):
        return RunResult(status="MACRO_SUCCESS")

    monkeypatch.setattr(MacroPlayer, "replay_macro_result", fake_replay)
    result = asyncio.run(registry.run("validation", version=1, allow_draft=True))

    assert result.status == "MACRO_SUCCESS"
    manifest = json.loads(Path(result.details["manifest_path"]).read_text())
    assert manifest["draft_validation"] is True
