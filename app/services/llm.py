from __future__ import annotations

import json
from typing import Mapping, Sequence

import httpx

from app.services.analyzer import AnalysisResult, Evidence, cosine_similarity


DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["IN_SCOPE", "OUT_OF_SCOPE", "NEEDS_REVIEW", "NEEDS_CLARIFICATION"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
        "evidence_clause_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": ["decision", "confidence", "reason", "evidence_clause_refs"],
    "additionalProperties": False,
}


def review_with_openai(
    ticket_text: str,
    clauses: Sequence[Mapping[str, object]],
    api_key: str,
    model: str,
    fallback: AnalysisResult,
) -> AnalysisResult:
    """Use structured output only on retrieved clauses and reject invented citations."""
    ranked = sorted(
        ((cosine_similarity(ticket_text, str(clause["text"])), clause) for clause in clauses),
        key=lambda item: item[0],
        reverse=True,
    )[:8]
    clause_map = {str(clause["clause_ref"]): clause for _, clause in ranked}
    context = "\n\n".join(
        f"[{clause['clause_ref']}] ({clause['category']}) {clause['text']}" for _, clause in ranked
    )
    payload = {
        "model": model,
        "store": False,
        "instructions": (
            "You are a contract scope analyst. Decide only from the supplied clauses. "
            "Never invent a clause reference. Absence of evidence means NEEDS_REVIEW, not OUT_OF_SCOPE. "
            "Use NEEDS_CLARIFICATION when the request lacks testable detail."
        ),
        "input": f"ENGINEERING REQUEST\n{ticket_text}\n\nRETRIEVED CONTRACT CLAUSES\n{context}",
        "text": {
            "format": {
                "type": "json_schema",
                "name": "scope_decision",
                "strict": True,
                "schema": DECISION_SCHEMA,
            }
        },
    }
    response = httpx.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    parsed = json.loads(_output_text(response.json()))
    references = parsed.get("evidence_clause_refs") or []
    if any(reference not in clause_map for reference in references):
        return fallback
    if parsed["decision"] in {"IN_SCOPE", "OUT_OF_SCOPE"} and not references:
        return fallback

    evidence = []
    for reference in references:
        clause = clause_map[reference]
        evidence.append(
            Evidence(
                clause_id=int(clause["id"]),
                clause_ref=reference,
                category=str(clause["category"]),
                clause_text=str(clause["text"]),
                score=round(cosine_similarity(ticket_text, str(clause["text"])), 3),
                relationship="LLM_CITATION",
                explanation="Clause selected by the structured LLM review.",
            )
        )
    return AnalysisResult(
        decision=str(parsed["decision"]),
        confidence=round(float(parsed["confidence"]), 3),
        reason=str(parsed["reason"]),
        evidence=evidence,
    )


def _output_text(response: Mapping[str, object]) -> str:
    for item in response.get("output", []):  # type: ignore[union-attr]
        if isinstance(item, dict) and item.get("type") == "message":
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text":
                    return str(content.get("text") or "")
    raise ValueError("The model response did not contain structured output text.")

