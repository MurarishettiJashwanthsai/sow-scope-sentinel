// Opening this static file directly bypasses FastAPI, so always use the app server.
  if (window.location.protocol === "file:") {
    window.location.replace("http://127.0.0.1:8000/");
  }

  let contractId = null;
  let activeContractTitle = "";
  let ticketId = null;
  const $ = (id) => document.getElementById(id);
  const goTo = (id) => $(id).scrollIntoView({ behavior: "smooth", block: "start" });
  function clearFields(...ids) {
    ids.forEach(id => {
      const field = $(id);
      if (field) field.value = "";
    });
  }

  async function api(url, options = {}) {
    if (window.location.protocol === "file:") {
      throw new Error("The API is not running on a file:// page. Start the server and open http://127.0.0.1:8000 instead.");
    }
    let response;
    try {
      const isForm = options.body instanceof FormData;
      const method = (options.method || "GET").toUpperCase();
      let headers = isForm ? { ...(options.headers || {}) } : { "Content-Type": "application/json", ...(options.headers || {}) };
      if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
        let csrf = document.cookie.split("; ").find(item => item.startsWith("scope_csrf="))?.split("=").slice(1).join("=");
        if (!csrf) {
          const tokenResponse = await fetch("/api/security/csrf", { credentials: "same-origin" });
          csrf = (await tokenResponse.json()).csrf_token;
        }
        if (csrf) headers["X-CSRF-Token"] = decodeURIComponent(csrf);
      }
      response = await fetch(url, { ...options, headers });
    } catch (error) {
      throw new Error("Cannot reach the Scope Sentinel API. Start it with: .venv/bin/python scripts/run_secure.py, then open https://localhost:8443.");
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(window.formatApiError(body, response.status));
    return body;
  }

  $("saveContract").addEventListener("click", async () => {
    const button = $("saveContract");
    button.disabled = true;
    try {
      const result = await api("/api/contracts/text", {
        method: "POST",
        body: JSON.stringify({
          title: $("contractTitle").value,
          content: $("contractText").value,
          version: $("contractVersion").value,
          effective_date: $("effectiveDate").value || null
        })
      });
      contractId = result.id;
      activeContractTitle = $("contractTitle").value.trim();
      $("historyContractId").value = contractId;
      $("contractNotice").textContent = `Contract #${result.id} indexed with ${result.clause_count} clauses.\nCategories: ${result.categories.join(", ")}`;
      clearFields("contractTitle", "contractVersion", "effectiveDate", "contractFile", "contractText");
      await loadOverview();
      goTo("ticketPanel");
    } catch (error) { $("contractNotice").textContent = error.message; }
    finally { button.disabled = false; }
  });

  $("uploadContract").addEventListener("click", async () => {
    const file = $("contractFile").files[0];
    if (!file) { $("contractNotice").textContent = "Choose a PDF, TXT or Markdown file first."; return; }
    const button = $("uploadContract");
    button.disabled = true;
    const form = new FormData(); form.append("file", file);
    const query = new URLSearchParams({ title: $("contractTitle").value, version: $("contractVersion").value });
    if ($("effectiveDate").value) query.set("effective_date", $("effectiveDate").value);
    try {
      const result = await api(`/api/contracts/upload?${query}`, { method: "POST", body: form });
      contractId = result.id;
      activeContractTitle = $("contractTitle").value.trim();
      $("historyContractId").value = contractId;
      $("contractNotice").textContent = `Uploaded ${file.name}; indexed ${result.clause_count} clauses as version ${result.version}.`;
      clearFields("contractTitle", "contractVersion", "effectiveDate", "contractFile", "contractText");
      await loadOverview();
      goTo("ticketPanel");
    } catch (error) { $("contractNotice").textContent = error.message; }
    finally { button.disabled = false; }
  });

  $("loadRealistic").addEventListener("click", async () => {
    const button = $("loadRealistic");
    button.disabled = true;
    try {
      const result = await api("/api/demo/realistic-sow");
      $("contractTitle").value = result.title;
      $("contractVersion").value = "1.0";
      $("contractText").value = result.content;
      $("contractNotice").textContent = `${result.notice}\nThe realistic SOW is loaded. Click Index contract to process it.`;
    } catch (error) { $("contractNotice").textContent = error.message; }
    finally { button.disabled = false; }
  });

  $("analyseTicket").addEventListener("click", async () => {
    if (!contractId) { $("ticketNotice").textContent = "Index a contract first."; return; }
    const button = $("analyseTicket");
    button.disabled = true;
    try {
      const result = await api("/api/tickets", {
        method: "POST",
        body: JSON.stringify({
          contract_id: contractId,
          external_key: $("externalKey").value || null,
          title: $("ticketTitle").value,
          description: $("ticketDescription").value,
          acceptance_criteria: $("acceptance").value,
          estimated_hours: $("hours").value.trim() ? Number($("hours").value) : null
        })
      });
      ticketId = result.ticket.id;
      const analysis = result.analysis;
      $("quoteResult").textContent = "";
      $("quoteApproval").classList.add("hidden");
      $("quoteResult").classList.add("hidden");
      $("ticketNotice").textContent = `Ticket #${ticketId} analysed successfully.`;
      $("decisionBadge").textContent = analysis.decision.replaceAll("_", " ");
      $("decisionBadge").className = `badge ${analysis.decision}`;
      $("decisionReason").textContent = `${analysis.reason} Confidence: ${Math.round(analysis.confidence * 100)}%.`;
      $("evidenceList").innerHTML = result.evidence.map(item => `
        <div class="evidence"><span class="score">score ${item.score.toFixed(3)}</span>
          <strong>Clause ${escapeHtml(item.clause_ref)} · ${escapeHtml(item.category)}</strong>
          <p>${escapeHtml(item.clause_text)}</p><small>${escapeHtml(item.explanation)}</small>
        </div>`).join("") || '<p>No clause evidence was available.</p>';
      $("resultPanel").classList.remove("hidden");
      $("quotePanel").classList.toggle("hidden", analysis.decision === "IN_SCOPE");
      clearFields("ticketTitle", "ticketDescription", "acceptance", "externalKey", "hours");
      await loadOverview();
      goTo("resultPanel");
    } catch (error) { $("ticketNotice").textContent = error.message; }
    finally { button.disabled = false; }
  });

  $("createQuote").addEventListener("click", async () => {
    if (!ticketId) return;
    $("createQuote").disabled = true;
    try {
      if (!$("hourlyCost").value.trim() || !$("margin").value.trim()) {
        throw new Error("Enter the hourly cost and target margin before generating a draft.");
      }
      const result = await api(`/api/tickets/${ticketId}/change-orders`, {
        method: "POST",
        body: JSON.stringify({
          internal_hourly_cost: Number($("hourlyCost").value),
          target_margin: Number($("margin").value),
          currency: "USD"
        })
      });
      $("quoteResult").textContent = result.draft_text;
      $("quoteApproval").href = `/approvals?target_type=CHANGE_ORDER&target_id=${result.id}`;
      $("quoteApproval").classList.remove("hidden");
      $("quoteResult").classList.remove("hidden");
      clearFields("hourlyCost", "margin");
      $("quoteResult").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) { $("quoteResult").textContent = error.message; $("quoteResult").classList.remove("hidden"); }
    finally { $("createQuote").disabled = false; }
  });

  $("addAmendment").addEventListener("click", async () => {
    if (!contractId) { $("amendmentNotice").textContent = "Index a parent SOW first."; return; }
    $("addAmendment").disabled = true;
    try {
      const result = await api(`/api/contracts/${contractId}/amendments/text`, {
        method: "POST",
        body: JSON.stringify({
          title: `${activeContractTitle || "Contract"} Amendment ${$("amendmentVersion").value}`,
          content: $("amendmentText").value,
          version: $("amendmentVersion").value,
          effective_date: $("amendmentDate").value || new Date().toISOString().slice(0, 10),
          supersedes_clause_refs: $("supersedesRefs").value.split(",").map(x => x.trim()).filter(Boolean)
        })
      });
      $("amendmentNotice").textContent = `Amendment #${result.id} indexed with ${result.clause_count} clauses.`;
      clearFields("amendmentVersion", "amendmentDate", "supersedesRefs", "amendmentText");
      await loadOverview();
    } catch (error) { $("amendmentNotice").textContent = error.message; }
    finally { $("addAmendment").disabled = false; }
  });



  $("refreshQueue").addEventListener("click", async () => {
    const button = $("refreshQueue");
    button.disabled = true;
    button.textContent = "Refreshing…";
    try {
      const rows = await api("/api/dashboard/review-queue");
      $("reviewQueue").innerHTML = rows.length ? rows.map(row =>
        `<div class="evidence"><strong>${escapeHtml(row.external_key || `Ticket ${row.id}`)} · ${escapeHtml(row.decision)}</strong><p>${escapeHtml(row.title)}</p><small>${escapeHtml(row.reason)}</small><br>
          <button data-review-id="${row.id}" data-decision="IN_SCOPE">Approve in scope</button>
          <button class="secondary" data-review-id="${row.id}" data-decision="OUT_OF_SCOPE">Confirm out of scope</button></div>`
      ).join("") : "The review queue is empty.";
    } catch (error) { $("reviewQueue").textContent = error.message; }
    finally { button.disabled = false; button.textContent = "Refresh queue"; }
  });

  $("reviewQueue").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-review-id]");
    if (!button) return;
    try {
      await api(`/api/tickets/${button.dataset.reviewId}/review`, {
        method: "POST",
        body: JSON.stringify({
          reviewer: "Local Project Manager",
          decision: button.dataset.decision,
          reason: button.dataset.decision === "IN_SCOPE"
            ? "Reviewed against the effective contract and approved by the Project Manager."
            : "Reviewed against the effective contract and confirmed as requiring change control."
        })
      });
      $("refreshQueue").click();
    } catch (error) { $("reviewQueue").textContent = error.message; }
  });

  $("loadHistory").addEventListener("click", async () => {
    const button = $("loadHistory");
    button.disabled = true;
    button.textContent = "Loading…";
    const typedId = $("historyContractId").value;
    const selectedId = typedId;
    const suffix = selectedId ? `?contract_id=${encodeURIComponent(selectedId)}` : "";
    try {
      const rows = await api(`/api/history${suffix}`);
      $("historyList").innerHTML = rows.length ? rows.map(row => `
        <div class="evidence"><strong>${escapeHtml(row.external_key || `Ticket ${row.id}`)} · ${escapeHtml(row.status)}</strong>
          <span class="score">${escapeHtml(row.created_at)}</span><p>${escapeHtml(row.title)}</p>
          <small>${escapeHtml(row.contract_title)} v${escapeHtml(row.contract_version)} · ${row.analysis_count} analysis run(s) · ${row.review_count} review(s) · ${row.change_order_count} quote(s)</small><br>
          <button class="secondary" data-history-id="${row.id}">Open full audit trail</button></div>`).join("") : "No saved history for this contract.";
      $("historyDetail").classList.add("hidden");
    } catch (error) { $("historyList").textContent = error.message; }
    finally { button.disabled = false; button.textContent = "Load history"; }
  });

  $("historyList").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-history-id]");
    if (!button) return;
    try {
      const result = await api(`/api/tickets/${button.dataset.historyId}/history`);
      $("historyDetail").textContent = JSON.stringify(result, null, 2);
      $("historyDetail").classList.remove("hidden");
    } catch (error) { $("historyDetail").textContent = error.message; $("historyDetail").classList.remove("hidden"); }
  });

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
  }

  async function loadSelectedContract(selected = new URLSearchParams(window.location.search).get("contract_id")) {
    if (!selected) return;
    try {
      const document = await api(`/api/contracts/${encodeURIComponent(selected)}`);
      contractId = document.root_contract_id;
      activeContractTitle = document.title;
      $("historyContractId").value = contractId;
      $("contractNotice").textContent = `Using ${document.title} v${document.version} (SOW #${contractId}) for ticket analysis.`;
      $("ticketNotice").textContent = `Ready to check tickets against ${document.title}.`;
      return true;
    } catch (error) { $("contractNotice").textContent = error.message; }
    return false;
  }

  async function loadOverview() {
    try {
      const documents = await api("/api/contracts");
      const sows = documents.filter(row => row.document_type === "SOW");
      $("sowCount").textContent = sows.length;
      $("amendmentCount").textContent = documents.length - sows.length;
      $("activeSow").replaceChildren(new Option("Choose a saved SOW…", ""));
      sows.forEach(row => $("activeSow").add(new Option(row.title + " · v" + row.version + " · #" + row.id, row.id)));
      $("activeSow").value = contractId || "";
      $("ticketCount").textContent = (await api("/api/history")).length;
    } catch { /* The session banner explains when sign-in or reconnection is needed. */ }
  }
  $("activeSow").addEventListener("change", async () => {
    const selected = $("activeSow").value;
    $("activeSow").disabled = true;
    const loaded = selected ? await loadSelectedContract(selected) : true;
    $("activeSow").disabled = false;
    if (!loaded) {
      $("activeSow").value = contractId || "";
      return;
    }
    if (!selected) {
      contractId = null;
      activeContractTitle = "";
      $("historyContractId").value = "";
      $("contractNotice").textContent = "Select a saved SOW or index a new contract.";
      $("ticketNotice").textContent = "Select a contract before running a scope check.";
    }
    ticketId = null;
    $("resultPanel").classList.add("hidden");
    $("quotePanel").classList.add("hidden");
    const url = new URL(location.href);
    if (contractId) url.searchParams.set("contract_id", contractId);
    else url.searchParams.delete("contract_id");
    history.replaceState(null, "", url);
  });

  loadSelectedContract().then(loadOverview);
