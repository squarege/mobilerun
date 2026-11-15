import json
import time

from click.testing import CliRunner

from mobilerun.macro.contracts import RunResult
from mobilerun.workflow.cli import workflow_cli
from mobilerun.workflow.registry import WorkflowRegistry


def _activate_workflow(root):
    macro = root / "macro.json"
    macro.write_text(
        json.dumps(
            {
                "macro_schema_version": "2.0",
                "version": "2.0",
                "actions": [{"action_type": "wait", "duration": 0, "pre_state": {"nodes": []}}],
            }
        )
    )
    registry = WorkflowRegistry(root / "workflows")
    registry.import_macro(macro, workflow_id="settings")
    registry.activate("settings", version=1)


def _write_failed_run(root, run_id="failed-run"):
    run_dir = root / "workflows" / "settings" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "workflow_id": "settings", "workflow_version": 1, "started_at": time.time()})
    )
    (run_dir / "result.json").write_text(
        json.dumps({"status": "FAILED", "success": False, "failure_reason": "state mismatch", "details": {}})
    )
    (run_dir / "journal.jsonl").write_text(
        json.dumps({"event": "divergence", "step_index": 0, "reason": "state mismatch"}) + "\n"
    )


def test_workflow_run_refreshes_lessons_automatically(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.chdir(root)
    _activate_workflow(root)
    _write_failed_run(root)
    run_dir = root / "workflows" / "settings" / "runs" / "successful-run"

    async def fake_run(*args, **kwargs):
        return RunResult(
            status="MACRO_SUCCESS",
            details={"run_id": run_dir.name, "run_dir": str(run_dir)},
        )

    monkeypatch.setattr(WorkflowRegistry, "run", fake_run)
    result = CliRunner().invoke(workflow_cli, ["--root", str(root / "workflows"), "run", "settings"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["details"]["active_lesson_count"] >= 1
    assert payload["details"]["lessons_path"] == "runs/scans/lessons.json"
    lessons = json.loads((root / "runs" / "scans" / "lessons.json").read_text())["lessons"]
    assert lessons[0]["status"] == "active"
