# Local QA and security assessment

Date: 10 September 2026. Target: the local SOW Scope Sentinel working tree, not a deployed company system.

## Verdict

**Not ready for production approval.** The assessment reproduced four application regressions and a separate documentation-rendering defect. Installed dependencies have known advisories, and the tested application runtime is unsupported. No production certification, complete vulnerability coverage, or approval by Prominent Scientific PVT LTD. is claimed.

The developer is presenting an independent portfolio project. All accounts, approvals and documents shown in screenshots are synthetic. Application behavior and application dependencies were not changed by this assessment; regression tests, QA tooling, evidence and documentation were added. Fixes require a follow-up implementation and retest.

## Results and evidence

| Area | Result | Evidence |
|---|---|---|
| Complete Python suite | 87 collected: **83 passed, 4 failed**, 12.40 seconds | [JUnit output](pytest-results.xml) |
| JavaScript regression suite | **5 passed** | [JUnit output](frontend-results.xml) |
| Browser workflows | **12 passed** | [Browser results](browser-results.json), [runner](../../scripts/verify_browser.mjs) |
| Separate API documentation check | **Failed:** `/docs` returns HTML but no rendered Swagger UI | QA-05 below |
| Installed-dependency audit | 38 raw advisory entries; **24 distinct package/advisory-ID pairs across 6 packages** | [Raw pip-audit JSON](dependency-audit.json) |
| Static security scan | **1 medium, 6 low; no high findings from this scan** | [Raw Bandit JSON](bandit-results.json) |
| Package consistency | `pip check` passed | No broken installed requirements reported; this does not mean vulnerability-free |
| Real local HTTPS health | HTTP 200; curl certificate verification result 0 using the explicit local certificate | Transport checks below |
| Real local unauthenticated document request | HTTP 401 | [Response body](https-anonymous.json) |
| Real local security configuration | Headers, trusted hosts, CSRF, Secure cookies and audit logging report enabled | [Configuration snapshot](https-status.json) |

An earlier partial expansion is retained as [historical test output](extended-initial-results.xml). It is not the final suite result. Final results above supersede the older passing baseline in previous project notes. There is no source-control release commit for this untracked working tree; [SHA256SUMS.txt](SHA256SUMS.txt) fingerprints the reviewed source and saved artifacts instead.

## Isolation and test environment

- Application Python: **3.9.6**, existing `.venv`; SQLite persistence.
- Browser: local Chromium through `agent-browser`; desktop screenshots and a 390 × 844 mobile viewport.
- Browser server: `http://127.0.0.1:8855`, bound to loopback, with a **new disposable SQLite database** under the system temporary directory. Existing workspace documents were not used for mutation tests.
- The synthetic fixture creates three SOWs, an amendment, tickets, a quote, and two approval records. Names are illustrative; the three fixture SOWs reuse a small clause set for deterministic tests and are not actual company contracts.
- Authentication and CSRF remain enabled for browser tests. **Secure cookies are disabled only in this HTTP fixture.** These screenshots do not prove browser HTTPS/cookie behavior.
- Separately, `TestClient` tests exercise HTTPS-mode session cookie flags, bootstrap-token enforcement, CSRF and rejection of HTTP writes. These simulate HTTPS requests; they are not browser TLS handshakes.
- Read-only checks exercised the existing HTTPS server on port 8443 using `curl --cacert .local/localhost-cert.pem`. No trust-store changes, certificate-warning bypasses or real-account creation were performed. Browser end-to-end sign-in on the secure server remains unverified because the certificate is not trusted by the browser.
- Security scanners were installed in an isolated `.local/qa-tools` environment using Python 3.12: pip-audit 2.10.1 and Bandit 1.9.4. The audit inspected the actual application's Python 3.9 site-packages, not the scanner environment.
- No real Jira/Slack credentials, external AI, company accounts, or company documents were used for workflow tests. Dependency scanning contacted package advisory services; this did not send SOW content.

## What was checked

### API, service and security regressions

Existing and expanded tests exercise text and text-based PDF ingestion; malformed, empty, unsupported, invalid-UTF-8 and oversized uploads; scope classifications and clause evidence; amendments and full revisions; soft deletion/restoration; quotes and pricing; history; PM overrides; role-denied writes; approval snapshots, distinct reviewers, stale/deleted targets and immutable final decisions.

Security-specific cases cover 15 unauthenticated private read routes, password salting and wrong-password rejection, expired/revoked/disabled-user sessions, concurrent-session limits, bootstrap-token checks, temporary lockout, login throttling across email addresses, CSRF with missing or foreign Origin, session-bound CSRF tokens, trusted hosts, headers, cookie flags, no-store API responses, selected secret/static traversal paths, SQL metacharacters treated as document data, and signed/invalid webhook cases. See [expanded tests](../../tests/test_security_extended.py) and [existing security tests](../../tests/test_security.py).

The disabled-user test changes the test database to validate enforcement. It does **not** demonstrate a finished offboarding UI. Role checks do **not** demonstrate project or tenant isolation, which is not implemented.

### Browser workflows

1. Administrator sign-in, password-field clearing and visibility of admin tools.
2. Saved SOW selection and live dashboard counts.
3. Scope submission, evidence rendering and cleared input fields.
4. Quote calculation: 24 hours × 80 / (1 − 0.36) = 3,000; approval link present.
5. Populated history; refresh returns to the top while retaining the contract query.
6. Library search and document viewing.
7. Save as a new revision while preserving the original.
8. A PM approves another user's request with a recorded reason.
9. An HTML-looking document title renders as text without executing its handler.
10. No horizontal page overflow on six routes at 390 pixels wide.
11. Viewer submission controls disabled and direct document write rejected with HTTP 403.
12. No uncaught errors reported by the browser error collector during these flows.

Passing step 3 means the expected decision label and evidence appeared. It does **not** mean the explanation was correct: visual review exposed QA-04. Similarly, quote arithmetic passed while its copied explanation remained incorrect. The error collector does not establish that every network request or console warning is clean.

Nine images are embedded in the [README gallery](../../README.md#application-screenshots). All were visually inspected. History and approval captures were reframed after the automated run to show the saved records more clearly; no product content was altered for those captures. The runner includes equivalent framing instructions.

## Open application findings

Priorities below are local triage judgments, not externally assigned CVSS scores. The four failing tests intentionally remain ordinary failures, not `xfail` or skipped tests.

### QA-01 — Unsupported Jira HMAC algorithm causes HTTP 500

Priority: medium. When a Jira signing secret is configured, a request with `X-Hub-Signature: shake_128=invalid` returns HTTP 500 rather than rejecting the header with a client error. The algorithm is present in `hashlib.algorithms_available` but is not usable by this HMAC call. No knowledge of the secret is needed to trigger the error. This demonstrates error-handling weakness, **not a forged-signature authentication bypass or proven service-wide denial of service**.

Evidence: `test_jira_unsupported_digest_does_not_crash`; `app/services/integrations.py`, `verify_jira_signature`.

Suggested fix: restrict accepted algorithms to the supported integration contract, validate the signature format, and handle invalid digest construction by rejecting the request. Retest valid and invalid signatures and ensure no exception details leak.

### QA-02 — Duplicate signed Jira delivery creates duplicate work

Priority: medium. Sending the same correctly signed issue payload twice creates two ticket/analysis records. Normal webhook retries can therefore duplicate work. This case requires a valid signed payload; it does not demonstrate forging one.

Evidence: `test_jira_redelivery_does_not_create_duplicate_ticket`, which observes two tickets where the regression expects one.

Suggested fix: define delivery/event identity and enforce atomic deduplication with a unique database constraint. Do not blindly deduplicate every future event by issue key, because a legitimate update to an existing issue is a different event. Test concurrent redelivery, retries and changed issues.

### QA-03 — Future amendments affect the current contract immediately

Priority: high for business correctness. An amendment effective on **2099-01-01** immediately replaces the base exclusion in the effective clause response. The resolver orders amendments by date but does not exclude future amendments from the current scope.

Evidence: `test_future_amendment_does_not_apply_before_effective_date`; `_effective_clauses` in `app/main.py`.

The regression assumes that “effective date” governs when clauses become applicable. Some existing tests encode immediate application even for future dates; the intended as-of-date policy must be explicitly agreed before changing those older assertions. Regardless of policy, the UI must not imply current applicability when it is only previewing future scope.

Suggested fix: define an explicit analysis as-of date, filter eligible amendments before resolving supersession, and preserve the resolution date and source versions with the analysis. Test past, today, future, missing and invalid dates, and revision chains.

### QA-04 — Excluded ERP work is described as a contracted provider

Priority: medium for explanation and commercial accuracy. A SOW includes Stripe payment processing and excludes cryptocurrency and ERP work. For a Coinbase request the result is correctly `OUT_OF_SCOPE`, but the explanation says the contracted provider is **ERP**, not Stripe. The incorrect explanation is also copied into the quote draft.

Evidence: `test_scope_reason_does_not_describe_excluded_erp_as_contracted_provider`; [analysis screenshot](../screenshots/scope-analysis.png), [quote screenshot](../screenshots/change-order.png).

Suggested fix: distinguish positive contracted capabilities from exclusions before named-provider comparison. Prefer the relevant explicit exclusion where applicable, and test the explanation and exact supporting clauses, not only the final decision label. Do not send the observed draft to a customer as-is.

### QA-05 — Interactive API documentation is blank

Priority: low functional defect. `/docs` returns HTTP 200 with a Swagger container, but the browser check observed an empty body and no rendered UI. The response loads JavaScript/CSS from `cdn.jsdelivr.net` and an inline initializer while its CSP permits only `script-src 'self'` and `style-src 'self'`. This provides a direct explanation for the rendering failure. The browser console command did not return a diagnostic, so no specific console message is claimed.

Suggested fix: self-host the documentation assets and use an external initializer or an appropriately scoped nonce/hash. Alternatively disable interactive docs intentionally and document schema-only access. Do not broadly disable the security policy to make Swagger work. Add a browser regression for the chosen behavior.

## Dependency and runtime findings

| Installed package | Installed version | Distinct advisory IDs for that package | Context |
|---|---|---:|---|
| click | 8.1.8 | 1 | CLI/runtime dependency |
| python-multipart | 0.0.20 | 6 | Upload parsing |
| starlette | 0.49.3 | 5 | Web framework runtime |
| pip | 21.2.4 | 7 | Installer tooling |
| setuptools | 58.0.4 | 4 | Build tooling |
| pytest | 8.4.2 | 1 | Test tooling |
| Total | | **24** | 6 packages |

The raw audit contains repeated entries for some identical package/advisory IDs. The table deduplicates those pairs; it does not claim 24 independently exploitable application vulnerabilities or collapse every possible alias. Consult the raw JSON for exact IDs, descriptions, aliases and fix versions. Reachability and actual application impact still require individual triage. Runtime and development-tool findings should not be conflated.

The existing runtime is Python 3.9.6. Python 3.9 reached end-of-life on 31 October 2025 according to the [official Python version status](https://devguide.python.org/versions/). Move to a supported runtime, resolve a compatible FastAPI/Starlette/dependency set, update installer/build/test tools, and rerun the full suite and audit. Some updated packages may no longer support Python 3.9. No automatic `--fix` or application dependency upgrade was run.

[pip-audit](https://github.com/pypa/pip-audit) checks installed packages against known advisory sources; it is not a general code audit and cannot certify that a project has no vulnerabilities.

## Static-analysis triage

Bandit scanned 1,982 lines of production Python in `app/` and `scripts/run_secure.py`. Synthetic fixtures and tests were not included in this production-code scan.

- **B608, medium, `app/main.py`:** formatted SQL in contract listing. Manual review shows the interpolated `where` value is chosen from two fixed strings using a boolean, not user-supplied SQL text. This finding is likely a false positive at this call site; the tested SQL-looking contract title also persisted as data. This does not certify every query in the application.
- **Six low findings, `scripts/run_secure.py`:** subprocess import/calls and a partially qualified executable. Calls use argument lists rather than a shell. No tested remote-input command injection was demonstrated. Resolving a trusted absolute OpenSSL executable and controlling the launcher environment remain hardening items.

No high Bandit findings is a scanner result, not proof that the application has no high-risk weaknesses.

## Transport checks

Read-only checks against the real local server observed:

- `GET https://localhost:8443/health`: HTTP 200 and certificate verification result 0 with the explicit local certificate file.
- `GET https://localhost:8443/api/contracts` without cookies: HTTP 401, `Authentication required.`, `Cache-Control: no-store`, HSTS, CSP, no-sniff and frame-denial headers.
- `GET http://127.0.0.1:8000/`: HTTP 307 to `https://localhost:8443/`, `Cache-Control: no-store`.
- Security status: CSRF and Secure cookies both true, plus headers, trusted hosts and audit logging true. Configuration reporting alone does not prove correct enforcement; relevant enforcement is tested separately.

The self-signed certificate is **not automatically trusted by the browser**. Successful explicit-CA curl validation is not equivalent to company-managed certificate trust. Resolve trusted HTTPS through an approved certificate setup before real browser sign-in; do not click through warnings as a production procedure.

## Reproducing the checks

Run from the repository root. Commands overwrite the saved reports/screenshots. Preserve this assessment first if comparing runs. Use a supported Node runtime for JavaScript/browser tools. Keep all temporary credentials, cookies and databases outside source control.

### Automated suites

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider --junitxml=docs/testing/pytest-results.xml
node --test --test-reporter=junit --test-reporter-destination=docs/testing/frontend-results.xml tests/test_frontend.js
```

The Python command currently exits with failure because QA-01 through QA-04 are unresolved. Do not exclude them to obtain a misleading green result.

### Disposable browser fixture

Use a new temporary directory for each run. The seed script refuses an existing database. Run this in a separate terminal; do not use these test accounts or insecure-cookie settings for a shared deployment.

```bash
QA_DIR=$(mktemp -d /private/tmp/sentinel-full-qa.XXXXXX)
.venv/bin/python scripts/seed_qa_demo.py "$QA_DIR/qa.db"
env -u OPENAI_API_KEY -u SCOPE_SENTINEL_LLM_MODEL -u SLACK_BOT_TOKEN \
  SCOPE_SENTINEL_DB="$QA_DIR/qa.db" \
  SCOPE_SENTINEL_AUTH_REQUIRED=true \
  SCOPE_SENTINEL_SECURE_COOKIES=false \
  SCOPE_SENTINEL_ALLOWED_ORIGINS=http://127.0.0.1:8855 \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8855
```

In another terminal, after installing Chromium for `agent-browser` if needed:

```bash
npx --yes agent-browser install
node scripts/verify_browser.mjs
```

The runner is intentionally restricted to port 8855 and expects the fresh fixture's IDs. It mutates only that fixture and writes browser results and nine screenshots. Stop the disposable server with Ctrl+C after testing. The actual assessment used these actions; the published history/approval images were additionally reframed after the run.

### Security scanners

Create the scanner environment with a supported Python interpreter, not the application's old Python 3.9. Use the existing `.local/qa-tools` if repeating this exact environment.

```bash
python3.12 -m venv .local/qa-tools
.local/qa-tools/bin/python -m pip install pip-audit==2.10.1 bandit==1.9.4
.local/qa-tools/bin/pip-audit --path .venv/lib/python3.9/site-packages --format json --output docs/testing/dependency-audit.json
.local/qa-tools/bin/bandit -r app scripts/run_secure.py -f json -o docs/testing/bandit-results.json
.venv/bin/python -m pip check
```

Adjust the audited site-packages path after a runtime migration. Both scanners currently exit nonzero because they report findings. Advisory results can change over time; the saved JSON is the point-in-time evidence, not a permanent clean bill of health.

### Read-only HTTPS verification

With the secure launcher already running:

```bash
curl --cacert .local/localhost-cert.pem -i https://localhost:8443/api/contracts
curl --cacert .local/localhost-cert.pem --output /dev/null \
  --write-out 'status=%{http_code} certificate_verify=%{ssl_verify_result}\n' \
  https://localhost:8443/health
curl -i http://127.0.0.1:8000/
```

## Not verified / remaining approval gates

This was broad local regression testing and targeted security review, not exhaustive testing. No percentage code coverage was measured. In particular, it does not establish:

- Independent penetration-test results, a complete threat model or OWASP ASVS verification.
- Multi-user load, race-condition coverage, distributed rate limiting, recovery under resource exhaustion or parser fuzzing/decompression-bomb resistance.
- Malware scanning, OCR quality for image-only PDFs or all malformed document cases.
- Production trusted TLS, proxies, secret rotation, SSO/MFA, offboarding operations or project/tenant separation.
- PostgreSQL/pgvector end-to-end persistence, migration rollback, encrypted storage or successful backup restoration.
- Real Jira OAuth/Slack permissions, network retry behavior, external AI correctness/privacy or customer e-signatures.
- A complete accessibility audit, Safari/Firefox testing or every possible viewport.
- Company IT/security approval, commercial acceptance, legal validity of SOW interpretations or compliance certification.

Recommended order: resolve runtime/dependency risks and confirmed defects; rerun these tests with no unresolved failures; verify trusted HTTPS and role boundaries in an authorized pilot; then obtain independent security review, backup/load evidence and named company acceptance. The [company approval package](../COMPANY_APPROVAL.md) remains a proposal with pending gates.
