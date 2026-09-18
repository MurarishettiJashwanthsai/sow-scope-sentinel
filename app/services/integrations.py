from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx


def verify_jira_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or "=" not in signature:
        return False
    method, supplied = signature.split("=", 1)
    if method.lower() not in hashlib.algorithms_available:
        return False
    expected = hmac.new(secret.encode(), body, method.lower()).hexdigest()
    return hmac.compare_digest(expected, supplied)


def verify_slack_signature(
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    secret: str,
    now: int | None = None,
) -> bool:
    if not timestamp or not signature:
        return False
    try:
        request_time = int(timestamp)
    except ValueError:
        return False
    if abs((now or int(time.time())) - request_time) > 300:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def send_slack_message(token: str, channel: str, text: str) -> bool:
    response = httpx.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        content=json.dumps({"channel": channel, "text": text}),
        timeout=10,
    )
    response.raise_for_status()
    return bool(response.json().get("ok"))

