const $ = id => document.getElementById(id);
let records = [];
let currentUser = null;
let selectedRecord = null;

async function api(url, options = {}) {
  const headers = { "Content-Type": "application/json" };
  if (options.method === "POST") {
    const tokenResponse = await fetch("/api/security/csrf");
    if (!tokenResponse.ok) throw new Error("Unable to initialize request protection.");
    headers["X-CSRF-Token"] = (await tokenResponse.json()).csrf_token;
  }
  const response = await fetch(url, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(window.formatApiError(body, response.status));
  return body;
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function render() {
  const filter = $("statusFilter").value;
  const rows = records.filter(row => !filter || row.status === filter);
  $("requestList").replaceChildren();
  $("approvalCount").textContent = `${rows.length} matching requests (latest 100 loaded)`;
  if (!rows.length) $("requestList").append(node("p", "No matching approval requests."));
  for (const row of rows) {
    const card = node("article", undefined, "evidence");
    card.append(node("strong", `#${row.id} · ${row.title} · ${row.status}`));
    card.append(node("p", `${row.target_type === "CONTRACT" ? "SOW / amendment" : "Commercial draft"} #${row.target_id} · Submitted by ${row.requester_name} · ${row.created_at} UTC`));
    card.append(node("p", row.request_reason));
    if (row.reviewer_name) card.append(node("p", `${row.reviewer_name}: ${row.decision_reason} · ${row.reviewed_at} UTC`));
    const button = node("button", "Open snapshot & review", "secondary");
    button.addEventListener("click", () => openRecord(row.id));
    card.append(button);
    $("requestList").append(card);
  }
}

async function loadTargets() {
  $("targetId").replaceChildren(new Option("Choose an item…", ""));
  const rows = await api(`/api/approvals/targets?target_type=${$("targetType").value}`);
  for (const row of rows) {
    const suffix = row.version ? `v${row.version}` : `${row.currency} ${Number(row.price).toFixed(2)}`;
    $("targetId").add(new Option(`${row.title} · ${suffix} · #${row.id}`, row.id));
  }
  const params = new URLSearchParams(location.search);
  if (params.get("target_type") === $("targetType").value) $("targetId").value = params.get("target_id") || "";
}

async function refresh() {
  $("refreshApprovals").disabled = true;
  try {
    currentUser = await api("/api/auth/me");
    if (!currentUser.authenticated) throw new Error("Approval records require a named login, including in demo mode.");
    records = await api("/api/approvals");
    render();
    $("notice").textContent = "Approvals apply only to the submitted snapshot, not future revisions or customer acceptance.";
    const canSubmit = ["ADMIN", "PM", "SALES"].includes(currentUser.role);
    $("submitApproval").disabled = !canSubmit;
    await loadTargets();
  } catch (error) {
    records = [];
    render();
    $("notice").textContent = error.message;
    $("submitApproval").disabled = true;
  } finally { $("refreshApprovals").disabled = false; }
}

async function openRecord(id) {
  selectedRecord = null;
  $("reviewPanel").classList.add("hidden");
  $("decisionReason").value = "";
  $("reviewNotice").textContent = "";
  try {
    const row = await api(`/api/approvals/${id}`);
    selectedRecord = row;
    $("reviewHeading").textContent = `Review #${row.id} · ${row.title}`;
    $("snapshot").textContent = row.snapshot.content || row.snapshot.draft_text;
    $("snapshotMeta").textContent = row.target_type === "CONTRACT"
      ? `Document #${row.target_id} · ${row.snapshot.document_type} · Version ${row.snapshot.version} · Effective ${row.snapshot.effective_date || "date not specified"}`
      : `Draft #${row.target_id} · ${row.snapshot.currency} ${Number(row.snapshot.price).toFixed(2)} · ${row.snapshot.estimated_hours} hours · ${row.snapshot.timeline_days} days`;
    $("snapshotData").textContent = JSON.stringify(row.snapshot, null, 2);
    $("snapshotHash").textContent = `Snapshot SHA-256: ${row.snapshot_hash}`;
    const roles = row.target_type === "CONTRACT" ? ["ADMIN", "PM"] : ["ADMIN", "SALES"];
    const allowed = row.status === "PENDING" && currentUser && roles.includes(currentUser.role) && currentUser.id !== row.requested_by;
    $("approve").disabled = !allowed;
    $("reject").disabled = !allowed;
    $("decisionReason").disabled = !allowed;
    if (!allowed) $("reviewNotice").textContent = row.status !== "PENDING"
      ? `Final decision: ${row.status}. ${row.reviewer_name}: ${row.decision_reason}`
      : "A different authorized reviewer must decide this request. SOW: PM/Admin. Commercial draft: Sales/Admin.";
    $("reviewPanel").classList.remove("hidden");
    $("reviewPanel").scrollIntoView({ block: "start" });
  } catch (error) { $("notice").textContent = error.message; }
}

$("submissionForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("submitApproval").disabled = true;
  try {
    const result = await api("/api/approvals", { method: "POST", body: JSON.stringify({
      target_type: $("targetType").value, target_id: Number($("targetId").value), reason: $("requestReason").value.trim()
    }) });
    $("requestReason").value = "";
    await refresh();
    $("notice").textContent = `Request #${result.id} submitted. A different authorized reviewer must approve or reject it.`;
  } catch (error) { $("notice").textContent = error.message; }
  finally { $("submitApproval").disabled = !currentUser || !["ADMIN", "PM", "SALES"].includes(currentUser.role); }
});

async function decide(decision) {
  if (!selectedRecord) return;
  const id = selectedRecord.id;
  $("approve").disabled = true;
  $("reject").disabled = true;
  try {
    await api(`/api/approvals/${id}/decision`, { method: "POST", body: JSON.stringify({ decision, reason: $("decisionReason").value.trim() }) });
    await refresh();
    await openRecord(id);
  } catch (error) {
    $("reviewNotice").textContent = error.message;
    $("approve").disabled = false;
    $("reject").disabled = false;
  }
}
$("approve").addEventListener("click", () => decide("APPROVED"));
$("reject").addEventListener("click", () => decide("REJECTED"));
$("refreshApprovals").addEventListener("click", refresh);
$("statusFilter").addEventListener("change", render);
$("targetType").addEventListener("change", () => loadTargets().catch(error => $("notice").textContent = error.message));
const kind = new URLSearchParams(location.search).get("target_type");
if (["CONTRACT", "CHANGE_ORDER"].includes(kind)) $("targetType").value = kind;
refresh();
