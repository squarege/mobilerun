from mobilerun.macro.matcher import compare_states


def test_phone_only_guard_allows_volatile_ui_tree():
    result = compare_states(
        {"phone_state": {"package": "com.example"}},
        {"phone_state": {"package": "com.example"}, "nodes": [{"text": "dynamic"}]},
    )
    assert result.matches
