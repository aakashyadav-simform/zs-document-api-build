from app.core.config import Settings, get_settings


def test_defaults_are_sane():
    s = Settings()
    assert s.rate_limit_max == 3
    assert s.max_attempts == 3
    assert "mongodb://" in s.mongodb_uri


def test_get_settings_is_cached():
    assert get_settings() is get_settings()
