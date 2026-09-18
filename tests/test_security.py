from fastapi.testclient import TestClient

from app.main import create_app


ADMIN = {
    "name": "Security Admin",
    "email": "security@example.com",
    "password": "a-secure-password-123",
}


def test_security_headers_and_request_id(tmp_path):
    client = TestClient(create_app(tmp_path / "headers.db"))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert len(response.headers["x-request-id"]) == 32


def test_trusted_host_rejects_unknown_host(tmp_path):
    client = TestClient(create_app(tmp_path / "hosts.db"))
    response = client.get("/health", headers={"host": "attacker.invalid"})
    assert response.status_code == 400


def test_authenticated_browser_write_requires_csrf(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_AUTH_REQUIRED", "true")
    client = TestClient(create_app(tmp_path / "csrf.db"))
    bootstrap = client.post("/api/auth/bootstrap", json=ADMIN)
    assert bootstrap.status_code == 201
    token = bootstrap.json()["csrf_token"]

    blocked = client.post(
        "/api/auth/logout", headers={"origin": "http://127.0.0.1:8000"}
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "CSRF validation failed."

    allowed = client.post(
        "/api/auth/logout",
        headers={"origin": "http://127.0.0.1:8000", "X-CSRF-Token": token},
    )
    assert allowed.status_code == 200


def test_repeated_failed_login_temporarily_locks_account(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_LOCKOUT_ATTEMPTS", "3")
    client = TestClient(create_app(tmp_path / "lockout.db"))
    assert client.post("/api/auth/bootstrap", json=ADMIN).status_code == 201
    client.post("/api/auth/logout")

    wrong = {"email": ADMIN["email"], "password": "wrong-password-999"}
    for _ in range(3):
        assert client.post("/api/auth/login", json=wrong).status_code == 401
    locked = client.post("/api/auth/login", json=ADMIN)
    assert locked.status_code == 423
    assert "Retry-After" in locked.headers

    events = client.get("/api/security/audit-events").json()
    assert any(event["event_type"] == "LOGIN_ACCOUNT_LOCKED" for event in events)
    assert sum(event["event_type"] == "LOGIN" and event["outcome"] == "FAILURE" for event in events) == 3


def test_upload_size_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_MAX_UPLOAD_MB", "1")
    client = TestClient(create_app(tmp_path / "upload.db"))
    response = client.post(
        "/api/contracts/upload?title=Oversized%20SOW",
        files={"file": ("large.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
    )
    assert response.status_code == 413


def test_private_api_requires_login_and_viewer_cannot_write(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_AUTH_REQUIRED", "true")
    client = TestClient(create_app(tmp_path / "permissions.db"))
    for path in ["/api/contracts", "/api/contracts/1", "/api/tickets", "/api/history"]:
        assert client.get(path).status_code == 401
    assert client.post("/api/contracts/text", json={}).status_code == 401
    bootstrap = client.post("/api/auth/bootstrap", json=ADMIN).json()
    client.headers["X-CSRF-Token"] = bootstrap["csrf_token"]
    viewer = {**ADMIN, "email": "viewer@example.com", "role": "VIEWER"}
    assert client.post("/api/users", json=viewer).status_code == 201
    assert client.post("/api/auth/logout").status_code == 200
    login = client.post("/api/auth/login", json=viewer).json()
    client.headers["X-CSRF-Token"] = login["csrf_token"]
    assert client.get("/api/contracts").status_code == 200
    for method, path in [("POST", "/api/contracts/text"), ("DELETE", "/api/contracts/1"),
                         ("POST", "/api/tickets"), ("POST", "/api/tickets/1/reanalyze")]:
        assert client.request(method, path, json={}).status_code == 403
    assert client.get("/api/security/audit-events").status_code == 403


def test_csrf_is_required_without_origin_and_bound_to_session(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_AUTH_REQUIRED", "true")
    client = TestClient(create_app(tmp_path / "csrf-session.db"))
    token = client.post("/api/auth/bootstrap", json=ADMIN).json()["csrf_token"]
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert client.get("/api/security/csrf").json()["csrf_token"] == token
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": token}).status_code == 200
    assert client.get("/api/contracts").status_code == 401


def test_jira_requires_configured_signature(tmp_path, monkeypatch):
    monkeypatch.delenv("JIRA_WEBHOOK_SECRET", raising=False)
    client = TestClient(create_app(tmp_path / "jira-secure.db"))
    assert client.post("/api/webhooks/jira?contract_id=1", json={}).status_code == 503


def test_csp_blocks_inline_code_and_api_responses_are_not_cached(tmp_path):
    client = TestClient(create_app(tmp_path / "csp.db"))
    assert "'unsafe-inline'" not in client.get("/").headers["content-security-policy"]
    assert client.get("/api/contracts").headers["cache-control"] == "no-store"
    for path in ["/", "/documents", "/documents/new", "/documents/1"]:
        html = client.get(path).text
        assert "<script>" not in html
        assert client.get("/assets/workspace.js").status_code == 200


def test_login_rate_limit_spans_different_email_addresses(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_LOGIN_RATE_LIMIT", "2")
    client = TestClient(create_app(tmp_path / "throttled.db"))
    for email in ["one@example.com", "two@example.com"]:
        assert client.post("/api/auth/login", json={"email": email, "password": "invalid"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "three@example.com", "password": "invalid"}).status_code == 429


def test_setup_token_guards_first_administrator(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_BOOTSTRAP_TOKEN", "test-setup-token")
    client = TestClient(create_app(tmp_path / "bootstrap.db"))
    assert client.post("/api/auth/bootstrap", json=ADMIN).status_code == 403
    assert client.post("/api/auth/bootstrap", json=ADMIN, headers={"X-Bootstrap-Token": "test-setup-token"}).status_code == 201


def test_secure_defaults_require_https_login_and_csrf(tmp_path, monkeypatch):
    monkeypatch.delenv("SCOPE_SENTINEL_AUTH_REQUIRED")
    monkeypatch.delenv("SCOPE_SENTINEL_SECURE_COOKIES")
    monkeypatch.delenv("SCOPE_SENTINEL_ALLOWED_ORIGINS")
    monkeypatch.setenv("SCOPE_SENTINEL_BOOTSTRAP_TOKEN", "secure-test-setup")
    app = create_app(tmp_path / "secure-defaults.db")
    insecure = TestClient(app)
    assert insecure.get("/api/contracts").status_code == 426
    assert insecure.post("/api/auth/login", json=ADMIN).status_code == 426
    client = TestClient(app, base_url="https://localhost:8443")
    status = client.get("/api/security/status").json()
    assert status["csrf_protection"] is True
    assert status["secure_cookies"] is True
    assert client.get("/api/contracts").status_code == 401
    bootstrap = client.post("/api/auth/bootstrap", json=ADMIN, headers={"X-Bootstrap-Token": "secure-test-setup"})
    assert bootstrap.status_code == 201
    cookie_headers = bootstrap.headers.get_list("set-cookie")
    assert all("Secure" in cookie for cookie in cookie_headers)
    assert any("scope_session=" in cookie and "HttpOnly" in cookie for cookie in cookie_headers)
    assert client.get("/api/contracts").status_code == 200
    assert client.post("/api/auth/logout").status_code == 403
    csrf = bootstrap.json()["csrf_token"]
    assert client.post("/api/auth/logout", headers={"Origin": "https://localhost:8443", "X-CSRF-Token": csrf}).status_code == 200
    assert client.post("/api/auth/login", json=ADMIN).status_code == 200


def test_http_entry_point_only_redirects_safe_navigation():
    from app.http_redirect import app
    client = TestClient(app, follow_redirects=False)
    response = client.get("/administration?contract_id=2", headers={"Host": "attacker.invalid"})
    assert response.status_code == 307
    assert response.headers["location"] == "https://localhost:8443/administration?contract_id=2"
    assert client.post("/api/auth/login", json=ADMIN).status_code == 426
