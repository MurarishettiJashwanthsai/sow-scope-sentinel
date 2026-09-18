from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


STOP_WORDS = {
    "a", "after", "an", "and", "are", "as", "at", "be", "before", "by", "for", "from", "in", "is", "it",
    "of", "on", "or", "that", "the", "this", "to", "via", "we", "will", "with", "shall",
    "can", "also", "client", "project", "system", "feature", "support", "add", "implement",
}

CANONICAL_TERMS = {
    "login": "authentication",
    "signin": "authentication",
    "sign-in": "authentication",
    "auth": "authentication",
    "payments": "payment",
    "pay": "payment",
    "checkout": "payment",
    "gateway": "integration",
    "integrate": "integration",
    "integrated": "integration",
    "apis": "api",
    "hooks": "webhook",
    "notifications": "notification",
    "dashboards": "dashboard",
    "forecasting": "forecast",
    "forecasted": "forecast",
    "predicted": "forecast",
    "predict": "forecast",
    "predictions": "forecast",
    "ga4": "analytics",
    "emails": "email",
    "users": "user",
}

GENERIC_ENTITIES = {
    "Acceptance", "Add", "Allow", "Application", "Build", "Card", "Client", "Commerce",
    "Create", "Credit", "Customer", "Deliverable", "Exclusions", "Implement", "Integrate", "Integration",
    "Mobile", "Native", "Order", "Payment", "Process", "Project", "Provide", "Section",
    "Scope", "Standard", "System", "The", "User", "Users", "Webhook",
}


@dataclass(frozen=True)
class Evidence:
    clause_id: int
    clause_ref: str
    category: str
    clause_text: str
    score: float
    relationship: str
    explanation: str


@dataclass(frozen=True)
class AnalysisResult:
    decision: str
    confidence: float
    reason: str
    evidence: list[Evidence]


def tokenize(text: str) -> list[str]:
    raw = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}", text.lower())
    result = []
    for token in raw:
        token = token.strip(".-")
        canonical = CANONICAL_TERMS.get(token, token)
        if canonical not in STOP_WORDS and len(canonical) > 1:
            result.append(canonical)
    return result


def cosine_similarity(left: str, right: str) -> float:
    left_counts = Counter(tokenize(left))
    right_counts = Counter(tokenize(right))
    if not left_counts or not right_counts:
        return 0.0
    dot = sum(count * right_counts.get(token, 0) for token, count in left_counts.items())
    left_norm = math.sqrt(sum(value * value for value in left_counts.values()))
    right_norm = math.sqrt(sum(value * value for value in right_counts.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def named_entities(text: str) -> set[str]:
    # Individual capitalized tokens are more reliable for equality checks than greedy
    # phrases (for example, "Stripe. Stripe" must still match "Stripe").
    candidates = set(re.findall(r"\b[A-Z][A-Za-z0-9+#-]{2,}\b", text))
    return {candidate for candidate in candidates if candidate not in GENERIC_ENTITIES}


def extract_requirements(title: str, description: str, acceptance_criteria: str) -> list[str]:
    combined = "\n".join(part for part in (title, description, acceptance_criteria) if part.strip())
    parts = re.split(r"(?:\n+|[;]|(?<=[.!?])\s+)", combined)
    return [part.strip(" -•\t") for part in parts if len(tokenize(part)) >= 2]


def _is_incomplete(title: str, description: str, acceptance_criteria: str) -> bool:
    detail_tokens = tokenize(f"{description} {acceptance_criteria}")
    vague = {"change", "update", "fix", "tweak", "thing", "improve", "modify"}
    no_acceptance = len(tokenize(acceptance_criteria)) < 2
    vague_without_acceptance = no_acceptance and (len(detail_tokens) < 8 or bool(set(detail_tokens) & vague))
    return len(detail_tokens) < 4 or set(detail_tokens) <= vague or vague_without_acceptance


def _bounded_alternative(ticket_text: str, clause_text: str, score: float) -> bool:
    """Detect a new named platform/provider in the same contractual capability."""
    if score < 0.12:
        return False
    ticket_entities = named_entities(ticket_text)
    clause_entities = named_entities(clause_text)
    if not ticket_entities or not clause_entities or ticket_entities & clause_entities:
        return False
    domain_terms = {"payment", "integration", "authentication", "database", "hosting", "notification", "analytics"}
    shared_domain = set(tokenize(ticket_text)) & set(tokenize(clause_text)) & domain_terms
    return bool(shared_domain)


def _matches_explicit_exclusion(ticket_text: str, clause_text: str) -> bool:
    """Require distinctive overlap with the excluded item, not just its business domain."""
    common_domain_terms = {
        "account", "application", "change", "checkout", "client", "customer", "data", "delivery",
        "feature", "integration", "management", "order", "payment", "processing", "product", "project", "shipment",
        "provider", "scope", "supplier", "support", "system", "user", "workflow",
    }
    overlap = (set(tokenize(ticket_text)) & set(tokenize(clause_text))) - common_domain_terms
    if len(overlap) >= 2:
        return True
    entity_overlap = named_entities(ticket_text) & named_entities(clause_text)
    return bool(entity_overlap and overlap)


def analyze_ticket(
    title: str,
    description: str,
    acceptance_criteria: str,
    clauses: Sequence[Mapping[str, object]],
) -> AnalysisResult:
    ticket_text = " ".join(part for part in (title, description, acceptance_criteria) if part)
    requirements = extract_requirements(title, description, acceptance_criteria)

    if _is_incomplete(title, description, acceptance_criteria):
        return AnalysisResult(
            decision="NEEDS_CLARIFICATION",
            confidence=0.96,
            reason="The ticket does not contain enough description or acceptance criteria for a contractual decision.",
            evidence=[],
        )

    ranked = []
    for clause in clauses:
        score = cosine_similarity(ticket_text, str(clause["text"]))
        # Exclusions are intentionally promoted so they cannot hide below generic deliverables.
        if str(clause["category"]) == "EXCLUSION" and score > 0.08:
            score = min(1.0, score + 0.18)
        ranked.append((score, clause))
    ranked.sort(key=lambda item: item[0], reverse=True)

    if not ranked:
        return AnalysisResult(
            decision="NEEDS_REVIEW",
            confidence=0.99,
            reason="No indexed contract clauses are available for comparison.",
            evidence=[],
        )

    top = ranked[:5]
    explicit_exclusions = [
        item
        for item in ranked
        if item[1]["category"] == "EXCLUSION"
        and _matches_explicit_exclusion(ticket_text, str(item[1]["text"]))
    ]
    if explicit_exclusions:
        score, clause = explicit_exclusions[0]
        supporting_context = [(score, clause)] + [
            item for item in top if int(item[1]["id"]) != int(clause["id"])
        ]
        evidence = _make_evidence(
            supporting_context,
            "CONTRADICTS",
            "The request overlaps an explicit contract exclusion.",
        )
        return AnalysisResult(
            decision="OUT_OF_SCOPE",
            confidence=round(min(0.98, 0.70 + score / 2), 3),
            reason=f"The request conflicts with exclusion {clause['clause_ref']}.",
            evidence=evidence,
        )

    best_score, best_clause = top[0]
    if _bounded_alternative(ticket_text, str(best_clause["text"]), best_score):
        ticket_names = ", ".join(sorted(named_entities(ticket_text)))
        contract_names = ", ".join(sorted(named_entities(str(best_clause["text"]))))
        reason = (
            f"The ticket introduces a different named platform/provider ({ticket_names}) from the "
            f"contracted one ({contract_names}) for the same capability."
        )
        return AnalysisResult(
            decision="OUT_OF_SCOPE",
            confidence=round(min(0.94, 0.72 + best_score / 3), 3),
            reason=reason,
            evidence=_make_evidence(top, "NARROWS_SCOPE", reason),
        )

    strong_categories = {"DELIVERABLE", "INTEGRATION", "TECHNICAL", "ACCEPTANCE", "GENERAL"}
    if best_score >= 0.30 and best_clause["category"] in strong_categories:
        coverage = sum(1 for requirement in requirements if cosine_similarity(requirement, str(best_clause["text"])) >= 0.18)
        if coverage >= max(1, math.ceil(len(requirements) * 0.5)):
            return AnalysisResult(
                decision="IN_SCOPE",
                confidence=round(min(0.96, 0.63 + best_score / 2), 3),
                reason=f"The request is supported by contract clause {best_clause['clause_ref']}.",
                evidence=_make_evidence(top, "SUPPORTS", "The clause semantically supports the requested work."),
            )

    return AnalysisResult(
        decision="NEEDS_REVIEW",
        confidence=round(max(0.51, 0.82 - best_score / 2), 3),
        reason="The available clauses do not provide strong enough evidence to approve or reject the request automatically.",
        evidence=_make_evidence(top, "RELATED", "Potentially relevant clause; a Project Manager must confirm coverage."),
    )


def _make_evidence(
    ranked: Iterable[tuple[float, Mapping[str, object]]],
    first_relationship: str,
    first_explanation: str,
) -> list[Evidence]:
    evidence = []
    for index, (score, clause) in enumerate(ranked):
        if score <= 0:
            continue
        evidence.append(
            Evidence(
                clause_id=int(clause["id"]),
                clause_ref=str(clause["clause_ref"]),
                category=str(clause["category"]),
                clause_text=str(clause["text"]),
                score=round(score, 3),
                relationship=first_relationship if index == 0 else "RELATED",
                explanation=first_explanation if index == 0 else "Additional retrieved contract context.",
            )
        )
    return evidence
