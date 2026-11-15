import json

from mobilerun.workflow.audit_report import build_audit_row, generate_audit_report


def test_audit_report_maps_journal_events_to_summary(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"run_id": "r1", "workflow_id": "audit", "parameters": {"broker_name": "Example Broker"}}))
    (run / "result.json").write_text(json.dumps({"status": "MACRO_SUCCESS"}))
    events = [
        {"event": "broker_session", "selected": True},
        {"event": "order_status_verification", "phase": "route", "verified": True, "observed_statuses": ["KSGT"]},
        {"event": "money_verification", "label": "funds", "verified": True, "calculated_value": 10, "target_value": 10, "difference": 0},
        {"event": "order_status_verification", "phase": "pending", "verified": True},
        {"event": "order_status_verification", "phase": "cancelled", "verified": True},
    ]
    (run / "journal.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")

    row = build_audit_row(run)
    assert row["broker"] == "Example Broker"
    assert row["conclusion"] == "PASS"
    output = generate_audit_report([row], tmp_path / "summary.html")
    assert output.exists()
    assert "Example Broker" in output.read_text()
    assert (tmp_path / "summary.json").exists()
