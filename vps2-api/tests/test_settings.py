from app.core.config import Settings


def test_settings_load_from_env():
    s = Settings()
    assert s.app_env in {"development", "staging", "production"}
    assert s.service_token == "x" * 32
    assert s.supabase_jwt_audience == "authenticated"


def test_cors_origins_empty_by_default():
    s = Settings()
    assert s.cors_origins == []


def test_cors_origins_parsed():
    s = Settings(allowed_origins="https://a.com, https://b.com ,")
    assert s.cors_origins == ["https://a.com", "https://b.com"]
