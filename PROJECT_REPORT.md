# Project Report: SOW Scope Sentinel

## Abstract

Fixed-price software projects lose margin when informal client requests become engineering tickets without contractual review. SOW Scope Sentinel checks a ticket against indexed Statement of Work clauses before work begins. The system extracts contract clauses, retrieves relevant evidence, assigns one of four scope states, allows a Project Manager to record an override, and prepares a margin-aware change-order draft. The MVP uses explainable local logic so it can be demonstrated without external AI services.

## Problem statement

Project Managers cannot manually compare every new ticket with a long legal document. Developers may begin apparently small requests without realizing that they represent new contractual deliverables. The result is unbilled effort, schedule slippage, unclear client expectations, and reduced gross margin.

## Objectives

- Check engineering requests before they enter development.
- Cite the contract clauses used for each decision.
- Identify explicit exclusions and new third-party solutions.
- Route uncertain cases to a human instead of guessing.
- Calculate a price that preserves a selected gross margin.
- Maintain persistent evidence and review records.

## Existing system

The typical process depends on a PM manually searching a PDF after a ticket is created. Informal requests from calls and messages can bypass the process, keyword searches do not understand context, and a single vector-similarity threshold cannot determine contractual entitlement.

## Proposed system

The proposed system combines structured document processing, normalized semantic terms, similarity retrieval, explicit rules, confidence bands, and human review. It produces `IN_SCOPE`, `OUT_OF_SCOPE`, `NEEDS_REVIEW`, or `NEEDS_CLARIFICATION`. Only sufficiently supported tickets should move toward development.

## Modules

1. **Contract ingestion:** extracts text from PDF or text documents and creates referenced clauses.
2. **Clause classification:** identifies exclusions, integrations, deliverables, technical terms, milestones, acceptance terms, and commercial clauses.
3. **Ticket analysis:** normalizes ticket requirements, retrieves evidence, applies scope rules, and assigns a decision.
4. **Review workflow:** records an authorized human decision and reason.
5. **Pricing:** calculates cost and fixed price from effort, hourly cost, and target margin.
6. **Change order:** produces a client-ready draft that remains unapproved until human authorization.
7. **Integration:** accepts manual requests and a minimal Jira webhook structure.
8. **Contract governance:** resolves active SOW versions, amendments, effective dates and superseded clause references.
9. **Access control:** supports secure password hashing, server-side sessions and role-restricted PM/commercial actions.
10. **Optional AI review:** requests strict structured output from an LLM and rejects any clause citation not present in retrieved evidence.

## Functional requirements

- Upload or paste a contract.
- View extracted clauses and references.
- Create a ticket with description and acceptance criteria.
- Analyse the ticket against its project contract.
- Upload a real PDF through the browser and manage amendments.
- Display confidence, reasoning, and evidence.
- Permit an auditable PM override.
- Authenticate users and restrict commercial actions by role.
- Generate a change-order draft for additional work.

## Non-functional requirements

- Decisions must be explainable.
- Data must persist between requests.
- Invalid input must return a clear error.
- Commercial drafts must not be represented as approved quotes.
- The architecture must support later PostgreSQL, vector, SSO, and integration upgrades.

## Testing

The included automated suite covers clause extraction, clause categories, contracted work, different providers, explicit exclusions, vague tickets, similarity behavior, price calculation, the API lifecycle, PM overrides, and prevention of change orders for in-scope tickets. Run the tests using the command documented in `README.md`.

## Result

The MVP implements the full local demonstration path from SOW ingestion to ticket decision and change-order draft. It does not claim legal accuracy or production classification metrics. Those require historical organization-specific tickets labelled by qualified reviewers.

## Future scope

- PostgreSQL with pgvector
- OCR and table-aware PDF extraction
- Contract amendments and clause precedence
- LLM structured reasoning with cited evidence
- Full Jira OAuth lifecycle, automated Jira transitions, Slack installation OAuth, CRM opportunities, and e-signatures
- Revenue-protection analytics
- Organization-specific policy configuration

## Conclusion

The project addresses the operational gap that allows unapproved work to begin. Its main contribution is not simply semantic search; it is an enforceable and auditable workflow in which contract evidence is retrieved automatically and uncertain commercial decisions remain under human control.

## Viva questions

1. **Why is cosine similarity alone insufficient?** It measures textual closeness, not whether the contract legally includes, excludes, or limits a deliverable.
2. **Why are there four decisions?** A binary answer forces unsafe guesses. Review and clarification states handle uncertainty and missing requirements.
3. **Why preserve clause references?** They make decisions explainable and allow PMs to verify the source.
4. **How is the quote calculated?** Cost equals hours multiplied by internal hourly cost; price equals cost divided by one minus the target gross margin.
5. **Why use SQLite in the MVP?** It makes the demonstration self-contained. PostgreSQL is appropriate for multi-user production deployment.
6. **What prevents AI hallucination?** Decisions must be tied to retrieved clause evidence, with human review for weak or conflicting evidence.
7. **How would the model improve?** Add embeddings, reranking, structured LLM output, and threshold calibration using PM-labelled historical tickets.
8. **What is the most important security risk?** Contracts contain confidential commercial information, so tenant isolation, encryption, RBAC, and retention controls are essential.
