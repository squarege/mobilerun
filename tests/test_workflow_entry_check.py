import asyncio
import json
from pathlib import Path

from mobilerun.macro.replay import MacroPlayer
from mobilerun.workflow.registry import WorkflowRegistry


def test_entry_check_blocks_when_package_is_wrong(tmp_path, monkeypatch):
    source = tmp_path / "macro.json"
    source.write_text(json.dumps({"macro_schema_version": "2.0", "version": "2.0", "actions": [{"action_type": "wait", "duration": 0, "pre_state": {"phone_state": {"package": "x"}}}]}))
    registry = WorkflowRegistry(tmp_path / "workflows")
    registry.import_macro(source, workflow_id="entry")
    metadata = registry.inspect("entry", 1)
    path = Path(metadata["macro_path"]).with_name("workflow.json")
    value = json.loads(path.read_text())
    value["entry_check"] = {"type": "package", "package": "wrong.package"}
    path.write_text(json.dumps(value))

    async def fake_state(self):
        return {"phone_state": {"package": "actual.package"}, "nodes": []}

    monkeypatch.setattr(MacroPlayer, "get_current_state_snapshot", fake_state)
    result = asyncio.run(registry.run("entry", version=1, allow_draft=True))
    assert result.status == "BLOCKED"
    assert "wrong.package" in result.failure_reason
