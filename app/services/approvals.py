"""Internal, single-reviewer approvals. Not company deployment approval or e-signature."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, Field


class ApprovalSubmission(BaseModel):
    target_type: Literal["CONTRACT", "CHANGE_ORDER"]
    target_id: int = Field(gt=0)
    reason: str = Field(min_length=5, max_length=2000)


class ApprovalDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=5, max_length=2000)


def target_snapshot(connection, kind, target_id):
    if kind == "CONTRACT":
        row = connection.execute("SELECT * FROM contracts WHERE id = ? AND status = 'ACTIVE'", (target_id,)).fetchone()
        if not row:
            raise HTTPException(409, "The document is missing or deleted; it cannot be approved.")
        fields = ("id", "title", "content", "version", "document_type", "effective_date", "parent_contract_id", "supersedes_clause_refs")
        return {key: row[key] for key in fields}
    row = connection.execute("SELECT * FROM change_orders WHERE id = ?", (target_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Change-order draft not found.")
    contract = connection.execute("SELECT c.status FROM contracts c JOIN tickets t ON t.contract_id=c.id WHERE t.id=?", (row["ticket_id"],)).fetchone()
    if not contract or contract["status"] != "ACTIVE":
        raise HTTPException(409, "The draft's parent contract is unavailable.")
    return {key: row[key] for key in row.keys() if key != "status"}


def fingerprint(snapshot):
    encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    return encoded, hashlib.sha256(encoded.encode()).hexdigest()


def require_reason(reason):
    if len(reason.strip()) < 5:
        raise HTTPException(422, "Please provide a meaningful reason of at least five characters.")
    return reason.strip()


def install_approval_routes(app, database, authorize):
    # Explicit authentication is mandatory even when demo mode is enabled.
    readers = {"ADMIN", "PM", "DEVELOPER", "SALES", "VIEWER"}
    submitters = {"ADMIN", "PM", "SALES"}

    @app.get("/api/approvals/targets")
    def targets(request: Request, target_type: Literal["CONTRACT", "CHANGE_ORDER"]):
        authorize(request, readers)
        with database.connection() as connection:
            if target_type == "CONTRACT":
                rows = connection.execute("SELECT id, title, version, document_type FROM contracts WHERE status='ACTIVE' ORDER BY id DESC LIMIT 500").fetchall()
            else:
                rows = connection.execute("SELECT id, 'Change order #' || id AS title, currency, price, status FROM change_orders WHERE status IN ('DRAFT', 'REJECTED') ORDER BY id DESC LIMIT 500").fetchall()
        return [dict(row) for row in rows]

    @app.get("/api/approvals")
    def list_approvals(request: Request, limit: int = Query(default=100, ge=1, le=500)):
        authorize(request, readers)
        with database.connection() as connection:
            rows = connection.execute("""SELECT id, target_type, target_id, title, snapshot_hash,
                requested_by, requester_name, request_reason, status, reviewed_by, reviewer_name,
                decision_reason, created_at, reviewed_at FROM approval_requests ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(row) for row in rows]

    @app.get("/api/approvals/{approval_id}")
    def get_approval(approval_id: int, request: Request):
        authorize(request, readers)
        with database.connection() as connection:
            row = connection.execute("SELECT * FROM approval_requests WHERE id=?", (approval_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Approval request not found.")
        result = dict(row)
        result["snapshot"] = json.loads(result["snapshot"])
        return result

    @app.post("/api/approvals", status_code=201)
    def submit_approval(payload: ApprovalSubmission, request: Request):
        actor = authorize(request, submitters)
        if payload.target_type == "CONTRACT" and actor["role"] not in {"ADMIN", "PM"}:
            raise HTTPException(403, "Only PM or Admin may submit SOWs for approval.")
        reason = require_reason(payload.reason)
        with database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = target_snapshot(connection, payload.target_type, payload.target_id)
            encoded, digest = fingerprint(snapshot)
            duplicate = connection.execute("""SELECT id FROM approval_requests WHERE target_type=? AND target_id=?
                AND (status='PENDING' OR (status='APPROVED' AND snapshot_hash=?))""",
                (payload.target_type, payload.target_id, digest)).fetchone()
            if duplicate:
                raise HTTPException(409, "This exact item is already pending or approved. Open its approval record.")
            title = snapshot.get("title", f"Change order #{payload.target_id}")
            cursor = connection.execute("""INSERT INTO approval_requests
                (target_type,target_id,title,snapshot,snapshot_hash,requested_by,requester_name,request_reason)
                VALUES (?,?,?,?,?,?,?,?)""", (payload.target_type,payload.target_id,title,encoded,digest,actor["id"],actor["name"],reason))
            approval_id = cursor.lastrowid
            audit(connection, request, actor, "APPROVAL_SUBMIT", approval_id)
        return {"id": approval_id, "status": "PENDING"}

    @app.post("/api/approvals/{approval_id}/decision")
    def decide(approval_id: int, payload: ApprovalDecision, request: Request):
        actor = authorize(request, submitters)
        reason = require_reason(payload.reason)
        with database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM approval_requests WHERE id=?", (approval_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Approval request not found.")
            roles = {"ADMIN", "PM"} if row["target_type"] == "CONTRACT" else {"ADMIN", "SALES"}
            if actor["role"] not in roles:
                raise HTTPException(403, "Your role cannot review this type of approval.")
            if actor["id"] == row["requested_by"]:
                raise HTTPException(403, "A different authorized person must review your request. Self-approval is not allowed.")
            if row["status"] != "PENDING":
                raise HTTPException(409, "This request already has a final decision.")
            # Rejection remains possible if an item has been deleted or changed.
            if payload.decision == "APPROVED":
                current = target_snapshot(connection, row["target_type"], row["target_id"])
                if fingerprint(current)[1] != row["snapshot_hash"]:
                    raise HTTPException(409, "The item changed after submission. Reject this request and submit the updated revision.")
            connection.execute("""UPDATE approval_requests SET status=?, reviewed_by=?, reviewer_name=?,
                decision_reason=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?""",
                (payload.decision, actor["id"], actor["name"], reason, approval_id))
            if row["target_type"] == "CHANGE_ORDER":
                status = "INTERNALLY_APPROVED" if payload.decision == "APPROVED" else "REJECTED"
                connection.execute("UPDATE change_orders SET status=? WHERE id=?", (status,row["target_id"]))
            audit(connection, request, actor, "APPROVAL_" + payload.decision, approval_id)
        return {"id": approval_id, "status": payload.decision}


def audit(connection, request, actor, event, approval_id):
    connection.execute("""INSERT INTO security_audit_events
        (event_type,outcome,actor_user_id,subject,ip_address,request_id,details)
        VALUES (?,'SUCCESS',?,?,?,?,?)""", (event,actor["id"],str(approval_id),
        request.client.host if request.client else None,getattr(request.state,"request_id",None),
        json.dumps({"approval_id": approval_id})))
