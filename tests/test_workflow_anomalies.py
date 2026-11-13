import json

import pytest

from mobilerun.workflow.anomalies import AnomalyError, AnomalyManager
from mobilerun.workflow.registry import WorkflowRegistry


def _write_workflow(root):
    registry = WorkflowRegistry(root / "workflows")
    source = root / "macro.json"
    source.write_text(
        json.dumps(
            {
                "macro_schema_version": "2.0",
                "version": "2.0",
                "description": "Open settings",
                "actions": [
                    {"action_type": "tap", "x": 10, "y": 20, "pre_state": {"nodes": [{"text": "Settings"}]}},
                    {"action_type": "wait", "duration": 1, "pre_state": {"nodes": []}},
                ],
            }
        )
    )
    registry.import_macro(source, workflow_id="settings", name="Settings")
    registry.activate("settings", version=1)
    return registry


def _write_run(root, name, status="FAILED", diverged=True, failure_reason="state mismatch"):
    run_dir = root / "workflows" / "settings" / "runs" / name
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": name,
        "workflow_id": "settings",
        "workflow_version": 1,
        "started_at": 100,
    }
    result = {
        "status": status,
        "success": status == "MACRO_SUCCESS",
        "steps_completed": 0 if status != "MACRO_SUCCESS" else 2,
        "total_steps": 2,
        "failure_reason": None if status == "MACRO_SUCCESS" else failure_reason,
        "details": {},
    }
    journal = []
    if diverged:
        journal.append(
            {
                "event": "divergence",
                "step_index": 0,
                "reason": "state mismatch",
                "state_path": "artifacts/states/divergence.json",
            }
        )
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "result.json").write_text(json.dumps(result))
    (run_dir / "journal.jsonl").write_text("".join(json.dumps(event) + "\n" for event in journal))
    return run_dir


def _manager(tmp_path):
    return AnomalyManager(tmp_path / "workflows", tmp_path / "runs" / "scans")


def test_scan_finds_failure_divergence_and_stable_ids(tmp_path):
    root = tmp_path
    _write_workflow(root)
    _write_run(root, "run-1")
    manager = _manager(root)

    first = manager.scan()
    second = manager.scan()

    assert first["anomaly_count"] >= 2
    assert [item["anomaly_id"] for item in first["anomalies"]] == [item["anomaly_id"] for item in second["anomalies"]]
    assert (tmp_path / "runs" / "scans" / "state.json").exists()
    assert (tmp_path / "runs" / "scans" / "index.jsonl").exists()
    assert any(anomaly["type"] == "DIVERGENCE" for anomaly in first["anomalies"])
    assert any(anomaly["type"] == "RUN_FAILURE" for anomaly in first["anomalies"])
    summary = next((tmp_path / "runs" / "scans").glob("*/summary.md"))
    assert "DIVERGENCE" in summary.read_text()


def test_scan_marks_repeated_failures_and_updates_status(tmp_path):
    root = tmp_path
    _write_workflow(root)
    _write_run(root, "run-1")
    _write_run(root, "run-2")
    manager = _manager(root)

    result = manager.scan()
    repeated = next(anomaly for anomaly in result["anomalies"] if anomaly["type"] == "REPEATED_FAILURE")
    updated = manager.update_status(repeated["anomaly_id"], "dismissed", note="known launcher variation")

    assert repeated["run_ids"] == ["run-1", "run-2"]
    assert updated["status"] == "dismissed"
    assert manager.list_anomalies("dismissed")[0]["anomaly_id"] == repeated["anomaly_id"]


def test_repair_creates_and_applies_whitelisted_plan_without_activation(tmp_path):
    root = tmp_path
    registry = _write_workflow(root)
    _write_run(root, "run-1")
    manager = _manager(root)
    scanned = manager.scan()
    divergence = next(anomaly for anomaly in scanned["anomalies"] if anomaly["type"] == "DIVERGENCE")

    plan = manager.repair(
        divergence["anomaly_id"],
        triage_runner=lambda anomaly, with_screenshots: {
            "classification": "DIVERGENCE",
            "root_cause": "temporary UI transition",
            "confidence": 0.8,
            "needs_human": False,
            "operations": [
                {"op": "insert_action", "step_index": 0, "action": {"action_type": "wait", "duration": 1.5}}
            ],
            "verification": "validate and explicit replay",
        },
    )
    assert plan["status"] == "pending_review"
    applied = manager.apply_plan(plan["plan_id"], registry)
    target = applied["draft"]

    assert target["version"] == 2
    assert target["status"] == "draft"
    assert target["repair_provenance"]["anomaly_id"] == divergence["anomaly_id"]
    target_macro = json.loads((root / "workflows" / "settings" / "versions" / "0002" / "macro.json").read_text())
    assert target_macro["actions"][0] == {"action_type": "wait", "duration": 1.5, "pre_state": {}}
    assert target_macro["actions"][1]["action_type"] == "tap"
    assert json.loads((root / "workflows" / "settings" / "active.json").read_text())["version"] == 1
    assert registry.validate("settings", version=2).valid
    assert applied["anomaly"]["status"] == "repair_planned"

    target_run = _write_run(root, "target-success", status="MACRO_SUCCESS", diverged=False)
    target_manifest = json.loads((target_run / "manifest.json").read_text())
    target_manifest["workflow_version"] = 2
    (target_run / "manifest.json").write_text(json.dumps(target_manifest))

    verified = manager.scan()
    repaired = next(anomaly for anomaly in verified["anomalies"] if anomaly["anomaly_id"] == divergence["anomaly_id"])
    assert repaired["status"] == "repaired"
    assert repaired["verified_by_run_id"] == "target-success"


def test_scan_flags_missing_runtime_files_instead_of_skipping(tmp_path):
    root = tmp_path
    _write_workflow(root)
    run_dir = root / "workflows" / "settings" / "runs" / "incomplete"
    run_dir.mkdir(parents=True)
    manager = _manager(root)

    result = manager.scan()

    assert result["anomaly_count"] == 1
    assert result["anomalies"][0]["type"] == "DATA_INTEGRITY"
    assert "missing files" in result["anomalies"][0]["reason"]


def test_repair_rejects_unsafe_operation(tmp_path):
    root = tmp_path
    _write_workflow(root)
    _write_run(root, "run-1")
    manager = _manager(root)
    scanned = manager.scan()
    anomaly = scanned["anomalies"][0]

    with pytest.raises(AnomalyError, match="unsupported repair operation"):
        manager.repair(
            anomaly["anomaly_id"],
            triage_runner=lambda anomaly, with_screenshots: {
                "operations": [{"op": "increase_recovery_budget", "step_index": 0}]
            },
        )
