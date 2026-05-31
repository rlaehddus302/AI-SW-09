import pytest

from app.llm.client import LLMConfigurationError, UpstageConfig, create_ai_client, normalize_ai_mode


def test_ai_mode_accepts_only_explicit_live_or_mock():
    assert normalize_ai_mode("mock") == "mock"
    assert normalize_ai_mode("live") == "live"

    with pytest.raises(ValueError):
        normalize_ai_mode("auto")


def test_create_ai_client_modes_are_explicit():
    mock_client = create_ai_client(UpstageConfig(ai_mode="mock"))
    assert mock_client.mode == "mock"

    live_client = create_ai_client(UpstageConfig(ai_mode="live", api_key="test-key"))
    assert live_client.mode == "live"

    with pytest.raises(LLMConfigurationError):
        create_ai_client(UpstageConfig(ai_mode="live", api_key=None))
