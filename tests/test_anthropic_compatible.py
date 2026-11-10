from mobilerun.agent.providers.registry import resolve_provider_variant
from mobilerun.agent.providers.setup_service import (
    SetupSelection,
    create_profile_for_variant,
)
from mobilerun.agent.utils.llm_picker import load_llm, normalize_provider_name
from mobilerun.config_manager.config_manager import LLMProfile

CUSTOM_BASE_URL = "http://hithink-oslm.myhexin.com/osllm"
CUSTOM_MODEL = "tb2b-v1-minimax-m25"


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


def test_anthropic_compatible_provider_alias_uses_anthropic_transport() -> None:
    assert normalize_provider_name("anthropic-compatible") == "Anthropic"
