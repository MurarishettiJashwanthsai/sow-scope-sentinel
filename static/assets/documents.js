if (window.location.protocol === "file:") window.location.replace("http://127.0.0.1:8000/documents");
  let documents = [];
  const library = document.getElementById("library");
  const search = document.getElementById("search");
  const summary = document.getElementById("summary");

  const showDeleted = document.getElementById("showDeleted");

  async function api(url, options={}) {
    let response;
    try {
      const method=(options.method||"GET").toUpperCase();
      const headers={"Content-Type":"application/json",...(options.headers||{})};
      if(!["GET","HEAD","OPTIONS"].includes(method)){
        let csrf=document.cookie.split("; ").find(item=>item.startsWith("scope_csrf="))?.split("=").slice(1).join("=");
        if(!csrf){const tokenResponse=await fetch("/api/security/csrf",{credentials:"same-origin"});csrf=(await tokenResponse.json()).csrf_token;}
        if(csrf)headers["X-CSRF-Token"]=decodeURIComponent(csrf);
      }
      response = await fetch(url,{...options,headers});
    }
    catch (error) { throw new Error("Cannot reach the Scope Sentinel API. Start the local server first."); }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(window.formatApiError(body, response.status));
    return body;
  }
  function escapeHtml(value) { return String(value).replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[c]); }
  function render() {
    const term = search.value.trim().toLowerCase();
    const rows = documents.filter(row => (showDeleted.checked || row.status !== "DELETED") && (!term || `${row.title} ${row.version} ${row.document_type} ${row.id}`.toLowerCase().includes(term)));
    summary.textContent = `${rows.length} of ${documents.length} document${documents.length === 1 ? "" : "s"}`;
    library.innerHTML = rows.length ? rows.map(row => `
      <article class="card">
        <span class="type ${row.status === "DELETED" ? "deleted" : ""}">${row.status === "DELETED" ? "DELETED" : escapeHtml(row.document_type)}</span>
        <h2>${escapeHtml(row.title)}</h2>
        <p class="meta">Version ${escapeHtml(row.version)} · Document #${row.id}</p>
        <p class="meta">${row.parent_contract_id ? `Parent SOW #${row.parent_contract_id}` : "Original SOW"}</p>
        <p class="meta">${row.clause_count} clauses · ${escapeHtml(row.effective_date || "No effective date")}</p>
        <div class="actions">${row.status === "DELETED"
          ? `<button class="secondary" data-restore-id="${row.id}">Restore</button>`
          : `<a class="button" href="/documents/${row.id}">Open &amp; Edit</a><button class="danger" data-delete-id="${row.id}" data-title="${escapeHtml(row.title)}">Delete</button>`}
        </div>
      </article>`).join("") : '<div class="empty">No matching SOW documents found.</div>';
  }
  async function load() {
    try { documents = await api("/api/contracts?include_deleted=true"); render(); }
    catch (error) { summary.textContent = error.message; library.innerHTML = ""; }
  }
  search.addEventListener("input", render);
  showDeleted.addEventListener("change", render);
  document.getElementById("refresh").addEventListener("click", load);
  library.addEventListener("click",async event=>{
    const deleteButton=event.target.closest("button[data-delete-id]");
    const restoreButton=event.target.closest("button[data-restore-id]");
    if(deleteButton){
      const confirmed=window.confirm(`Delete “${deleteButton.dataset.title}”?\n\nIt will leave the active library, but its audit history will be preserved.`);
      if(!confirmed)return;
      deleteButton.disabled=true;
      try{await api(`/api/contracts/${deleteButton.dataset.deleteId}`,{method:"DELETE"});await load();}
      catch(error){summary.textContent=error.message;deleteButton.disabled=false;}
    }
    if(restoreButton){
      restoreButton.disabled=true;
      try{await api(`/api/contracts/${restoreButton.dataset.restoreId}/restore`,{method:"POST"});await load();}
      catch(error){summary.textContent=error.message;restoreButton.disabled=false;}
    }
  });
  load();
