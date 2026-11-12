import json

import pytest

from mobilerun.workflow.registry import WorkflowRegistry


def _write_macro(path):
    path.write_text(
        json.dumps(
            {
                "macro_schema_version": "2.0",
                "version": "2.0",
                "description": "Open settings",
                "actions": [
                    {
                        "action_type": "wait",
                        "duration": 0,
                        "pre_state": {"phone_state": {}, "nodes": []},
                    }
                ],
            }
        )
    )


def test_import_creates_reviewable_draft_sidecar(tmp_path):
    source = tmp_path / "macro.json"
    _write_macro(source)
    registry = WorkflowRegistry(tmp_path / "workflows")

    metadata = registry.import_macro(source, workflow_id="settings", name="Settings")

    assert metadata["status"] == "draft"
    assert metadata["version"] == 1
    stored = tmp_path / "workflows" / "settings" / "versions" / "0001"
    assert (stored / "macro.json").exists()
    assert (stored / "workflow.json").exists()


def test_validate_and_activate_require_valid_macro(tmp_path):
    source = tmp_path / "macro.json"
    _write_macro(source)
    registry = WorkflowRegistry(tmp_path / "workflows")
    registry.import_macro(source, workflow_id="settings", name="Settings")

    report = registry.validate("settings")
    assert report.valid

    activated = registry.activate("settings", version=1)
    assert activated["status"] == "active"
    assert json.loads(
        (tmp_path / "workflows" / "settings" / "active.json").read_text()
    )["version"] == 1


def test_parameter_substitution_is_literal_and_unknown_parameters_are_rejected():
    actions = [{"action_type": "input_text", "text": "{{query}}"}]
    rendered = WorkflowRegistry.render_actions(actions, {"query": "a+b"})

    assert rendered[0]["text"] == "a+b"
    with pytest.raises(ValueError, match="unknown workflow parameters"):
        WorkflowRegistry._resolve_params(
            {"query": {"required": True}}, {"query": "ok", "other": "x"}
        )


def test_validate_rejects_missing_pre_state(tmp_path):
    source = tmp_path / "macro.json"
    source.write_text(
        json.dumps(
            {
                "macro_schema_version": "2.0",
                "actions": [{"action_type": "tap", "x": 1, "y": 2}],
            }
        )
    )
    registry = WorkflowRegistry(tmp_path / "workflows")
    registry.import_macro(source, workflow_id="unsafe", name="Unsafe")

    report = registry.validate("unsafe")

    assert not report.valid
    assert any("pre_state" in error for error in report.errors)
    with pytest.raises(ValueError, match="validation"):
        registry.activate("unsafe", version=1)
