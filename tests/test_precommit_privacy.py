import importlib.util
from pathlib import Path


def _checker():
    path = Path(__file__).parents[1] / "scripts" / "check_staged_privacy.py"
    spec = importlib.util.spec_from_file_location("staged_privacy", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_example_workflow_path_is_allowed():
    checker = _checker()
    assert checker.check_path("workflows/examples/demo/workflow.json") == []


def test_private_workflow_path_is_rejected():
    checker = _checker()
    assert checker.check_path("workflows/private/workflow.json")


def test_private_workflow_marker_is_rejected_even_in_example():
    checker = _checker()
    private_app = "同" + "花顺"
    stock_code = "300" + "033"
    assert checker.check_text("docs/example.md", private_app + " " + stock_code)


def test_placeholders_are_allowed_but_real_credentials_are_rejected():
    checker = _checker()
    assert checker.check_text("config.yaml", 'api_key: "your-api-key"') == []
    live_value = "live-" + "value-12345678"
    assert checker.check_text("config.yaml", 'api_key: "' + live_value + '"')


def test_local_paths_and_device_serials_are_rejected():
    checker = _checker()
    local_path = "/" + "Users/alice/project"
    serial = "emulator-" + "5554"
    violations = checker.check_text(
        "notes.md", local_path + " on " + serial
    )
    assert len(violations) == 2
