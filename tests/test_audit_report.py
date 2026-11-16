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
    assert row["notes"] == []
    assert row["evidence"]["interruption"] == []
    output = generate_audit_report([row], tmp_path / "summary.html")
    assert output.exists()
    assert "Example Broker" in output.read_text()
    assert "无异常记录" in output.read_text()
    assert (tmp_path / "summary.json").exists()


def test_audit_report_keeps_only_abnormal_evidence(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"run_id": "r2", "workflow_id": "audit", "parameters": {"broker_name": "Example Broker"}}))
    (run / "result.json").write_text(json.dumps({"status": "MACRO_SUCCESS"}))
    events = [
        {"event": "broker_session", "selected": True},
        {"event": "order_status_verification", "phase": "route", "verified": True, "observed_statuses": ["KSGT"]},
        {"event": "money_verification", "label": "pre", "verified": True, "calculated_value": 10, "target_value": 10, "difference": 0},
        {"event": "money_verification", "label": "post", "verified": False, "calculated_value": 9, "target_value": 10, "difference": -1},
        {"event": "order_status_verification", "phase": "pending", "verified": False, "observed_statuses": ["未知状态"]},
        {"event": "order_status_verification", "phase": "cancelled", "verified": True},
    ]
    (run / "journal.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")

    row = build_audit_row(run)
    assert len(row["notes"]) == 2
    assert any("post" in note and "差值=-1" in note for note in row["notes"])
    assert any("下单状态：失败" in note and "未知状态" in note for note in row["notes"])
    assert not any("pre" in note for note in row["notes"])


def test_audit_report_groups_embedded_evidence_screenshots_by_broker(tmp_path):
    run = tmp_path / "run"
    (run / "artifacts" / "screenshots").mkdir(parents=True)
    (run / "artifacts" / "screenshots" / "funds.png").write_bytes(b"png")
    (run / "manifest.json").write_text(json.dumps({"run_id": "r3", "workflow_id": "audit", "parameters": {"broker_name": "Example Broker"}}))
    (run / "result.json").write_text(json.dumps({"status": "MACRO_SUCCESS"}))
    events = [
        {"event": "broker_session", "selected": True},
        {"event": "order_status_verification", "phase": "route", "verified": True, "observed_statuses": ["KSGT"]},
        {"event": "money_verification", "verified": True},
        {"event": "order_status_verification", "phase": "pending", "verified": True},
        {"event": "order_status_verification", "phase": "cancelled", "verified": True},
        {"event": "step", "index": 4, "action": {"evidence_role": "funds_pre"}},
        {"event": "observation", "index": 4, "phase": "post", "screenshot_path": "artifacts/screenshots/funds.png"},
    ]
    (run / "journal.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")

    row = build_audit_row(run)
    output = generate_audit_report([row], tmp_path / "summary.html")
    content = output.read_text()
    assert "关键截图证据" in content
    assert "资金查询（下单前）" in content
    assert "data:image/png;base64" in content


def test_audit_report_shows_interruption_screenshot_only_for_failed_run(tmp_path):
    run = tmp_path / "run"
    (run / "artifacts" / "screenshots").mkdir(parents=True)
    (run / "artifacts" / "screenshots" / "interrupted.png").write_bytes(b"png")
    (run / "manifest.json").write_text(json.dumps({"run_id": "r4", "workflow_id": "audit", "parameters": {"broker_name": "Example Broker"}}))
    (run / "result.json").write_text(json.dumps({"status": "UNKNOWN_OUTCOME"}))
    events = [{"event": "interruption", "status": "UNKNOWN_OUTCOME", "screenshot_path": "artifacts/screenshots/interrupted.png"}]
    (run / "journal.jsonl").write_text(json.dumps(events[0]) + "\n")

    row = build_audit_row(run)
    output = generate_audit_report([row], tmp_path / "summary.html")
    content = output.read_text()
    assert row["evidence"]["interruption"][0]["label"] == "中断时截图"
    assert "中断时截图" in content


def test_audit_report_infers_unknown_after_high_risk_action(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"run_id": "r5", "workflow_id": "audit", "parameters": {"broker_name": "Example Broker"}}))
    (run / "result.json").write_text(json.dumps({"status": "FAILED"}))
    events = [
        {"event": "step", "action_type": "tap_selector", "status": "VERIFIED", "action": {"risk": "high"}},
        {"event": "order_status_verification", "phase": "pending", "verified": False},
    ]
    (run / "journal.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")

    row = build_audit_row(run)
    assert row["conclusion"] == "未知"
    assert any("副作用结果：未知" in note for note in row["notes"])
