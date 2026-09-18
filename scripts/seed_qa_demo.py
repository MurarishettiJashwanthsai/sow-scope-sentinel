"""Seed an explicitly new disposable database for browser tests/screenshots only.

Usage: .venv/bin/python scripts/seed_qa_demo.py /private/tmp/qa-directory/qa.db
Never point a publicly accessible server at this fixture: the credentials are test-only.
"""
import os
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Provide a new disposable database path.")
database = Path(sys.argv[1]).resolve()
root = Path(__file__).resolve().parent.parent
if database.exists() or database == root / "scope_sentinel.db":
    raise SystemExit("Refusing to modify an existing database.")
os.environ["SCOPE_SENTINEL_DB"] = str(database)
os.environ["SCOPE_SENTINEL_AUTH_REQUIRED"] = "true"
os.environ["SCOPE_SENTINEL_SECURE_COOKIES"] = "false"
os.environ["SCOPE_SENTINEL_BOOTSTRAP_TOKEN"] = "qa-fixture-setup-only"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("SCOPE_SENTINEL_LLM_MODEL", None)
sys.path.insert(0, str(root))
from fastapi.testclient import TestClient
from app.main import create_app

app = create_app(database)
admin = TestClient(app)
password = "Synthetic-demo-only-passphrase-981!"
result = admin.post("/api/auth/bootstrap", headers={"X-Bootstrap-Token": "qa-fixture-setup-only"}, json={"name": "QA Administrator", "email": "admin@example.test", "password": password})
assert result.status_code == 201
admin.headers["X-CSRF-Token"] = result.json()["csrf_token"]
for name, email, role in [("QA Project Manager", "pm@example.test", "PM"), ("QA Viewer", "viewer@example.test", "VIEWER")]:
    assert admin.post("/api/users", json={"name": name, "email": email, "password": password, "role": role}).status_code == 201

sow = """1.1 Deliverable: Build a responsive e-commerce web application with a product catalogue, customer accounts and a shopping cart.

4.1 Payment Integration: Process standard credit-card checkout payments through Stripe. Stripe webhooks are included.

5.1 Exclusions: Native mobile applications, cryptocurrency payments and ERP integrations are not included.

6.1 Acceptance: Customer checkout passes the agreed functional tests and a Project Manager reviews acceptance evidence.
"""
documents = []
for title in ["Customer Portal — Synthetic SOW", "Laboratory Inventory — Synthetic SOW", "Service Desk — Synthetic SOW"]:
    response = admin.post("/api/contracts/text", json={"title": title, "content": sow, "version": "1.0", "effective_date": "2026-09-01"})
    assert response.status_code == 201
    documents.append(response.json()["id"])
amendment = admin.post(f"/api/contracts/{documents[0]}/amendments/text", json={"title": "Reporting Amendment — Synthetic", "content": "2.1 Deliverable: Add a monthly sales export in CSV format.", "version": "1.1", "effective_date": "2026-09-02", "supersedes_clause_refs": []})
assert amendment.status_code == 201
tickets = []
for key, title, description, criteria in [
    ("DEMO-101", "Implement Stripe checkout", "Process contracted Stripe card payments and Stripe webhooks.", "A Stripe card payment updates the customer order."),
    ("DEMO-102", "Add native mobile applications", "Build native Android and iOS shopping applications.", "Customers can install native Android and iOS apps."),
    ("DEMO-103", "Quick tweak", "Please change it.", ""),
]:
    result = admin.post("/api/tickets", json={"contract_id": documents[0], "external_key": key, "title": title, "description": description, "acceptance_criteria": criteria, "estimated_hours": 24})
    assert result.status_code == 201
    tickets.append(result.json()["ticket"]["id"])
quote = admin.post(f"/api/tickets/{tickets[1]}/change-orders", json={"internal_hourly_cost": 80, "target_margin": 0.36})
assert quote.status_code == 201
for document in documents[:2]:
    result = admin.post("/api/approvals", json={"target_type": "CONTRACT", "target_id": document, "reason": "Synthetic demonstration: please review the scope and exclusions."})
    assert result.status_code == 201
pm = TestClient(app)
login = pm.post("/api/auth/login", json={"email": "pm@example.test", "password": password})
pm.headers["X-CSRF-Token"] = login.json()["csrf_token"]
assert pm.post("/api/approvals/1/decision", json={"decision": "APPROVED", "reason": "Synthetic demo review completed; scope and exclusions checked."}).status_code == 200
print("Disposable QA database seeded: 3 SOWs, 1 amendment, 3 tickets, 1 quote and 2 approval records.")
