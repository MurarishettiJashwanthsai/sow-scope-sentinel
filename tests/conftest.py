import pytest


@pytest.fixture(autouse=True)
def explicit_local_test_configuration(monkeypatch):
    """Legacy functional tests opt into demo mode; real application defaults stay secure."""
    monkeypatch.setenv("SCOPE_SENTINEL_AUTH_REQUIRED", "false")
    monkeypatch.setenv("SCOPE_SENTINEL_SECURE_COOKIES", "false")
    monkeypatch.setenv("SCOPE_SENTINEL_ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")
