"""Expanded isolated security checks; no production data or third-party integrations used."""
import hashlib
import hmac
import json
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.auth import hash_password, verify_password


def test_text_pdf_can_be_uploaded_and_indexed(tmp_path, monkeypatch):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 40 740 Td (1.1 Deliverable: Build a customer web portal.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    _, client = authenticated(tmp_path, monkeypatch)
    response = client.post("/api/contracts/upload?title=Synthetic%20PDF", files={"file": ("synthetic.pdf", output.getvalue(), "application/pdf")})
    assert response.status_code == 201
    clauses = client.get(f"/api/contracts/{response.json()['id']}/clauses").json()
    assert any("customer web portal" in row["text"] for row in clauses)

ADMIN = {"name": "QA Administrator", "email": "qa@example.test", "password": "Synthetic-qa-only-passphrase-981!"}
SOW = "1.1 Deliverable: Build a customer web portal.\n\n5.1 Exclusions: Native mobile applications are excluded."


def authenticated(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_AUTH_REQUIRED", "true")
    app = create_app(tmp_path / "security-extended.db")
    client = TestClient(app, raise_server_exceptions=False)
    result = client.post("/api/auth/bootstrap", json=ADMIN)
    assert result.status_code == 201
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return app, client


@pytest.mark.parametrize("path", [
    "/api/contracts", "/api/contracts?include_deleted=true", "/api/contracts/1",
    "/api/contracts/1/clauses", "/api/contracts/1/effective-clauses", "/api/tickets",
    "/api/tickets/1/analysis", "/api/tickets/1/history", "/api/history",
    "/api/dashboard/review-queue", "/api/security/audit-events", "/api/approvals",
    "/api/approvals/1", "/api/approvals/targets?target_type=CONTRACT",
    "/api/approvals/targets?target_type=CHANGE_ORDER",
])
def test_anonymous_private_read_matrix(tmp_path, monkeypatch, path):
    monkeypatch.setenv("SCOPE_SENTINEL_AUTH_REQUIRED", "true")
    client = TestClient(create_app(tmp_path / "anonymous.db"))
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("condition", ["expired", "disabled-user", "logged-out"])
def test_sessions_stop_authorizing_after_revocation(tmp_path, monkeypatch, condition):
    app, client = authenticated(tmp_path, monkeypatch)
    token = client.cookies.get("scope_session")
    assert client.get("/api/contracts").status_code == 200
    if condition == "logged-out":
        assert client.post("/api/auth/logout").status_code == 200
        client.cookies.set("scope_session", token)
    else:
        with app.state.database.connection() as connection:
            if condition == "expired":
                connection.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
            else:
                connection.execute("UPDATE users SET active=0")
    assert client.get("/api/contracts").status_code == 401


def test_oldest_session_is_evicted_at_configured_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_MAX_SESSIONS_PER_USER", "1")
    app, client = authenticated(tmp_path, monkeypatch)
    other = TestClient(app)
    assert other.post("/api/auth/login", json=ADMIN).status_code == 200
    assert client.get("/api/contracts").status_code == 401
    assert other.get("/api/contracts").status_code == 200


def test_foreign_origin_blocked_even_with_valid_csrf(tmp_path, monkeypatch):
    _, client = authenticated(tmp_path, monkeypatch)
    result = client.post("/api/contracts/text", headers={"Origin": "https://attacker.invalid"}, json={"title": "Rejected", "content": SOW})
    assert result.status_code == 403
    assert client.get("/api/contracts").json() == []


def test_password_hashes_use_unique_salts_and_reject_wrong_password():
    first, second = hash_password(ADMIN["password"]), hash_password(ADMIN["password"])
    assert first != second and ADMIN["password"] not in first
    assert verify_password(ADMIN["password"], first)
    assert not verify_password("incorrect-password", first)


def test_sql_metacharacters_are_data_not_queries(tmp_path, monkeypatch):
    _, client = authenticated(tmp_path, monkeypatch)
    title = "QA '); DROP TABLE contracts; --"
    result = client.post("/api/contracts/text", json={"title": title, "content": SOW})
    assert result.status_code == 201
    assert client.get("/api/contracts").json()[0]["title"] == title


@pytest.mark.parametrize("path", ["/.env", "/scope_sentinel.db", "/.local/bootstrap-token.txt", "/assets/%2e%2e/app/main.py"])
def test_files_outside_assets_are_not_exposed(tmp_path, path):
    client = TestClient(create_app(tmp_path / "files.db"))
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("filename,content,expected", [
    ("bad.exe", b"This is not a supported contract file.", 415),
    ("broken.pdf", b"%PDF-1.4 not a valid PDF document", 422),
    ("empty.txt", b"", 400),
    ("invalid.txt", b"\xff\xfe invalid utf8 file contents", 422),
])
def test_bad_uploads_fail_without_persisting_documents(tmp_path, monkeypatch, filename, content, expected):
    _, client = authenticated(tmp_path, monkeypatch)
    result = client.post("/api/contracts/upload?title=QA%20Upload", files={"file": (filename, content)})
    assert result.status_code == expected
    assert client.get("/api/contracts").json() == []


def test_invalid_jira_signature_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "qa-jira-secret")
    client = TestClient(create_app(tmp_path / "jira.db"))
    assert client.post("/api/webhooks/jira?contract_id=1", json={}, headers={"X-Hub-Signature": "sha256=invalid"}).status_code == 401


def test_jira_unsupported_digest_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "qa-jira-secret")
    client = TestClient(create_app(tmp_path / "jira-digest.db"), raise_server_exceptions=False)
    response = client.post("/api/webhooks/jira?contract_id=1", json={}, headers={"X-Hub-Signature": "shake_128=invalid"})
    assert response.status_code in {400, 401}, "QA-01: unsupported HMAC digest must not cause HTTP 500"


def test_jira_redelivery_does_not_create_duplicate_ticket(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "qa-jira-secret")
    _, client = authenticated(tmp_path, monkeypatch)
    contract = client.post("/api/contracts/text", json={"title": "QA replay SOW", "content": SOW}).json()["id"]
    body = json.dumps({"issue": {"key": "QA-REPLAY-1", "fields": {"summary": "Build customer web portal", "description": "Implement customer web portal."}}}).encode()
    signature = "sha256=" + hmac.new(b"qa-jira-secret", body, hashlib.sha256).hexdigest()
    for _ in range(2):
        result = client.post(f"/api/webhooks/jira?contract_id={contract}", content=body, headers={"X-Hub-Signature": signature, "Content-Type": "application/json"})
        assert result.status_code in {200, 201, 409}
    assert len(client.get("/api/tickets").json()) == 1, "QA-02: Jira redelivery currently creates duplicate ticket/analysis rows"


def test_future_amendment_does_not_apply_before_effective_date(tmp_path, monkeypatch):
    _, client = authenticated(tmp_path, monkeypatch)
    contract = client.post("/api/contracts/text", json={"title": "QA effective dates", "content": SOW}).json()["id"]
    result = client.post(f"/api/contracts/{contract}/amendments/text", json={"title": "Future scope", "content": "5.1 Deliverable: Native mobile applications are included.", "version": "2.0", "effective_date": "2099-01-01", "supersedes_clause_refs": ["5.1"]})
    assert result.status_code == 201
    clauses = client.get(f"/api/contracts/{contract}/effective-clauses").json()
    assert any("excluded" in row["text"] for row in clauses), "QA-03: future-dated amendment replaces current scope immediately"


def test_scope_reason_does_not_describe_excluded_erp_as_contracted_provider(tmp_path, monkeypatch):
    _, client = authenticated(tmp_path, monkeypatch)
    content = "4.1 Payment Integration: Process standard credit-card checkout payments through Stripe. Stripe webhooks are included.\n\n5.1 Exclusions: Native mobile applications, cryptocurrency payments and ERP integrations are not included."
    contract = client.post("/api/contracts/text", json={"title": "QA provider explanation", "content": content}).json()["id"]
    ticket = client.post("/api/tickets", json={"contract_id": contract, "title": "Add Coinbase cryptocurrency checkout", "description": "Add Coinbase Commerce as a second payment provider with cryptocurrency payment webhooks.", "acceptance_criteria": "A successful Coinbase cryptocurrency payment marks the customer order as paid."}).json()
    assert ticket["analysis"]["decision"] == "OUT_OF_SCOPE"
    assert "contracted one (ERP)" not in ticket["analysis"]["reason"], "QA-04: exclusion text is misidentified as a contracted provider"
