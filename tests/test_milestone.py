import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.analyzer import AnalysisResult
from app.services.integrations import verify_jira_signature, verify_slack_signature
from app.services.llm import review_with_openai


BASE_SOW = """3.1 Payment Integration: Stripe card checkout and Stripe webhooks are included.

3.2 Payment Limitation: Stripe is the only approved payment provider. Razorpay and Coinbase are excluded.
"""


def test_amendment_supersedes_base_clause(tmp_path):
    client = TestClient(create_app(tmp_path / "amendment.db"))
    base = client.post(
        "/api/contracts/text",
        json={"title": "Base SOW", "content": BASE_SOW, "version": "1.0"},
    ).json()
    amendment = client.post(
        f"/api/contracts/{base['id']}/amendments/text",
        json={
            "title": "Payment Amendment",
            "content": "3.2 Payment Amendment: Razorpay card checkout and Razorpay webhooks are included.",
            "version": "1.1",
            "effective_date": "2026-09-01",
            "supersedes_clause_refs": ["3.2"],
        },
    )
    assert amendment.status_code == 201
    clauses = client.get(f"/api/contracts/{base['id']}/effective-clauses").json()
    matching = [clause for clause in clauses if clause["clause_ref"] == "3.2"]
    assert len(matching) == 1
    assert matching[0]["contract_version"] == "1.1"
    assert "Razorpay card checkout" in matching[0]["text"]


def test_full_sow_revision_preserves_prior_document(tmp_path):
    client = TestClient(create_app(tmp_path / "revision.db"))
    base = client.post(
        "/api/contracts/text",
        json={"title": "Commerce SOW", "content": BASE_SOW, "version": "1.0"},
    ).json()
    revision = client.post(
        f"/api/contracts/{base['id']}/revisions/text",
        json={
            "title": "Commerce SOW",
            "content": "3.1 Payment Integration: Razorpay card checkout and Razorpay webhooks are included.",
            "version": "2.0",
            "effective_date": "2026-10-01",
        },
    )
    assert revision.status_code == 201
    document = client.get(f"/api/contracts/{base['id']}").json()
    assert len(document["revisions"]) == 2
    effective = client.get(f"/api/contracts/{base['id']}/effective-clauses").json()
    assert len(effective) == 1
    assert effective[0]["contract_version"] == "2.0"
    assert "Razorpay" in effective[0]["text"]


def test_bootstrap_login_and_role_protected_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_AUTH_REQUIRED", "true")
    client = TestClient(create_app(tmp_path / "auth.db"))
    assert client.get("/api/dashboard/review-queue").status_code == 401

    response = client.post(
        "/api/auth/bootstrap",
        json={"name": "Admin User", "email": "admin@example.com", "password": "strong-password-123"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "ADMIN"
    assert client.get("/api/dashboard/review-queue").status_code == 200
    assert client.get("/api/auth/me").json()["email"] == "admin@example.com"

    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": response.json()["csrf_token"]}).status_code == 200
    assert client.get("/api/dashboard/review-queue").status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "strong-password-123"}
    ).status_code == 200


def test_jira_and_slack_signature_verification():
    body = b'{"event":"test"}'
    jira_signature = "sha256=" + hmac.new(b"jira-secret", body, hashlib.sha256).hexdigest()
    assert verify_jira_signature(body, jira_signature, "jira-secret")
    assert not verify_jira_signature(body + b"x", jira_signature, "jira-secret")

    timestamp = str(int(time.time()))
    base = b"v0:" + timestamp.encode() + b":" + body
    slack_signature = "v0=" + hmac.new(b"slack-secret", base, hashlib.sha256).hexdigest()
    assert verify_slack_signature(body, timestamp, slack_signature, "slack-secret")
    assert not verify_slack_signature(body, "1", slack_signature, "slack-secret")


def test_signed_slack_challenge(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "slack-secret")
    client = TestClient(create_app(tmp_path / "slack.db"))
    body = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()
    timestamp = str(int(time.time()))
    base = b"v0:" + timestamp.encode() + b":" + body
    signature = "v0=" + hmac.new(b"slack-secret", base, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/webhooks/slack",
        content=body,
        headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "abc123"}


def test_llm_invented_clause_citation_falls_back(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            decision = {
                "decision": "OUT_OF_SCOPE",
                "confidence": 0.99,
                "reason": "Invented evidence.",
                "evidence_clause_refs": ["99.99"],
            }
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(decision)}]}]}

    monkeypatch.setattr("app.services.llm.httpx.post", lambda *args, **kwargs: FakeResponse())
    fallback = AnalysisResult("NEEDS_REVIEW", 0.7, "Local fallback.", [])
    result = review_with_openai(
        "Add a new payment provider",
        [{"id": 1, "clause_ref": "3.1", "category": "INTEGRATION", "text": "Stripe is included."}],
        "test-key",
        "configured-model",
        fallback,
    )
    assert result is fallback
