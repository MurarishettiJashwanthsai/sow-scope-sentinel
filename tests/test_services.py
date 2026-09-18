from app.services.analyzer import analyze_ticket, cosine_similarity
from app.services.contracts import classify_clause, split_into_clauses
from app.services.pricing import calculate_price


SOW = """1.1 Deliverable: The supplier will build a responsive e-commerce web application with product catalogue and shopping cart.

3.2 Authentication: The application will provide customer login using OAuth2 authentication.

4.1 Payment Integration: The checkout will process standard credit-card payments through Stripe. Stripe webhook processing is included.

5.1 Exclusions: Native mobile applications, ERP integration and multilingual localization are not included in this scope.
"""


def clause_rows():
    return [
        {
            "id": index,
            "clause_ref": clause.reference,
            "category": clause.category,
            "text": clause.text,
        }
        for index, clause in enumerate(split_into_clauses(SOW), start=1)
    ]


def test_contract_is_split_and_classified():
    clauses = split_into_clauses(SOW)
    assert [clause.reference for clause in clauses] == ["1.1", "3.2", "4.1", "5.1"]
    assert clauses[2].category == "INTEGRATION"
    assert clauses[3].category == "EXCLUSION"
    assert classify_clause("The mobile app is not included in scope") == "EXCLUSION"


def test_semantically_supported_ticket_is_in_scope():
    result = analyze_ticket(
        "Process Stripe checkout payment",
        "Implement the contracted Stripe payment flow and webhook processing.",
        "A credit-card purchase through Stripe updates the order after its webhook.",
        clause_rows(),
    )
    assert result.decision == "IN_SCOPE"
    assert result.evidence[0].clause_ref == "4.1"


def test_different_named_provider_is_out_of_scope():
    result = analyze_ticket(
        "Integrate Coinbase Commerce checkout",
        "Add Coinbase Commerce as a second payment provider and process cryptocurrency webhooks.",
        "A customer can pay with cryptocurrency and Coinbase marks the order paid.",
        clause_rows(),
    )
    assert result.decision == "OUT_OF_SCOPE"
    assert result.evidence[0].clause_ref == "4.1"
    assert "different named platform/provider" in result.reason


def test_explicit_exclusion_is_out_of_scope():
    result = analyze_ticket(
        "Build native mobile application",
        "Create a native mobile app for customer shopping and checkout.",
        "The native mobile application runs on Android and supports the catalogue.",
        clause_rows(),
    )
    assert result.decision == "OUT_OF_SCOPE"
    assert any(item.category == "EXCLUSION" for item in result.evidence)


def test_vague_ticket_requires_clarification():
    result = analyze_ticket("Quick checkout tweak", "Please update it.", "", clause_rows())
    assert result.decision == "NEEDS_CLARIFICATION"
    assert result.evidence == []


def test_similarity_is_bounded():
    assert cosine_similarity("Stripe payment webhook", "Stripe processes payment webhook") > 0.5
    assert cosine_similarity("mobile app", "database migration") == 0


def test_margin_aware_price():
    estimate = calculate_price(hours=24, internal_hourly_cost=80, target_margin=0.36)
    assert estimate.estimated_cost == 1920
    assert estimate.price == 3000
    assert estimate.timeline_days == 4

