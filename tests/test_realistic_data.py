import json
from pathlib import Path

import pytest

from app.services.analyzer import analyze_ticket
from app.services.contracts import split_into_clauses


ROOT = Path(__file__).resolve().parent.parent
SOW_TEXT = (ROOT / "sample_data" / "realistic_ecommerce_sow.txt").read_text(encoding="utf-8")
CASES = json.loads((ROOT / "sample_data" / "realistic_ticket_cases.json").read_text(encoding="utf-8"))
CLAUSES = [
    {"id": index, "clause_ref": clause.reference, "category": clause.category, "text": clause.text}
    for index, clause in enumerate(split_into_clauses(SOW_TEXT), start=1)
]


@pytest.mark.parametrize("case", CASES, ids=[case["external_key"] for case in CASES])
def test_realistic_ticket_decisions(case):
    result = analyze_ticket(
        case["title"],
        case["description"],
        case["acceptance_criteria"],
        CLAUSES,
    )
    assert result.decision == case["expected_decision"]
    if case["expected_clause"]:
        assert result.evidence
        assert result.evidence[0].clause_ref.startswith(case["expected_clause"])

