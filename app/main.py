from __future__ import annotations

import json
import os
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.database import Database
from app.services.analyzer import AnalysisResult, analyze_ticket
from app.services.auth import create_session, hash_password, hash_token, is_expired, verify_password
from app.services.contracts import extract_pdf_text, split_into_clauses
from app.services.integrations import send_slack_message, verify_jira_signature, verify_slack_signature
from app.services.llm import review_with_openai
from app.services.pricing import calculate_price
from app.services.security import SlidingWindowLimiter, create_csrf_token, create_request_id
from app.services.approvals import install_approval_routes


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "scope_sentinel.db"
STATIC_INDEX = ROOT / "static" / "index.html"
STATIC_DOCUMENTS = ROOT / "static" / "documents.html"
STATIC_DOCUMENT_EDITOR = ROOT / "static" / "document.html"
STATIC_NEW_DOCUMENT = ROOT / "static" / "new_document.html"
STATIC_ADMINISTRATION = ROOT / "static" / "administration.html"
REALISTIC_SOW = ROOT / "sample_data" / "realistic_ecommerce_sow.txt"


class ContractTextCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    content: str = Field(min_length=20, max_length=1_000_000)
    version: str = Field(default="1.0", min_length=1, max_length=40)
    effective_date: Optional[str] = None


class AmendmentTextCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    content: str = Field(min_length=20, max_length=1_000_000)
    version: str = Field(min_length=1, max_length=40)
    effective_date: str
    supersedes_clause_refs: list[str] = Field(default_factory=list)


class TicketCreate(BaseModel):
    contract_id: int
    external_key: Optional[str] = Field(default=None, max_length=100)
    title: str = Field(min_length=3, max_length=300)
    description: str = ""
    acceptance_criteria: str = ""
    estimated_hours: Optional[float] = Field(default=None, gt=0, le=10000)


class ReviewCreate(BaseModel):
    reviewer: str = Field(min_length=2, max_length=150)
    decision: Literal["IN_SCOPE", "OUT_OF_SCOPE", "NEEDS_CLARIFICATION"]
    reason: str = Field(min_length=5, max_length=2000)


class ChangeOrderCreate(BaseModel):
    internal_hourly_cost: float = Field(gt=0, le=100000)
    target_margin: float = Field(default=0.36, ge=0, lt=0.90)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    timeline_days: Optional[int] = Field(default=None, gt=0, le=3650)


class BootstrapUserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=5, max_length=250)
    password: str = Field(min_length=12, max_length=500)


class UserCreate(BootstrapUserCreate):
    role: Literal["ADMIN", "PM", "DEVELOPER", "SALES", "VIEWER"]


class LoginCreate(BaseModel):
    email: str = Field(min_length=1, max_length=250)
    password: str = Field(min_length=1, max_length=500)


def create_app(db_path: str | Path | None = None) -> FastAPI:
    async def enforce_access(request: Request):
        path = request.url.path
        public = {"/api/auth/login", "/api/auth/bootstrap", "/api/auth/me",
                  "/api/security/csrf", "/api/system/status", "/api/security/status",
                  "/api/demo/realistic-sow", "/api/webhooks/jira", "/api/webhooks/slack"}
        if not path.startswith("/api/") or path in public:
            return
        roles = {"ADMIN", "PM", "DEVELOPER", "SALES", "VIEWER"}
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if path == "/api/auth/logout":
                pass
            elif path.startswith("/api/users"):
                roles = {"ADMIN"}
            elif path.startswith("/api/contracts"):
                roles = {"ADMIN", "PM"}
            elif path.startswith("/api/approvals"):
                roles = {"ADMIN", "PM", "SALES"}
            elif path.endswith("/review"):
                roles = {"ADMIN", "PM"}
            elif path.endswith("/change-orders"):
                roles = {"ADMIN", "PM", "SALES"}
            elif path == "/api/tickets" or path.endswith("/reanalyze"):
                roles = {"ADMIN", "PM", "DEVELOPER"}
            else:
                roles = set()
        if path == "/api/security/audit-events":
            roles = {"ADMIN"}
        _authorize(database, request, auth_required, roles)

    app = FastAPI(
        title="SOW Scope Sentinel",
        version="0.1.0",
        description="Evidence-based contract scope checking and change-order drafting.",
        dependencies=[Depends(enforce_access)],
    )
    app.mount("/assets", StaticFiles(directory=ROOT / "static" / "assets"), name="assets")
    database = Database(db_path or os.getenv("SCOPE_SENTINEL_DB", str(DEFAULT_DB)))
    database.initialize()
    app.state.database = database
    auth_required = os.getenv("SCOPE_SENTINEL_AUTH_REQUIRED", "true").lower() == "true"
    secure_cookies = os.getenv("SCOPE_SENTINEL_SECURE_COOKIES", "true").lower() == "true"
    allowed_hosts = [item.strip() for item in os.getenv(
        "SCOPE_SENTINEL_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver"
    ).split(",") if item.strip()]
    allowed_origins = {item.strip() for item in os.getenv(
        "SCOPE_SENTINEL_ALLOWED_ORIGINS", "https://127.0.0.1:8443,https://localhost:8443"
    ).split(",") if item.strip()}
    login_limiter = SlidingWindowLimiter(
        int(os.getenv("SCOPE_SENTINEL_LOGIN_RATE_LIMIT", "20")), 60
    )
    lockout_attempts = int(os.getenv("SCOPE_SENTINEL_LOCKOUT_ATTEMPTS", "5"))
    lockout_minutes = int(os.getenv("SCOPE_SENTINEL_LOCKOUT_MINUTES", "15"))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        request_id = create_request_id()
        request.state.request_id = request_id
        origin = request.headers.get("origin")
        unsafe = request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
        webhook = request.url.path.startswith("/api/webhooks/")
        if secure_cookies and request.url.scheme != "https":
            response = JSONResponse(
                {"detail": "HTTPS is required. Start the app with scripts/run_secure.py and use https://localhost:8443."},
                status_code=426,
            )
        elif unsafe and origin and origin not in allowed_origins:
            response = JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
        elif (
            unsafe and auth_required and request.cookies.get("scope_session") and not webhook
        ):
            cookie_token = request.cookies.get("scope_csrf") or ""
            header_token = request.headers.get("X-CSRF-Token") or ""
            expected_token = hash_token("csrf:" + request.cookies["scope_session"])
            if not cookie_token or not hmac.compare_digest(cookie_token, header_token) or not hmac.compare_digest(expected_token, header_token):
                response = JSONResponse({"detail": "CSRF validation failed."}, status_code=403)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; "
            "form-action 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'"
        )
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_INDEX)

    @app.get("/administration", include_in_schema=False)
    def administration() -> FileResponse:
        return FileResponse(STATIC_ADMINISTRATION)

    @app.get("/approvals", include_in_schema=False)
    def approvals_page() -> FileResponse:
        return FileResponse(ROOT / "static" / "approvals.html")

    @app.get("/documents", include_in_schema=False)
    def document_library() -> FileResponse:
        return FileResponse(STATIC_DOCUMENTS)

    @app.get("/documents/new", include_in_schema=False)
    def new_document() -> FileResponse:
        return FileResponse(STATIC_NEW_DOCUMENT)

    @app.get("/documents/{document_id}", include_in_schema=False)
    def document_editor(document_id: int) -> FileResponse:
        return FileResponse(STATIC_DOCUMENT_EDITOR)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/system/status")
    def system_status() -> dict[str, Any]:
        return {
            "status": "ok",
            "auth_required": auth_required,
            "llm_enabled": bool(os.getenv("OPENAI_API_KEY") and os.getenv("SCOPE_SENTINEL_LLM_MODEL")),
            "slack_enabled": bool(os.getenv("SLACK_BOT_TOKEN") and os.getenv("SLACK_CHANNEL_ID")),
        }

    @app.get("/api/security/csrf")
    def csrf_token(request: Request, response: Response) -> dict[str, str]:
        session = request.cookies.get("scope_session")
        token = hash_token("csrf:" + session) if session else create_csrf_token()
        response.set_cookie(
            "scope_csrf",
            token,
            httponly=False,
            secure=secure_cookies,
            samesite="strict",
            max_age=12 * 60 * 60,
            path="/",
        )
        return {"csrf_token": token}

    @app.get("/api/security/status")
    def security_status() -> dict[str, Any]:
        return {
            "security_headers": True,
            "trusted_hosts": True,
            "csrf_protection": auth_required,
            "secure_cookies": secure_cookies,
            "login_rate_limit_per_minute": login_limiter.limit,
            "account_lockout_attempts": lockout_attempts,
            "account_lockout_minutes": lockout_minutes,
            "upload_limit_mb": int(os.getenv("SCOPE_SENTINEL_MAX_UPLOAD_MB", "10")),
            "audit_logging": True,
        }

    @app.get("/api/security/audit-events")
    def security_audit_events(
        request: Request, limit: int = Query(default=100, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        _authorize(database, request, auth_required, {"ADMIN"})
        with database.connection() as connection:
            rows = connection.execute(
                """SELECT id, event_type, outcome, actor_user_id, subject, ip_address,
                          request_id, details, created_at
                   FROM security_audit_events ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            try:
                event["details"] = json.loads(event["details"] or "{}")
            except json.JSONDecodeError:
                event["details"] = {}
            events.append(event)
        return events

    @app.post("/api/auth/bootstrap", status_code=201)
    def bootstrap_user(
        payload: BootstrapUserCreate, request: Request, response: Response
    ) -> dict[str, Any]:
        configured_token = os.getenv("SCOPE_SENTINEL_BOOTSTRAP_TOKEN")
        if secure_cookies and not configured_token:
            raise HTTPException(503, "Configure the initial administrator setup token on the server.")
        if configured_token and not hmac.compare_digest(
            request.headers.get("X-Bootstrap-Token", ""), configured_token
        ):
            raise HTTPException(403, "A valid administrator setup token is required.")
        with database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
                raise HTTPException(409, "The first administrator has already been created.")
            try:
                encoded = hash_password(payload.password)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            cursor = connection.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'ADMIN')",
                (payload.name, payload.email.lower(), encoded),
            )
            user_id = int(cursor.lastrowid)
        _security_audit(
            database, request, "ADMIN_BOOTSTRAP", "SUCCESS", user_id, payload.email.lower()
        )
        return _start_user_session(database, response, user_id, payload.name, payload.email.lower(), "ADMIN")

    @app.post("/api/auth/login")
    def login(payload: LoginCreate, request: Request, response: Response) -> dict[str, Any]:
        email = payload.email.strip().lower()
        client_ip = _client_ip(request)
        limiter_key = client_ip
        allowed, retry_after = login_limiter.check(limiter_key)
        if not allowed:
            _security_audit(database, request, "LOGIN_RATE_LIMITED", "BLOCKED", None, email)
            raise HTTPException(
                429, "Too many login attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        with database.connection() as connection:
            user = connection.execute(
                "SELECT * FROM users WHERE email = ? AND active = 1", (email,)
            ).fetchone()
        now = datetime.now(timezone.utc)
        if user is not None and user["locked_until"]:
            try:
                locked_until = datetime.fromisoformat(str(user["locked_until"]))
            except ValueError:
                locked_until = now
            if locked_until > now:
                wait_seconds = max(1, int((locked_until - now).total_seconds()))
                _security_audit(
                    database, request, "LOGIN_ACCOUNT_LOCKED", "BLOCKED", int(user["id"]), email
                )
                raise HTTPException(
                    423, "Account temporarily locked after repeated failed logins.",
                    headers={"Retry-After": str(wait_seconds)},
                )
        if user is None or not verify_password(payload.password, str(user["password_hash"])):
            actor_id = int(user["id"]) if user is not None else None
            if user is not None:
                failures = (0 if user["locked_until"] else int(user["failed_login_attempts"] or 0)) + 1
                locked_until_value = None
                if failures >= lockout_attempts:
                    locked_until_value = (now + timedelta(minutes=lockout_minutes)).isoformat()
                with database.connection() as connection:
                    connection.execute(
                        "UPDATE users SET failed_login_attempts = ?, locked_until = ? WHERE id = ?",
                        (failures, locked_until_value, user["id"]),
                    )
            _security_audit(database, request, "LOGIN", "FAILURE", actor_id, email)
            raise HTTPException(401, "Invalid email or password.")
        with database.connection() as connection:
            connection.execute(
                "UPDATE users SET failed_login_attempts = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
                (now.isoformat(), user["id"]),
            )
        _security_audit(database, request, "LOGIN", "SUCCESS", int(user["id"]), email)
        return _start_user_session(
            database, response, int(user["id"]), str(user["name"]), str(user["email"]), str(user["role"])
        )

    @app.post("/api/users", status_code=201)
    def create_user(payload: UserCreate, request: Request) -> dict[str, Any]:
        actor = _authorize(database, request, True, {"ADMIN"})
        try:
            encoded = hash_password(payload.password)
            with database.connection() as connection:
                cursor = connection.execute(
                    "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                    (payload.name, payload.email.lower(), encoded, payload.role),
                )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(409, "A user with this email already exists.") from exc
            raise
        user_id = int(cursor.lastrowid)
        _security_audit(
            database, request, "USER_CREATE", "SUCCESS", int(actor["id"]), payload.email.lower(),
            {"created_user_id": user_id, "role": payload.role},
        )
        return {"id": user_id, "name": payload.name, "email": payload.email.lower(), "role": payload.role}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        user = _current_user(database, request)
        token = request.cookies.get("scope_session")
        if token:
            with database.connection() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
        if user:
            _security_audit(
                database, request, "LOGOUT", "SUCCESS", int(user["id"]), str(user["email"])
            )
        response.delete_cookie(
            "scope_session", path="/", secure=secure_cookies, httponly=True, samesite="strict"
        )
        response.delete_cookie(
            "scope_csrf", path="/", secure=secure_cookies, httponly=False, samesite="strict"
        )
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(request: Request) -> dict[str, Any]:
        user = _current_user(database, request)
        if user is None:
            if auth_required:
                raise HTTPException(401, "Authentication required.")
            return {"authenticated": False, "role": "LOCAL_DEMO"}
        return {"authenticated": True, **user}

    @app.get("/api/demo/realistic-sow")
    def realistic_sow() -> dict[str, str]:
        return {
            "title": "Northstar D2C Commerce Platform SOW",
            "content": REALISTIC_SOW.read_text(encoding="utf-8"),
            "notice": "Synthetic demonstration data; not legal advice or a legal template.",
        }

    @app.post("/api/contracts/text", status_code=201)
    def create_text_contract(payload: ContractTextCreate) -> dict[str, Any]:
        return _save_contract(
            database, payload.title, payload.content, None, version=payload.version,
            effective_date=payload.effective_date,
        )

    @app.post("/api/contracts/{contract_id}/amendments/text", status_code=201)
    def create_text_amendment(contract_id: int, payload: AmendmentTextCreate) -> dict[str, Any]:
        root = _root_contract(database, contract_id)
        return _save_contract(
            database,
            payload.title,
            payload.content,
            None,
            parent_contract_id=int(root["id"]),
            version=payload.version,
            document_type="AMENDMENT",
            effective_date=payload.effective_date,
            supersedes_clause_refs=payload.supersedes_clause_refs,
        )

    @app.post("/api/contracts/{contract_id}/revisions/text", status_code=201)
    def create_full_revision(contract_id: int, payload: ContractTextCreate) -> dict[str, Any]:
        """Create a new effective revision without overwriting a prior signed SOW."""
        root = _root_contract(database, contract_id)
        superseded = [clause["clause_ref"] for clause in _effective_clauses(database, int(root["id"]))]
        return _save_contract(
            database,
            payload.title,
            payload.content,
            None,
            parent_contract_id=int(root["id"]),
            version=payload.version,
            document_type="AMENDMENT",
            effective_date=payload.effective_date,
            supersedes_clause_refs=superseded,
        )

    @app.post("/api/contracts/upload", status_code=201)
    async def upload_contract(
        title: str = Query(min_length=3, max_length=200),
        version: str = Query(default="1.0", min_length=1, max_length=40),
        effective_date: Optional[str] = Query(default=None),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        filename = file.filename or "contract"
        filename = Path(filename).name
        max_upload_bytes = int(os.getenv("SCOPE_SENTINEL_MAX_UPLOAD_MB", "10")) * 1024 * 1024
        data = await file.read(max_upload_bytes + 1)
        if len(data) > max_upload_bytes:
            raise HTTPException(413, "The uploaded contract exceeds the configured size limit.")
        if not data:
            raise HTTPException(400, "The uploaded file is empty.")
        try:
            if filename.lower().endswith(".pdf"):
                content = extract_pdf_text(data)
            elif filename.lower().endswith((".txt", ".md")):
                content = data.decode("utf-8")
            else:
                raise HTTPException(415, "Upload a PDF, TXT, or Markdown contract.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, f"Could not extract contract text: {exc}") from exc
        if len(content.strip()) < 20:
            raise HTTPException(422, "No usable text was extracted from the contract.")
        return _save_contract(
            database, title, content, filename, version=version, effective_date=effective_date
        )

    @app.get("/api/contracts")
    def list_contracts(include_deleted: bool = Query(default=False)) -> list[dict[str, Any]]:
        where = "" if include_deleted else "WHERE c.status != 'DELETED'"
        with database.connection() as connection:
            rows = connection.execute(
                f"""SELECT c.id, c.title, c.source_filename, c.parent_contract_id, c.version,
                           c.document_type, c.effective_date, c.status, c.created_at,
                           COUNT(cl.id) AS clause_count
                    FROM contracts c LEFT JOIN clauses cl ON cl.contract_id = c.id
                    {where}
                    GROUP BY c.id ORDER BY c.id DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    @app.delete("/api/contracts/{contract_id}")
    def delete_contract(contract_id: int, request: Request) -> dict[str, Any]:
        """Soft-delete a document while retaining its audit and ticket history."""
        actor = _authorize(database, request, auth_required, {"ADMIN", "PM"})
        contract = _require_contract(database, contract_id)
        with database.connection() as connection:
            if contract["parent_contract_id"] is None:
                cursor = connection.execute(
                    "UPDATE contracts SET status = 'DELETED' WHERE id = ? OR parent_contract_id = ?",
                    (contract_id, contract_id),
                )
            else:
                cursor = connection.execute(
                    "UPDATE contracts SET status = 'DELETED' WHERE id = ?", (contract_id,)
                )
        _security_audit(
            database, request, "CONTRACT_DELETE", "SUCCESS",
            int(actor["id"]) if actor else None, str(contract_id),
            {"affected_documents": cursor.rowcount, "soft_delete": True},
        )
        return {
            "id": contract_id,
            "status": "DELETED",
            "deleted_documents": cursor.rowcount,
            "audit_history_preserved": True,
        }

    @app.post("/api/contracts/{contract_id}/restore")
    def restore_contract(contract_id: int, request: Request) -> dict[str, Any]:
        actor = _authorize(database, request, auth_required, {"ADMIN", "PM"})
        contract = _require_contract(database, contract_id)
        with database.connection() as connection:
            if contract["parent_contract_id"] is None:
                cursor = connection.execute(
                    "UPDATE contracts SET status = 'ACTIVE' WHERE id = ? OR parent_contract_id = ?",
                    (contract_id, contract_id),
                )
            else:
                cursor = connection.execute(
                    "UPDATE contracts SET status = 'ACTIVE' WHERE id = ?", (contract_id,)
                )
        _security_audit(
            database, request, "CONTRACT_RESTORE", "SUCCESS",
            int(actor["id"]) if actor else None, str(contract_id),
            {"affected_documents": cursor.rowcount},
        )
        return {"id": contract_id, "status": "ACTIVE", "restored_documents": cursor.rowcount}

    @app.get("/api/contracts/{contract_id}")
    def get_contract(contract_id: int) -> dict[str, Any]:
        contract = _require_contract(database, contract_id)
        root = _root_contract(database, contract_id)
        with database.connection() as connection:
            revisions = connection.execute(
                """SELECT id, title, version, document_type, effective_date, status, source_filename,
                          supersedes_clause_refs, created_at
                   FROM contracts WHERE id = ? OR parent_contract_id = ?
                   ORDER BY COALESCE(effective_date, ''), id""",
                (root["id"], root["id"]),
            ).fetchall()
        result = dict(contract)
        result["root_contract_id"] = root["id"]
        result["revisions"] = [dict(row) for row in revisions]
        return result

    @app.get("/api/contracts/{contract_id}/clauses")
    def list_clauses(contract_id: int) -> list[dict[str, Any]]:
        _require_contract(database, contract_id)
        with database.connection() as connection:
            rows = connection.execute(
                "SELECT id, clause_ref, category, text, ordinal FROM clauses WHERE contract_id = ? ORDER BY ordinal",
                (contract_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get("/api/contracts/{contract_id}/effective-clauses")
    def list_effective_clauses(contract_id: int) -> list[dict[str, Any]]:
        return [dict(row) for row in _effective_clauses(database, contract_id)]

    @app.post("/api/tickets", status_code=201)
    def create_ticket(payload: TicketCreate) -> dict[str, Any]:
        root = _root_contract(database, payload.contract_id)
        with database.connection() as connection:
            cursor = connection.execute(
                """INSERT INTO tickets
                   (contract_id, external_key, title, description, acceptance_criteria, estimated_hours)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    root["id"],
                    payload.external_key,
                    payload.title,
                    payload.description,
                    payload.acceptance_criteria,
                    payload.estimated_hours,
                ),
            )
            ticket_id = cursor.lastrowid
        return _run_and_store_analysis(database, int(ticket_id))

    @app.post("/api/webhooks/jira", status_code=201)
    async def jira_webhook(request: Request, contract_id: int = Query(gt=0)) -> dict[str, Any]:
        raw_body = await request.body()
        jira_secret = os.getenv("JIRA_WEBHOOK_SECRET")
        if not jira_secret:
            raise HTTPException(503, "Jira request verification is not configured.")
        if jira_secret and not verify_jira_signature(
            raw_body, request.headers.get("X-Hub-Signature"), jira_secret
        ):
            raise HTTPException(401, "Invalid Jira webhook signature.")
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "Invalid Jira webhook JSON.") from exc
        issue = payload.get("issue") or {}
        fields = issue.get("fields") or {}
        ticket = TicketCreate(
            contract_id=contract_id,
            external_key=str(issue.get("key") or "") or None,
            title=str(fields.get("summary") or "Untitled Jira ticket"),
            description=_flatten_jira_text(fields.get("description")),
            acceptance_criteria=_flatten_jira_text(
                fields.get("acceptanceCriteria") or fields.get("customfield_acceptance_criteria")
            ),
        )
        return create_ticket(ticket)

    @app.post("/api/webhooks/slack")
    async def slack_webhook(request: Request) -> dict[str, Any]:
        raw_body = await request.body()
        slack_secret = os.getenv("SLACK_SIGNING_SECRET")
        if not slack_secret:
            raise HTTPException(503, "Slack request verification is not configured.")
        if not verify_slack_signature(
            raw_body,
            request.headers.get("X-Slack-Request-Timestamp"),
            request.headers.get("X-Slack-Signature"),
            slack_secret,
        ):
            raise HTTPException(401, "Invalid or expired Slack signature.")
        payload = json.loads(raw_body)
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge")}
        return {"ok": True}

    @app.get("/api/tickets")
    def list_tickets() -> list[dict[str, Any]]:
        with database.connection() as connection:
            rows = connection.execute(
                """SELECT t.*, a.id AS analysis_id, a.decision, a.confidence, a.reason
                   FROM tickets t
                   LEFT JOIN analyses a ON a.id = (
                       SELECT id FROM analyses WHERE ticket_id = t.id ORDER BY id DESC LIMIT 1
                   )
                   ORDER BY t.id DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get("/api/history")
    def history(contract_id: Optional[int] = Query(default=None, gt=0)) -> list[dict[str, Any]]:
        """Compact audit list suitable for the dashboard history screen."""
        sql = """SELECT t.id, t.external_key, t.title, t.status, t.estimated_hours, t.created_at,
                        c.id AS contract_id, c.title AS contract_title, c.version AS contract_version,
                        a.decision, a.confidence, a.reason, a.created_at AS analysed_at,
                        (SELECT COUNT(*) FROM analyses x WHERE x.ticket_id = t.id) AS analysis_count,
                        (SELECT COUNT(*) FROM review_decisions r WHERE r.ticket_id = t.id) AS review_count,
                        (SELECT COUNT(*) FROM change_orders o WHERE o.ticket_id = t.id) AS change_order_count
                 FROM tickets t JOIN contracts c ON c.id = t.contract_id
                 LEFT JOIN analyses a ON a.id = (
                     SELECT id FROM analyses WHERE ticket_id = t.id ORDER BY id DESC LIMIT 1
                 )"""
        parameters: tuple[Any, ...] = ()
        if contract_id is not None:
            root = _root_contract(database, contract_id)
            sql += " WHERE t.contract_id = ?"
            parameters = (root["id"],)
        sql += " ORDER BY t.id DESC"
        with database.connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    @app.get("/api/dashboard/review-queue")
    def review_queue(request: Request) -> list[dict[str, Any]]:
        _authorize(database, request, auth_required, {"ADMIN", "PM", "SALES", "VIEWER"})
        with database.connection() as connection:
            rows = connection.execute(
                """SELECT t.id, t.external_key, t.title, t.estimated_hours, t.status, t.created_at,
                          c.title AS contract_title, a.decision, a.confidence, a.reason
                   FROM tickets t JOIN contracts c ON c.id = t.contract_id
                   JOIN analyses a ON a.id = (
                       SELECT id FROM analyses WHERE ticket_id = t.id ORDER BY id DESC LIMIT 1
                   )
                   WHERE t.status IN ('OUT_OF_SCOPE', 'NEEDS_REVIEW', 'NEEDS_CLARIFICATION')
                   ORDER BY t.id DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get("/api/tickets/{ticket_id}/analysis")
    def get_analysis(ticket_id: int) -> dict[str, Any]:
        return _analysis_response(database, ticket_id)

    @app.get("/api/tickets/{ticket_id}/history")
    def ticket_history(ticket_id: int) -> dict[str, Any]:
        ticket = _require_ticket(database, ticket_id)
        with database.connection() as connection:
            analysis_rows = connection.execute(
                "SELECT * FROM analyses WHERE ticket_id = ? ORDER BY id DESC", (ticket_id,)
            ).fetchall()
            analyses = []
            for analysis in analysis_rows:
                evidence = connection.execute(
                    """SELECT e.score, e.relationship, e.explanation, c.clause_ref, c.category,
                              c.text AS clause_text, d.version AS contract_version, d.document_type
                       FROM analysis_evidence e
                       JOIN clauses c ON c.id = e.clause_id
                       JOIN contracts d ON d.id = c.contract_id
                       WHERE e.analysis_id = ? ORDER BY e.score DESC""",
                    (analysis["id"],),
                ).fetchall()
                analyses.append({**dict(analysis), "evidence": [dict(row) for row in evidence]})
            reviews = connection.execute(
                "SELECT reviewer, decision, reason, created_at FROM review_decisions WHERE ticket_id = ? ORDER BY id DESC",
                (ticket_id,),
            ).fetchall()
            change_orders = connection.execute(
                """SELECT id, currency, estimated_hours, timeline_days, price, status, draft_text, created_at
                   FROM change_orders WHERE ticket_id = ? ORDER BY id DESC""",
                (ticket_id,),
            ).fetchall()
        return {
            "ticket": dict(ticket),
            "analyses": analyses,
            "reviews": [dict(row) for row in reviews],
            "change_orders": [dict(row) for row in change_orders],
        }

    @app.post("/api/tickets/{ticket_id}/reanalyze")
    def reanalyze(ticket_id: int) -> dict[str, Any]:
        _require_ticket(database, ticket_id)
        return _run_and_store_analysis(database, ticket_id)

    @app.post("/api/tickets/{ticket_id}/review", status_code=201)
    def review_ticket(ticket_id: int, payload: ReviewCreate, request: Request) -> dict[str, Any]:
        user = _authorize(database, request, auth_required, {"ADMIN", "PM"})
        _require_ticket(database, ticket_id)
        reviewer = str(user["name"]) if user else payload.reviewer
        with database.connection() as connection:
            connection.execute(
                "INSERT INTO review_decisions (ticket_id, reviewer, decision, reason) VALUES (?, ?, ?, ?)",
                (ticket_id, reviewer, payload.decision, payload.reason),
            )
            connection.execute("UPDATE tickets SET status = ? WHERE id = ?", (payload.decision, ticket_id))
        return {
            "ticket_id": ticket_id,
            "status": payload.decision,
            "reviewed_by": reviewer,
            "reason": payload.reason,
        }

    @app.post("/api/tickets/{ticket_id}/change-orders", status_code=201)
    def create_change_order(ticket_id: int, payload: ChangeOrderCreate, request: Request) -> dict[str, Any]:
        _authorize(database, request, auth_required, {"ADMIN", "PM", "SALES"})
        ticket = _require_ticket(database, ticket_id)
        analysis = _latest_analysis(database, ticket_id)
        if analysis["decision"] == "IN_SCOPE" and ticket["status"] != "OUT_OF_SCOPE":
            raise HTTPException(409, "An in-scope ticket does not require a change order.")
        hours = ticket["estimated_hours"]
        if hours is None:
            raise HTTPException(422, "Add estimated_hours to the ticket before generating a change order.")

        try:
            estimate = calculate_price(
                float(hours), payload.internal_hourly_cost, payload.target_margin, payload.timeline_days
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

        with database.connection() as connection:
            contract = connection.execute(
                "SELECT title FROM contracts WHERE id = ?", (ticket["contract_id"],)
            ).fetchone()
        draft = _change_order_draft(
            ticket=dict(ticket),
            contract_title=str(contract["title"]),
            reason=str(analysis["reason"]),
            currency=payload.currency.upper(),
            price=estimate.price,
            hours=float(hours),
            days=estimate.timeline_days,
        )
        with database.connection() as connection:
            cursor = connection.execute(
                """INSERT INTO change_orders
                   (ticket_id, analysis_id, currency, internal_hourly_cost, target_margin,
                    estimated_hours, timeline_days, price, draft_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticket_id,
                    analysis["id"],
                    payload.currency.upper(),
                    payload.internal_hourly_cost,
                    payload.target_margin,
                    hours,
                    estimate.timeline_days,
                    estimate.price,
                    draft,
                ),
            )
            change_order_id = cursor.lastrowid
        return {
            "id": change_order_id,
            "ticket_id": ticket_id,
            "status": "DRAFT",
            "currency": payload.currency.upper(),
            "estimated_cost": estimate.estimated_cost,
            "price": estimate.price,
            "timeline_days": estimate.timeline_days,
            "draft_text": draft,
        }

    install_approval_routes(app, database, lambda request, roles: _authorize(database, request, True, roles))
    return app


def _save_contract(
    database: Database,
    title: str,
    content: str,
    filename: str | None,
    *,
    parent_contract_id: int | None = None,
    version: str = "1.0",
    document_type: str = "SOW",
    effective_date: str | None = None,
    supersedes_clause_refs: list[str] | None = None,
) -> dict[str, Any]:
    clauses = split_into_clauses(content)
    if not clauses:
        raise HTTPException(422, "No contract clauses could be extracted.")
    with database.connection() as connection:
        cursor = connection.execute(
            """INSERT INTO contracts
               (title, source_filename, content, parent_contract_id, version, document_type,
                effective_date, supersedes_clause_refs)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                title,
                filename,
                content,
                parent_contract_id,
                version,
                document_type,
                effective_date,
                json.dumps(supersedes_clause_refs or []),
            ),
        )
        contract_id = int(cursor.lastrowid)
        connection.executemany(
            "INSERT INTO clauses (contract_id, clause_ref, category, text, ordinal) VALUES (?, ?, ?, ?, ?)",
            [(contract_id, clause.reference, clause.category, clause.text, clause.ordinal) for clause in clauses],
        )
    return {
        "id": contract_id,
        "title": title,
        "source_filename": filename,
        "parent_contract_id": parent_contract_id,
        "version": version,
        "document_type": document_type,
        "effective_date": effective_date,
        "supersedes_clause_refs": supersedes_clause_refs or [],
        "clause_count": len(clauses),
        "categories": sorted({clause.category for clause in clauses}),
    }


def _run_and_store_analysis(database: Database, ticket_id: int) -> dict[str, Any]:
    ticket = _require_ticket(database, ticket_id)
    clauses = _effective_clauses(database, int(ticket["contract_id"]))
    ticket_text = " ".join(
        str(ticket[field]) for field in ("title", "description", "acceptance_criteria") if ticket[field]
    )
    result = analyze_ticket(
        str(ticket["title"]),
        str(ticket["description"]),
        str(ticket["acceptance_criteria"]),
        clauses,
    )
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("SCOPE_SENTINEL_LLM_MODEL")
    if api_key and model:
        try:
            result = review_with_openai(ticket_text, clauses, api_key, model, result)
        except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError):
            # Contract enforcement must remain available when the optional model is unavailable.
            pass
    _persist_analysis(database, ticket_id, result)
    return _analysis_response(database, ticket_id)


def _persist_analysis(database: Database, ticket_id: int, result: AnalysisResult) -> None:
    with database.connection() as connection:
        cursor = connection.execute(
            "INSERT INTO analyses (ticket_id, decision, confidence, reason) VALUES (?, ?, ?, ?)",
            (ticket_id, result.decision, result.confidence, result.reason),
        )
        analysis_id = int(cursor.lastrowid)
        connection.executemany(
            """INSERT INTO analysis_evidence
               (analysis_id, clause_id, score, relationship, explanation)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (analysis_id, item.clause_id, item.score, item.relationship, item.explanation)
                for item in result.evidence
            ],
        )
        connection.execute("UPDATE tickets SET status = ? WHERE id = ?", (result.decision, ticket_id))


def _analysis_response(database: Database, ticket_id: int) -> dict[str, Any]:
    ticket = _require_ticket(database, ticket_id)
    analysis = _latest_analysis(database, ticket_id)
    with database.connection() as connection:
        rows = connection.execute(
            """SELECT e.score, e.relationship, e.explanation,
                      c.clause_ref, c.category, c.text AS clause_text,
                      d.title AS contract_title, d.version AS contract_version,
                      d.document_type
               FROM analysis_evidence e JOIN clauses c ON c.id = e.clause_id
               JOIN contracts d ON d.id = c.contract_id
               WHERE e.analysis_id = ? ORDER BY e.score DESC""",
            (analysis["id"],),
        ).fetchall()
    return {
        "ticket": dict(ticket),
        "analysis": dict(analysis),
        "evidence": [dict(row) for row in rows],
    }


def _require_contract(database: Database, contract_id: int):
    with database.connection() as connection:
        row = connection.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Contract not found.")
    return row


def _root_contract(database: Database, contract_id: int):
    contract = _require_contract(database, contract_id)
    if contract["parent_contract_id"] is not None:
        return _require_contract(database, int(contract["parent_contract_id"]))
    return contract


def _effective_clauses(database: Database, contract_id: int) -> list[dict[str, Any]]:
    root = _root_contract(database, contract_id)
    with database.connection() as connection:
        documents = connection.execute(
            """SELECT * FROM contracts
               WHERE status = 'ACTIVE' AND (id = ? OR parent_contract_id = ?)
               ORDER BY COALESCE(effective_date, ''), id""",
            (root["id"], root["id"]),
        ).fetchall()
        effective: list[dict[str, Any]] = []
        for document in documents:
            try:
                superseded = set(json.loads(document["supersedes_clause_refs"] or "[]"))
            except json.JSONDecodeError:
                superseded = set()
            if superseded:
                effective = [item for item in effective if item["clause_ref"] not in superseded]
            rows = connection.execute(
                "SELECT id, clause_ref, category, text FROM clauses WHERE contract_id = ? ORDER BY ordinal",
                (document["id"],),
            ).fetchall()
            for row in rows:
                item = dict(row)
                item.update(
                    contract_id=document["id"],
                    contract_title=document["title"],
                    contract_version=document["version"],
                    document_type=document["document_type"],
                )
                effective.append(item)
    return effective


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _security_audit(
    database: Database,
    request: Request,
    event_type: str,
    outcome: str,
    actor_user_id: int | None,
    subject: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    with database.connection() as connection:
        connection.execute(
            """INSERT INTO security_audit_events
               (event_type, outcome, actor_user_id, subject, ip_address, request_id, details)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event_type,
                outcome,
                actor_user_id,
                subject,
                _client_ip(request),
                getattr(request.state, "request_id", None),
                json.dumps(details or {}, separators=(",", ":")),
            ),
        )


def _current_user(database: Database, request: Request) -> dict[str, Any] | None:
    token = request.cookies.get("scope_session")
    if not token:
        return None
    with database.connection() as connection:
        row = connection.execute(
            """SELECT u.id, u.name, u.email, u.role, s.expires_at
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND u.active = 1""",
            (hash_token(token),),
        ).fetchone()
        if row and is_expired(str(row["expires_at"])):
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
            return None
    return dict(row) if row else None


def _authorize(
    database: Database,
    request: Request,
    auth_required: bool,
    roles: set[str],
) -> dict[str, Any] | None:
    user = _current_user(database, request)
    if user is None:
        if auth_required:
            raise HTTPException(401, "Authentication required.")
        return None
    if str(user["role"]) not in roles:
        raise HTTPException(403, "Your role is not allowed to perform this action.")
    return user


def _start_user_session(
    database: Database,
    response: Response,
    user_id: int,
    name: str,
    email: str,
    role: str,
) -> dict[str, Any]:
    session = create_session()
    with database.connection() as connection:
        connection.execute(
            "DELETE FROM sessions WHERE expires_at <= ?", (datetime.now(timezone.utc).isoformat(),)
        )
        connection.execute(
            "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, session.token_hash, session.expires_at),
        )
        max_sessions = max(1, int(os.getenv("SCOPE_SENTINEL_MAX_SESSIONS_PER_USER", "5")))
        connection.execute(
            """DELETE FROM sessions WHERE user_id = ? AND id NOT IN (
                   SELECT id FROM sessions WHERE user_id = ? ORDER BY id DESC LIMIT ?
               )""",
            (user_id, user_id, max_sessions),
        )
    secure_cookies = os.getenv("SCOPE_SENTINEL_SECURE_COOKIES", "true").lower() == "true"
    response.set_cookie(
        "scope_session",
        session.raw,
        httponly=True,
        samesite="strict",
        secure=secure_cookies,
        max_age=12 * 60 * 60,
        path="/",
    )
    csrf_token = hash_token("csrf:" + session.raw)
    response.set_cookie(
        "scope_csrf", csrf_token, httponly=False, samesite="strict", secure=secure_cookies,
        max_age=12 * 60 * 60, path="/",
    )
    return {
        "authenticated": True,
        "id": user_id,
        "name": name,
        "email": email,
        "role": role,
        "csrf_token": csrf_token,
    }


def _require_ticket(database: Database, ticket_id: int):
    with database.connection() as connection:
        row = connection.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Ticket not found.")
    return row


def _latest_analysis(database: Database, ticket_id: int):
    with database.connection() as connection:
        row = connection.execute(
            "SELECT * FROM analyses WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "No analysis exists for this ticket.")
    return row


def _flatten_jira_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_flatten_jira_text(item) for item in value)
    if isinstance(value, dict):
        own_text = str(value.get("text") or "")
        children = _flatten_jira_text(value.get("content") or [])
        return f"{own_text} {children}".strip()
    return str(value)


def _change_order_draft(
    ticket: dict[str, Any],
    contract_title: str,
    reason: str,
    currency: str,
    price: float,
    hours: float,
    days: int,
) -> str:
    reference = ticket.get("external_key") or f"Internal ticket {ticket['id']}"
    return f"""CHANGE-ORDER PROPOSAL — DRAFT

Contract: {contract_title}
Request: {reference} — {ticket['title']}

Requested change
{ticket['description'] or ticket['title']}

Scope assessment
{reason}

Commercial and schedule impact
- Estimated engineering effort: {hours:g} hours
- Estimated timeline impact: {days} working day(s)
- Proposed fixed price: {currency} {price:,.2f}

Acceptance criteria
{ticket['acceptance_criteria'] or 'To be agreed with the client before work begins.'}

This document is a draft. Work will begin only after authorized client approval.
"""


app = create_app()
