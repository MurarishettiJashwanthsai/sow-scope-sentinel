# Scope Sentinel — proposed pilot for Prominent Scientific PVT LTD.

Date: 10 September 2026  
Status: DRAFT — NOT APPROVED FOR PRODUCTION  
Business sponsor: To be assigned  
Technical owner: To be assigned   
Deployment environment: To be confirmed by the company  
Company sign-in system: Unknown — confirmation required from IT

This package is a proposal prepared for company review. Use of the company name does not imply sponsorship, endorsement, or approval.

## Decision requested

Request permission from XYZ.pvt.ltd to evaluate Scope Sentinel in a limited, company-controlled pilot after the pilot gates below are completed. This is not a request for unrestricted production rollout, authority to interpret contracts legally, or permission to send company data to external AI services.

## First step when the IT setup is unknown

Start with your reporting manager or the person responsible for internal software. Ask them to identify the appropriate IT/security contact; do not assume a particular department or individual exists. You do not need to choose a sign-in provider yourself.

Ask the nominated contact to confirm:

- Who may authorize a small internal pilot and which team would evaluate it?
- Which work-account sign-in service and MFA requirements should an internal application use?
- Where may it be hosted, and which company domain or internal address should it use?
- Which synthetic or redacted examples may be used, and who can authorize real contract data later?

Until those answers are available, keep the environment local, use synthetic data for demonstrations, and do not enable external integrations or claim company readiness. Local accounts can demonstrate the workflow; company pilot use of those accounts still needs explicit approval. Company-wide HTTPS should be provided through an IT-approved certificate and deployment, not by asking every employee to bypass a browser warning.

Scope Sentinel compares engineering requests with SOW clauses, presents evidence, records PM reviews, and generates change-order drafts. The intended business benefit is earlier detection of unbilled scope changes. Savings and classification accuracy have not yet been demonstrated on company-approved data.

## Current evidence and gaps

This is a code-based readiness review, not an independent penetration test or compliance certification. Items described as unverified require company evidence; their absence from this repository does not prove the company's infrastructure lacks them.

| Area | Implemented or observed | Required next step |
|---|---|---|
| Transport and sessions | Local HTTPS, Secure/HttpOnly session cookies, CSRF checks, required login | Deploy to an approved company environment with a trusted certificate; local self-signed certificates are not a company rollout solution |
| Identity | Local accounts, role checks, password hashing, session logout and login throttling | Confirm company identity provider; implement approved SSO/MFA or obtain an explicit limited-pilot exception; add administrator offboarding and session revocation |
| Data access | Role-based API permissions | Define project/team boundaries and test object-level access; roles currently do not isolate separate company projects or tenants |
| Storage | Runtime database uses SQLite; PostgreSQL/pgvector migration groundwork exists | Implement and validate the selected production database, migration path, storage encryption, and least-privilege access |
| Recovery | No backup schedule or restore drill evidence found in the repository | Assign recovery objectives, automate encrypted backups, and demonstrate a restore in an isolated environment |
| Audit | Application review history and security event tables | Agree event coverage, reviewer identity requirements, retention, access controls, and protected external log storage; these tables are not tamper-proof |
| Approval workflow | Separate internal approval requests for exact SOW/amendment snapshots and commercial drafts; required reasons, reviewer identity, duplicate/self-review protection | Company must accept the initial role policy; named assignments, multi-stage approval, delegation/escalation, customer acceptance, and binding e-signatures remain unimplemented |
| AI and data sharing | Optional adapter sends ticket text and up to eight retrieved clauses to an external API | Keep external AI disabled until the company approves provider, data categories, contractual terms, and retention/residency requirements; a request-level `store: false` is not blanket privacy approval |
| Integrations | Jira/Slack signature-verification code and limited integration paths | Approve scopes and service accounts, test replay/idempotency and retries, and map projects to contracts; do not describe this as completed enterprise OAuth integration |
| Operations | Local launcher and health endpoint | Establish managed hosting, patching, deployment/rollback, alerting, resource limits, shared rate limiting where needed, and an incident owner |
| Verification | Expanded local QA on 10 September 2026: 83 Python tests passed, 4 failed; 5 JavaScript and 12 browser workflow checks passed. Separate documentation rendering and dependency findings remain open. See [testing report](testing/REPORT.md). | NOT approved for production: remediate findings, rerun on a release candidate, and attach dependency/license review, independent security testing, load testing and user acceptance evidence |

Code evidence: `app/main.py`, `app/database.py`, `app/services/auth.py`, `app/services/security.py`, `app/services/llm.py`, `app/services/integrations.py`, `scripts/run_secure.py`, `tests/`, and `migrations/postgres/`. The local security-status JSON reports configuration; it is not proof of overall company readiness.

## Proposed pilot limits

These are recommendations for the company to accept or modify, not approved commitments:

- One team, one project, a small named user group, and a time-limited evaluation.
- Start with synthetic or company-approved redacted documents. Real contracts require explicit data-owner permission and completion of the relevant controls.
- Human reviewers check every scope decision. No automatic Jira transitions, customer messages, signed quotes, or financial commitments.
- Keep external AI and external integrations disabled until separately approved.
- Record access owners, permitted users, pilot end date, support contact, and deletion/retention instructions before inviting participants.
- Stop the pilot if data exposure, unexplained authorization failures, unreliable citations, or unrecoverable data loss occurs.

## Approval gates

| Gate | Proposed owner | Evidence required | Decision |
|---|---|---|---|
| Business case and pilot scope | Business sponsor / PM lead | Named use case, users, budget, measurable success criteria | PENDING |
| Data handling | Contract data owner / privacy team | Data classification, permitted data flows, retention and deletion policy | PENDING |
| Hosting and identity | IT / infrastructure | Approved environment/domain, trusted TLS, identity setup, offboarding and support plan | PENDING |
| Security assessment | Information security | Threat model, access-control tests, dependency findings, upload abuse tests, risk decisions | PENDING |
| Functional acceptance | PM / engineering / commercial reviewers | Agreed test set, exact clause citation checks, correct versions/amendments, approval and draft behavior | PENDING |
| Operations | Service owner | Backup restore evidence, monitoring, incident process and rollback procedure | PENDING |
| Pilot authorization | Accountable company approver | Completed gates or explicitly accepted exceptions with owners and expiry | PENDING |
| Production authorization | Company change/release authority | Pilot results, unresolved risks, production evidence and signed release decision | PENDING |

The company chooses the actual approvers and sequence. A local PM review inside this application does not constitute IT/security approval to deploy it.

## Acceptance evidence to collect

1. An unauthenticated user cannot read contracts, tickets, history, or audit events.
2. Every approved role is tested for both allowed and denied actions, including access to another project's data where isolation is required.
3. Disabled/offboarded users and revoked sessions lose access within the company-approved interval.
4. Trusted HTTPS works without warnings; insecure requests are blocked or redirected; cookie and CSRF protections are exercised, not merely displayed.
5. Malformed, oversized, scanned, and adversarial documents have documented behavior. Scanned PDFs may require OCR that is not currently implemented.
6. Reviewers confirm clause citations against the exact applicable SOW/amendment version. Evaluate false in-scope decisions separately; thresholds must be agreed before the pilot, not invented afterward.
7. Draft commercial output is not treated as approval or sent to a client automatically. Any future approval is tied to an immutable revision and authenticated approver identity.
8. A backup restores successfully; rollback is rehearsed; audit records remain available for the agreed retention period.
9. Attach a specific release identifier, configuration summary without secrets, test outputs, reviewer names, findings, and accepted exceptions.

## Implemented internal approval baseline

The `/approvals` page supports `PENDING → APPROVED or REJECTED` for SOW/amendment snapshots and change-order drafts. Submission and review require authenticated users even in demo mode. The requester cannot review their own request, including when they are an administrator. A final decision cannot be overwritten through the API. Rejected items may be submitted again as a new request with a new history entry.

Initial policy, pending company acceptance:

- SOW/amendment submissions and reviews: PM or Admin, with a different person reviewing.
- Commercial draft submissions: PM, Sales, or Admin. Reviews: a different Sales or Admin user.
- Viewer and Developer accounts can read approval records but cannot submit or decide them.
- Administration includes an Admin-only local user-creation form so a separate reviewer can be provisioned. It does not send invitations or provide SSO/offboarding.
- Approval records store content snapshots, SHA-256 fingerprints, authenticated user IDs/names, reasons, and timestamps. Changed or deleted content cannot be approved. New revisions require their own requests and do not inherit approval.
- Commercial acceptance is marked `INTERNALLY_APPROVED`, not customer-signed. No customer message, Jira transition, or contractual commitment is triggered.

Limitations: the record tables are not tamper-proof. Approval does not currently gate SOW indexing or ticket analysis, and does not certify the entire effective contract family when only one amendment is approved. Access remains workspace-wide by role, not project-isolated. Company deployment approval is an external decision, not a status generated by this application.

## Possible later multi-stage approval design — not implemented

If company policy requires multiple reviewers, confirm the stages before extending the baseline:

`Draft → Submitted → PM review → Commercial/finance review → Approved or Rejected`

Required policy decisions: who may submit, who may approve, whether self-approval is prohibited, whether approval is sequential, and whether customer acceptance is recorded separately. Changes after submission should invalidate approval of the previous revision. Record approver user ID, decision, reason, timestamp, and document/revision ID. Approval inside the app is not automatically a legally binding electronic signature.

## Draft email to the company — not sent

Subject: Request for internal pilot review at xyz PVT LTD. — Scope Sentinel

Hello [Manager / nominated IT reviewer],

I have developed a prototype that compares engineering requests with Statement of Work clauses, shows supporting evidence, records PM review decisions, and prepares change-order drafts.

I would like to request a limited internal evaluation at xyz PVT LTD., initially using synthetic or approved redacted data. I am not requesting immediate production deployment or permission to send confidential contracts to external AI services.

The attached readiness package identifies the implemented controls and outstanding work, including hosting and trusted HTTPS, company identity and access boundaries, backups, security assessment, and commercial approval policy.

Could you please identify the person responsible for reviewing an internal tool like this? I also need confirmation of the company's approved hosting environment, employee sign-in system, and required approval process. Once those requirements are agreed, I will address the gaps and provide a release-specific test and acceptance report for your decision.

Regards,  
[Your name / team]

## Planning references

Use [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/) to agree the applicable technical security checks with the company reviewer. Use [NIST SSDF](https://csrc.nist.gov/projects/ssdf) as a reference for development and operational responsibilities. These are planning references only; no ASVS verification, NIST certification, ISO certification, or company approval is claimed here.
