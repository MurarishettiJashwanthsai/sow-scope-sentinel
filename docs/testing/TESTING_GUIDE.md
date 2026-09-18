# Testing Guide for Company Reviewers

Project: **SOW Scope Sentinel** — an independent portfolio prototype, not a company-approved deployment.

This guide explains the names of the testing methods used in the local assessment dated **10 September 2026**. It is intended for the developer and company reviewers who want a plain-language explanation. Writing this guide did not rerun tests or fix defects; the [assessment report](REPORT.md) and saved outputs remain the evidence for the results.

The categories below overlap. For example, a test that rejects a Viewer document write is both an API test and an authorization test. Do not add category names together as though they were separate test counts.

## 1. Unit / Business-Logic Testing

**Meaning:** Check a small part of the application, such as a calculation or decision rule, independently of the full browser workflow.

**Project examples:** Contract clause classification, scope decision rules and the margin-aware quote calculation. For 24 hours at an internal cost of 80 per hour and a target margin of 36%, the expected price is 3,000.

**Tool and evidence:** pytest; [service tests](../../tests/test_services.py).

**Company explanation:** “We checked the application's individual business rules and calculations.” A correct final decision label does not automatically mean its explanation is correct; QA-04 demonstrates that distinction.

## 2. API / Integration Testing

**Meaning:** Check whether backend endpoints, business logic and the database work together correctly. API means Application Programming Interface.

**Project examples:** Uploading a SOW and retrieving clauses; storing ticket analysis and history; saving revisions without overwriting earlier documents; recording approvals and rejecting changes to final decisions.

**Tools and evidence:** pytest and FastAPI TestClient; [API tests](../../tests/test_api.py), [milestone tests](../../tests/test_milestone.py), [approval tests](../../tests/test_approvals.py).

**Company explanation:** “We checked that connected application features save and retrieve the expected data.” These tests use local test databases, not live company integrations or PostgreSQL production infrastructure.

## 3. End-to-End Browser Testing — E2E

**Meaning:** Operate the website like a user and check a workflow across the interface and backend.

**Project examples:** Sign in, select a saved SOW, submit a ticket, inspect evidence and generate a quote. Other flows cover document editing, PM approval, history and Viewer restrictions.

**Tools and evidence:** agent-browser with Chromium; [browser runner](../../scripts/verify_browser.mjs), [12 recorded workflow results](browser-results.json).

**Company explanation:** “We exercised the main user journeys in a real browser.” Only the listed journeys were checked; this does not mean every button, browser or workflow combination was tested.

## 4. Regression Testing

**Meaning:** Repeat automated checks to detect broken or incorrect behavior as the application changes.

**Project examples:** Refresh returns to the top without losing the selected SOW; old Administration links reach the separate page; new document revisions preserve originals. Newly identified defects also have tests that currently fail.

**Tools and evidence:** pytest and the Node.js test runner; [frontend tests](../../tests/test_frontend.js), [expanded regression/security tests](../../tests/test_security_extended.py).

**Company explanation:** “The test suite gives us repeatable checks when we make changes. We retain failing tests until the underlying behavior is corrected.”

## 5. Authentication and Session Testing

**Meaning:** Check who can sign in, how identity is established, and when a login session must stop working. Authentication answers: **Who are you?**

**Project examples:** Wrong-password rejection, password salting, protected initial admin setup, failed-login throttling, temporary account lockout, session expiry, logout, disabled users and concurrent-session limits.

**Tools and evidence:** pytest and FastAPI TestClient; [security tests](../../tests/test_security.py), [expanded security tests](../../tests/test_security_extended.py).

**Company explanation:** “We tested login protections and rejection of invalid or revoked sessions.” Testing disabled-user enforcement through a test database does not demonstrate a completed employee-offboarding interface or SSO/MFA integration.

## 6. Authorization Testing — RBAC

**Meaning:** Check which actions an identified user may perform. Authorization answers: **What are you allowed to do?** RBAC means Role-Based Access Control.

**Project examples:** Viewers cannot create documents; private APIs reject anonymous access; approval requests need an eligible reviewer; users cannot approve their own requests.

**Tools and evidence:** API and browser checks; [approval tests](../../tests/test_approvals.py), [security tests](../../tests/test_security.py), [browser results](browser-results.json).

**Company explanation:** “We checked selected allowed and denied actions for application roles.” Current roles do not isolate separate projects or tenants, and these checks are not a complete permission matrix for a company deployment.

## 7. Cross-Site Request Forgery Protection Testing — CSRF

**Meaning:** Check that another website cannot trick an already logged-in browser into submitting an unauthorized change.

**Project examples:** Reject write requests with missing, incorrect or another session's CSRF token; reject a foreign Origin even with a valid token; require CSRF protection when Origin is absent.

**Tools and evidence:** pytest and FastAPI TestClient; [security tests](../../tests/test_security.py), [expanded security tests](../../tests/test_security_extended.py).

**Company explanation:** “We tested that a logged-in session alone is not enough to authorize a forged browser write.” Signature-authenticated webhook routes use different controls and are assessed separately.

## 8. Input Validation and File Upload Testing

**Meaning:** Check that acceptable input is processed and invalid input is rejected safely.

**Project examples:** Index a generated text-based PDF; reject oversized files, unsupported file types, broken PDFs, empty documents and invalid UTF-8 text. Invalid uploads should not create saved contracts.

**Tools and evidence:** pytest and FastAPI TestClient; [expanded upload tests](../../tests/test_security_extended.py), [upload-size check](../../tests/test_security.py).

**Company explanation:** “We tested valid document uploads and several invalid or abusive input cases.” This is not comprehensive PDF fuzzing, malware scanning, OCR testing or decompression-bomb resistance testing.

## 9. Injection and Output-Escaping Checks — XSS / SQL Injection

**Meaning:** Check selected situations where application input could be mistaken for executable code.

- **Cross-Site Scripting (XSS):** Untrusted text executes as code in another user's browser. The browser check confirmed that an HTML-looking document title displayed as text without executing its handler.
- **SQL Injection:** Untrusted input changes a database command. A tested SQL-looking document title was saved as data without dropping the contracts table.

**Tools and evidence:** Browser automation and pytest; [browser runner](../../scripts/verify_browser.mjs), [expanded security tests](../../tests/test_security_extended.py).

**Company explanation:** “We checked selected script-injection and database-injection cases.” Do not describe this as proof that every input, rendering location or query is injection-proof.

## 10. Webhook Security and Duplicate-Delivery Testing

**Meaning:** Check the authenticity of incoming integration messages and what happens when a sender retries the same event.

**Project examples:** Jira/Slack signature checks, malformed Jira digest handling, and repeated delivery of the same signed Jira payload. HMAC means Hash-based Message Authentication Code: it lets the receiver verify a message using a shared secret. Idempotency means repeating the same operation does not create additional unintended effects.

**Tools and evidence:** pytest; [integration tests](../../tests/test_milestone.py), [expanded webhook tests](../../tests/test_security_extended.py).

**Observed gaps:** QA-01 reproduces an HTTP 500 for an unsupported Jira digest; QA-02 reproduces duplicate tickets from repeated valid delivery. Neither proves a signature-forgery bypass.

**Company explanation:** “We tested message verification and retries, and found webhook handling defects that need correction before deployment.” Live Jira/Slack account integration was not validated.

## 11. HTTPS and Security-Configuration Testing

**Meaning:** Check encrypted access and protective browser/server settings. HTTPS uses TLS, Transport Layer Security, to protect communication.

**Project examples:** Validate the local HTTPS certificate using an explicit certificate file; verify HTTP-to-HTTPS redirects and anonymous-access denial; inspect security headers; test Secure/HttpOnly cookie flags and rejection of HTTP writes.

**Tools and evidence:** curl and FastAPI TestClient; [transport-check details](REPORT.md#transport-checks), [configuration snapshot](https-status.json), [security tests](../../tests/test_security.py).

**Company explanation:** “We checked local HTTPS and selected enforcement settings, but company-managed browser trust is still pending.” Browser screenshots used a separate authenticated HTTP fixture with Secure cookies disabled only there. A configuration value of `true` is not, on its own, proof that protection works correctly.

## 12. Static Application Security Testing — SAST

**Meaning:** Inspect source code for potentially unsafe patterns without running every application feature.

**Project example:** Bandit scanned production Python and reported formatted SQL plus subprocess-related patterns for manual review.

**Tool and evidence:** Bandit; [scan output](bandit-results.json), [manual triage](REPORT.md#static-analysis-triage).

**Company explanation:** “We scanned the Python source and reviewed the findings.” A scanner warning is not automatically an exploitable vulnerability. For example, the flagged SQL interpolation uses fixed strings at that call site. Conversely, a clean scan would not prove the application has no vulnerabilities.

## 13. Software Composition Analysis — SCA

**Meaning:** Check third-party dependencies against published vulnerability advisories.

**Project example:** Audit the packages installed in the application's environment, including runtime libraries and development tools.

**Tool and evidence:** pip-audit; [dependency audit](dependency-audit.json), [dependency interpretation](REPORT.md#dependency-and-runtime-findings).

**Company explanation:** “We checked external packages for known advisories and documented upgrade work.” The result is 24 distinct package/advisory-ID pairs across six packages, not proof of 24 independently exploitable application vulnerabilities. Reachability and impact require further review. `pip check` separately checks dependency compatibility; it is not a vulnerability scanner.

## 14. Responsive Layout and Visual Inspection

**Meaning:** Check how pages fit different screen sizes and inspect whether the visible output is usable and sensible.

**Project examples:** Check six routes for horizontal page overflow at a 390-pixel viewport; inspect nine screenshots. Visual inspection identified the incorrect explanation that calls excluded ERP work a contracted provider.

**Tools and evidence:** Chromium, browser assertions and manual image inspection; [README screenshot gallery](../../README.md#application-screenshots), [browser results](browser-results.json).

**Company explanation:** “We checked selected mobile layouts and reviewed actual screen output.” This was not a complete accessibility audit, cross-browser compatibility test or automated visual-diff baseline.

## Recorded results to present

These are the assessment's recorded results, not a new run performed while writing this guide.

| Group | Result |
|---|---|
| Python service, API and security suite | 87 tests: 83 passed, 4 failed |
| JavaScript regression suite | 5 passed |
| Browser workflow checks | 12 passed |
| Separate API documentation rendering check | Failed |
| Dependency audit | 24 distinct package/advisory pairs across 6 packages |
| Static security scan | 1 medium and 6 low findings, with manual triage |

Five open application findings cover malformed Jira signatures, duplicate webhook deliveries, future amendment dates, an incorrect scope explanation and the blank API documentation page. Dependency advisories and the unsupported application runtime also need remediation. See the [full report](REPORT.md) for evidence and limitations.

**A passed test means its specific assertions passed. It does not mean the entire feature or application is secure.**

## Testing still needed before company rollout

These activities are pending, not completed claims:

- **Independent penetration testing:** An authorized security specialist attempts to exploit weaknesses within an agreed scope.
- **Performance, load and stress testing:** Measure response times and behavior under expected traffic and overload.
- **User Acceptance Testing (UAT):** Company-designated users check agreed business requirements and record acceptance or rejection.
- **Backup and recovery testing:** Restore data from backups and verify completeness and recovery time.
- **Deployment and integration testing:** Validate trusted production HTTPS, identity, permissions, databases and real external integrations in an authorized environment.
- **Accessibility and cross-browser testing:** Evaluate keyboard/screen-reader access and supported browsers beyond the tested Chromium scenarios.

## A short explanation for a company meeting

> I developed an independent SOW management prototype and tested it using synthetic data. The assessment covered business rules, APIs, browser workflows, login and permissions, upload handling, selected security attacks, HTTPS and dependency vulnerabilities. I documented both successful tests and unresolved defects, with screenshots and reproducible evidence. It is available for technical review, but I am not claiming it is production-ready or company-approved.

Use the [README](../../README.md), [assessment report](REPORT.md) and [pilot review template](../COMPANY_APPROVAL.md) as supporting materials. No organizational sponsorship, endorsement or approval is implied.
