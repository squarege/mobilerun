from mobilerun.agent.fast_agent.xml_parser import (
    ToolCallParseStatus,
    parse_tool_calls_detailed,
)
from mobilerun.agent.providers.registry import resolve_provider_variant
from mobilerun.agent.providers.setup_service import (
    SetupSelection,
    create_profile_for_variant,
)
from mobilerun.agent.utils.llm_picker import load_llm, normalize_provider_name
from mobilerun.config_manager.config_manager import LLMProfile

CUSTOM_BASE_URL = "http://hithink-oslm.myhexin.com/osllm"
CUSTOM_MODEL = "tb2b-v1-minimax-m25"


def test_minimax_dsml_variant_is_a_first_class_custom_provider() -> None:
    variant = resolve_provider_variant("minimax_dsml", "api_key")
    profile = create_profile_for_variant(
        variant,
        SetupSelection(
            family_id="minimax_dsml",
            variant_id=variant.id,
            auth_mode="api_key",
            model=CUSTOM_MODEL,
            api_key_source="env",
            base_url=CUSTOM_BASE_URL,
        ),
    )

    assert variant.runtime_provider_name == "MiniMaxDSML"
    assert profile.provider == "MiniMaxDSML"
    assert profile.provider_family == "minimax_dsml"
    assert profile.model == CUSTOM_MODEL
    assert profile.base_url == CUSTOM_BASE_URL


def test_minimax_dsml_loader_exposes_dsml_protocol() -> None:
    llm = load_llm(
        "MiniMaxDSML",
        model=CUSTOM_MODEL,
        api_key="test-key",
        base_url=CUSTOM_BASE_URL,
    )

    assert llm.tool_protocol == "dsml"
    assert llm.supports_dsml_tool_calls is True
    assert llm.metadata.model_name == CUSTOM_MODEL


def test_anthropic_compatible_profile_keeps_custom_model_and_url() -> None:
    variant = resolve_provider_variant("anthropic_like", "api_key")
    profile = create_profile_for_variant(
        variant,
        SetupSelection(
            family_id="anthropic_like",
            variant_id=variant.id,
            auth_mode="api_key",
            model=CUSTOM_MODEL,
            api_key_source="env",
            base_url=CUSTOM_BASE_URL,
        ),
    )

    assert profile.provider == "Anthropic"
    assert profile.provider_family == "anthropic_like"
    assert profile.model == CUSTOM_MODEL
    assert profile.base_url == CUSTOM_BASE_URL


def test_anthropic_compatible_profile_resolves_anthropic_key(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    profile = LLMProfile(
        provider="Anthropic",
        provider_family="anthropic_like",
        auth_mode="api_key",
        model=CUSTOM_MODEL,
        base_url=CUSTOM_BASE_URL,
        api_key_source="env",
    )

    kwargs = profile.to_load_llm_kwargs()

    assert kwargs["api_key"] == "test-key"
    assert kwargs["tool_protocol"] == "dsml"
    assert kwargs["base_url"] == CUSTOM_BASE_URL
    assert kwargs["model"] == CUSTOM_MODEL


def test_anthropic_compatible_loader_uses_custom_base_url() -> None:
    llm = load_llm(
        "AnthropicLike",
        model=CUSTOM_MODEL,
        api_key="test-key",
        base_url=CUSTOM_BASE_URL,
    )

    assert llm.model == CUSTOM_MODEL
    assert str(llm._client.base_url).rstrip("/") == CUSTOM_BASE_URL
    assert str(llm._aclient.base_url).rstrip("/") == CUSTOM_BASE_URL

    metadata = llm.metadata
    assert metadata.model_name == CUSTOM_MODEL
    assert metadata.context_window == 200_000
    assert metadata.is_function_calling_model is True


def test_anthropic_compatible_provider_parses_minimax_dsml_tool_markup() -> None:
    response = """I will open the app.
<function_calls>
<｜DSML｜invoke name="swipe">
<｜DSML｜parameter name="coordinate">[540, 1600]</｜DSML｜parameter>
<｜DSML｜parameter name="coordinate2">[540, 400]</｜DSML｜parameter>
<｜DSML｜parameter name="duration">0.5</｜DSML｜parameter>
</｜DSML｜invoke>
</｜DSML｜tool_calls>"""

    result = parse_tool_calls_detailed(
        response,
        {"coordinate": "list", "coordinate2": "list", "duration": "number"},
        allow_dsml=True,
    )

    assert result.status is ToolCallParseStatus.VALID
    assert len(result.calls) == 1
    assert result.calls[0].name == "swipe"
    assert result.calls[0].parameters == {
        "coordinate": [540, 1600],
        "coordinate2": [540, 400],
        "duration": 0.5,
    }


def test_dsml_parser_repairs_common_model_typographical_closers() -> None:
    responses = [
        (
            """<｜DSML｜tool_calls>
<｜DSML｜invoke name="click">
<｜DSML｜parameter name="index">8</｜DSML｜parameter>
</｜DSML>
</｜DSML｜tool_calls>""",
            8,
        ),
        (
            """<｜DSML｜tool_calls>
<｜DSML｜invoke name="click">
<｜DSML｜parameter name="index">32</｜DSML｜parameter>
</invok>
</function_calls>""",
            32,
        ),
        (
            """<｜DSML｜tool_calls>
<｜DSML｜invoke name="click">
<｜DSML｜parameter name="index">21</｜DSML｜parameter>
</invoke>""",
            21,
        ),
        (
            """<｜DSML｜tool_calls>
<｜DSML｜invoke name="click">
<｜DSML｜parameter name="index">21</｜DSML｜parameter>
</invoke>
</function_results>""",
            21,
        ),
    ]

    for response, index in responses:
        result = parse_tool_calls_detailed(
            response,
            {"index": "number"},
            allow_dsml=True,
        )
        assert result.status is ToolCallParseStatus.VALID
        assert [(call.name, call.parameters) for call in result.calls] == [
            ("click", {"index": index})
        ]


def test_anthropic_compatible_provider_alias_uses_anthropic_transport() -> None:
    assert normalize_provider_name("anthropic-compatible") == "Anthropic"
