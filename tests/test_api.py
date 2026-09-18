from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


SOW = """1.1 Deliverable: Build an e-commerce application with customer accounts and shopping cart.

4.1 Payment Integration: Process standard credit-card checkout payments through Stripe, including Stripe webhooks.

5.1 Exclusions: Native mobile applications and ERP integrations are not included in scope.
"""


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "test.db"))


def test_document_library_and_editor_pages_are_served(tmp_path):
    client = make_client(tmp_path)
    library = client.get("/documents")
    editor = client.get("/documents/42")
    assert library.status_code == 200
    assert "SOW Documents" in library.text
    assert client.get("/assets/documents.js").status_code == 200
    assert editor.status_code == 200
    assert "Edit document" in editor.text
    assert "Save as new revision" in editor.text
    assert "Delete document" in editor.text
    assert 'class="sidebar"' in library.text
    assert 'class="sidebar"' in editor.text
    new_document = client.get("/documents/new")
    assert new_document.status_code == 200
    assert "Add a <span>document</span>" in new_document.text
    assert "New SOW" in new_document.text
    assert "Contract amendment" in new_document.text
    assert "+ Add new document" in library.text


def test_administration_is_a_separate_page(tmp_path):
    client = make_client(tmp_path)
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert 'id="adminPanel"' not in dashboard.text
    assert 'id="loginUser"' not in dashboard.text
    for route in ("/", "/documents", "/documents/new", "/documents/42"):
        assert 'href="/administration"' in client.get(route).text
    administration = client.get("/administration")
    assert administration.status_code == 200
    for control in ("loginUser", "logoutUser", "bootstrapUser", "setupToken", "loadSecurityStatus", "loadSecurityAudit"):
        assert f'id="{control}"' in administration.text
    assert 'src="/assets/administration.js"' in administration.text
    assert 'src="/assets/index.js"' not in administration.text
    assert client.get("/assets/administration.js").status_code == 200
    assert client.get("/assets/workspace.js").status_code == 200


def test_administration_login_page_available_when_auth_required(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_AUTH_REQUIRED", "true")
    client = make_client(tmp_path)
    assert client.get("/administration").status_code == 200
    assert client.get("/api/security/audit-events").status_code == 401


def test_contract_can_be_soft_deleted_and_restored(tmp_path):
    client = make_client(tmp_path)
    contract = client.post(
        "/api/contracts/text", json={"title": "Deletable SOW", "content": SOW}
    ).json()

    deleted = client.delete(f"/api/contracts/{contract['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "DELETED"
    assert deleted.json()["audit_history_preserved"] is True
    assert client.get("/api/contracts").json() == []
    assert client.get("/api/contracts?include_deleted=true").json()[0]["status"] == "DELETED"

    restored = client.post(f"/api/contracts/{contract['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["status"] == "ACTIVE"
    assert client.get("/api/contracts").json()[0]["id"] == contract["id"]


def test_contract_ticket_analysis_and_change_order(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/health").json() == {"status": "ok"}

    contract_response = client.post(
        "/api/contracts/text",
        json={"title": "Commerce SOW", "content": SOW},
    )
    assert contract_response.status_code == 201
    contract = contract_response.json()
    assert contract["clause_count"] == 3

    ticket_response = client.post(
        "/api/tickets",
        json={
            "contract_id": contract["id"],
            "external_key": "PROJ-142",
            "title": "Integrate Coinbase Commerce checkout",
            "description": "Add Coinbase Commerce as another payment provider with cryptocurrency webhooks.",
            "acceptance_criteria": "Coinbase cryptocurrency payment marks an order paid.",
            "estimated_hours": 24,
        },
    )
    assert ticket_response.status_code == 201
    body = ticket_response.json()
    assert body["analysis"]["decision"] == "OUT_OF_SCOPE"
    assert body["evidence"][0]["clause_ref"] == "4.1"

    history = client.get(f"/api/history?contract_id={contract['id']}")
    assert history.status_code == 200
    assert history.json()[0]["id"] == body["ticket"]["id"]
    assert history.json()[0]["analysis_count"] == 1
    ticket_history = client.get(f"/api/tickets/{body['ticket']['id']}/history")
    assert ticket_history.status_code == 200
    assert ticket_history.json()["analyses"][0]["decision"] == "OUT_OF_SCOPE"

    quote_response = client.post(
        f"/api/tickets/{body['ticket']['id']}/change-orders",
        json={"internal_hourly_cost": 80, "target_margin": 0.36, "currency": "USD"},
    )
    assert quote_response.status_code == 201
    quote = quote_response.json()
    assert quote["price"] == 3000
    assert "PROJ-142" in quote["draft_text"]
    assert "authorized client approval" in quote["draft_text"]


def test_pm_can_override_ambiguous_ticket(tmp_path):
    client = make_client(tmp_path)
    contract = client.post(
        "/api/contracts/text", json={"title": "Commerce SOW", "content": SOW}
    ).json()
    result = client.post(
        "/api/tickets",
        json={
            "contract_id": contract["id"],
            "title": "Add customer analytics dashboard",
            "description": "Show customer purchase trends and account activity in a dashboard.",
            "acceptance_criteria": "Managers can filter customer purchase trends by month.",
            "estimated_hours": 12,
        },
    ).json()
    assert result["analysis"]["decision"] == "NEEDS_REVIEW"

    review = client.post(
        f"/api/tickets/{result['ticket']['id']}/review",
        json={
            "reviewer": "Project Manager",
            "decision": "OUT_OF_SCOPE",
            "reason": "Analytics was not part of the signed deliverables.",
        },
    )
    assert review.status_code == 201
    assert review.json()["status"] == "OUT_OF_SCOPE"


def test_in_scope_ticket_cannot_create_change_order(tmp_path):
    client = make_client(tmp_path)
    contract = client.post(
        "/api/contracts/text", json={"title": "Commerce SOW", "content": SOW}
    ).json()
    result = client.post(
        "/api/tickets",
        json={
            "contract_id": contract["id"],
            "title": "Implement Stripe payment webhook",
            "description": "Process contracted Stripe credit-card checkout payments and Stripe webhooks.",
            "acceptance_criteria": "A Stripe payment webhook marks the customer order as paid.",
            "estimated_hours": 8,
        },
    ).json()
    assert result["analysis"]["decision"] == "IN_SCOPE"
    response = client.post(
        f"/api/tickets/{result['ticket']['id']}/change-orders",
        json={"internal_hourly_cost": 80},
    )
    assert response.status_code == 409
