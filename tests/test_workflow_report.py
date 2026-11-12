import json

from mobilerun.workflow.report import generate_report


def test_generate_report_renders_result_and_journal_timeline(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "workflow_id": "settings",
                "workflow_version": 2,
                "device": "emulator-5554",
            }
        )
    )
    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "status": "MACRO_SUCCESS",
                "steps_completed": 1,
                "total_steps": 1,
                "recovery_attempts": 0,
            }
        )
    )
    (run_dir / "journal.jsonl").write_text(
        json.dumps(
            {
                "event": "step",
                "step": 1,
                "status": "VERIFIED",
                "action_type": "tap",
            }
        )
        + "\n"
    )

    output = generate_report(run_dir, run_dir / "report.html")

    report = output.read_text()
    assert "MACRO_SUCCESS" in report
    assert "settings v2" in report
    assert "VERIFIED" in report
    assert "tap" in report
