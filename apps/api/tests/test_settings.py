from opencanvas_api.core.config import Settings


def test_settings_normalize_empty_key_and_log_level() -> None:
    settings = Settings(openai_api_key="", log_level="debug")

    assert settings.openai_api_key is None
    assert settings.log_level == "DEBUG"
    assert settings.openai_configured is False


def test_openai_provider_requires_a_key() -> None:
    settings = Settings(ai_provider="openai", openai_api_key="test-key")

    assert settings.openai_configured is True
