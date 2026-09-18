import pytest
from fastapi.testclient import TestClient
from app.main import create_app

PASSWORD = "test-only-strong-password-981!"
SOW = "1.1 Deliverable: Build a customer web portal.\n\n5.1 Exclusions: Native mobile applications are not included."


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOPE_SENTINEL_AUTH_REQUIRED", "true")
    app = create_app(tmp_path / "approvals.db")
    admin = TestClient(app)
    bootstrap = admin.post("/api/auth/bootstrap", json={"name": "Admin", "email": "admin@example.com", "password": PASSWORD})
    assert bootstrap.status_code == 201
    admin.headers["X-CSRF-Token"] = bootstrap.json()["csrf_token"]
    clients = {"ADMIN": admin}
    for role in ["PM", "SALES", "VIEWER", "DEVELOPER"]:
        user = {"name": role + " Tester", "email": role.lower() + "@example.com", "password": PASSWORD, "role": role}
        assert admin.post("/api/users", json=user).status_code == 201
        client = TestClient(app)
        login = client.post("/api/auth/login", json=user)
        assert login.status_code == 200
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        clients[role] = client
    contract = admin.post("/api/contracts/text", json={"title": "Pilot SOW", "content": SOW}).json()
    return app, clients, contract["id"]


def submit(client, target_id, target_type="CONTRACT"):
    return client.post("/api/approvals", json={"target_type": target_type, "target_id": target_id, "reason": "Please review the exact submitted version."})


def decide(client, approval_id, decision="APPROVED"):
    return client.post(f"/api/approvals/{approval_id}/decision", json={"decision": decision, "reason": "Reviewed against the submitted evidence."})


def test_sow_approval_no_self_review_and_immutable_final_decision(workspace):
    app, users, contract = workspace
    response = submit(users["PM"], contract)
    assert response.status_code == 201
    approval = response.json()["id"]
    assert submit(users["PM"], contract).status_code == 409
    assert decide(users["PM"], approval).status_code == 403
    assert decide(users["SALES"], approval).status_code == 403
    assert decide(users["ADMIN"], approval).status_code == 200
    assert decide(users["ADMIN"], approval, "REJECTED").status_code == 409
    assert submit(users["PM"], contract).status_code == 409
    record = users["VIEWER"].get(f"/api/approvals/{approval}").json()
    assert record["status"] == "APPROVED"
    assert record["snapshot"]["content"] == SOW
    assert len(record["snapshot_hash"]) == 64
    assert record["requested_by"] != record["reviewed_by"]
    assert record["reviewed_at"] and record["decision_reason"]
    events = users["ADMIN"].get("/api/security/audit-events").json()
    assert any(row["event_type"] == "APPROVAL_APPROVED" for row in events)


def test_approval_access_and_csrf_are_enforced(workspace):
    app, users, contract = workspace
    anonymous = TestClient(app)
    for path in ["/api/approvals", "/api/approvals/targets?target_type=CONTRACT", "/api/approvals/1"]:
        assert anonymous.get(path).status_code == 401
    for role in ["VIEWER", "DEVELOPER", "SALES"]:
        assert submit(users[role], contract).status_code == 403
    del users["PM"].headers["X-CSRF-Token"]
    assert submit(users["PM"], contract).status_code == 403


def test_deleted_or_changed_snapshot_cannot_be_approved(workspace):
    app, users, contract = workspace
    approval = submit(users["PM"], contract).json()["id"]
    with app.state.database.connection() as connection:
        connection.execute("UPDATE contracts SET content=? WHERE id=?", (SOW + " Changed.", contract))
    assert decide(users["ADMIN"], approval).status_code == 409
    assert decide(users["ADMIN"], approval, "REJECTED").status_code == 200
    fresh = submit(users["PM"], contract).json()["id"]
    assert users["ADMIN"].delete(f"/api/contracts/{contract}").status_code == 200
    assert decide(users["ADMIN"], fresh).status_code == 409
    assert decide(users["ADMIN"], fresh, "REJECTED").status_code == 200


def test_new_revision_does_not_inherit_approval(workspace):
    app, users, contract = workspace
    approval = submit(users["PM"], contract).json()["id"]
    assert decide(users["ADMIN"], approval).status_code == 200
    revision = users["PM"].post(f"/api/contracts/{contract}/revisions/text", json={"title": "Revised pilot", "version": "2.0", "content": SOW + "\n\n2.1 Deliverable: Reports."}).json()["id"]
    fresh = submit(users["PM"], revision)
    assert fresh.status_code == 201 and fresh.json()["status"] == "PENDING"
    assert fresh.json()["id"] != approval


def test_commercial_draft_requires_different_sales_or_admin(workspace):
    app, users, contract = workspace
    ticket = users["PM"].post("/api/tickets", json={"contract_id": contract, "title": "Build native mobile apps", "description": "Create Android and iOS native applications.", "estimated_hours": 20}).json()["ticket"]["id"]
    quote = users["PM"].post(f"/api/tickets/{ticket}/change-orders", json={"internal_hourly_cost": 80, "target_margin": 0.3})
    assert quote.status_code == 201
    quote_id = quote.json()["id"]
    approval = submit(users["PM"], quote_id, "CHANGE_ORDER").json()["id"]
    assert decide(users["PM"], approval).status_code == 403
    assert decide(users["SALES"], approval).status_code == 200
    saved = users["ADMIN"].get(f"/api/tickets/{ticket}/history").json()["change_orders"][0]
    assert saved["status"] == "INTERNALLY_APPROVED"
    assert submit(users["PM"], quote_id, "CHANGE_ORDER").status_code == 409


def test_approval_pages_and_links(workspace):
    app, users, _ = workspace
    client = users["ADMIN"]
    for route in ["/", "/documents", "/documents/new", "/documents/1", "/administration", "/approvals"]:
        assert 'href="/approvals"' in client.get(route).text
    assert client.get("/assets/approvals.js").status_code == 200
    assert 'id="createUserForm"' in client.get("/administration").text
    assert 'id="requestApproval"' in client.get("/documents/1").text
