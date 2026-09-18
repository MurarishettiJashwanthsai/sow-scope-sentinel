if (window.location.protocol === "file:") window.location.replace("http://127.0.0.1:8000/documents");
  const documentId = Number(window.location.pathname.split("/").filter(Boolean).at(-1));
  let currentDocument = null;
  const $ = id => document.getElementById(id);

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
    const body = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(window.formatApiError(body, response.status));
    return body;
  }
  function escapeHtml(value) { return String(value).replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[c]); }
  function suggestedVersion(version) {
    const parts = String(version).split(".");
    const last = Number(parts.at(-1));
    if (Number.isFinite(last)) { parts[parts.length-1]=String(last+1); return parts.join("."); }
    return `${version}.1`;
  }
  function setEditing(editing) {
    $("title").disabled=!editing; $("version").disabled=!editing; $("effectiveDate").disabled=!editing; $("content").readOnly=!editing;
    $("edit").classList.toggle("hidden",editing); $("save").classList.toggle("hidden",!editing); $("cancel").classList.toggle("hidden",!editing);
    if (editing) { $("version").value=suggestedVersion(currentDocument.version); $("content").focus(); $("notice").innerHTML='<span class="warning">Your changes will be saved as a new revision. The signed version will remain unchanged.</span>'; }
  }
  function renderDocument(document, clauses) {
    currentDocument=document;
    $("pageTitle").textContent=document.title;
    $("pageSubtitle").textContent=`${document.document_type} · Version ${document.version} · Document #${document.id}`;
    $("title").value=document.title; $("version").value=document.version; $("effectiveDate").value=document.effective_date||""; $("content").value=document.content;
    $("useDashboard").href=`/?contract_id=${document.root_contract_id}`;
    $("requestApproval").href=`/approvals?target_type=CONTRACT&target_id=${document.id}`;
    $("history").innerHTML=document.revisions.map(item=>`<div class="item ${item.id===document.id?"active":""}"><strong>v${escapeHtml(item.version)} · ${escapeHtml(item.document_type)}</strong><p>Document #${item.id} · ${escapeHtml(item.effective_date||"No effective date")}</p><a href="/documents/${item.id}">Open this version</a></div>`).join("");
    $("clauses").innerHTML=clauses.length?clauses.map(item=>`<div class="item"><strong>${escapeHtml(item.clause_ref)} · ${escapeHtml(item.category)}</strong><p>${escapeHtml(item.text)}</p></div>`).join(""):"No clauses extracted.";
    $("notice").textContent="Click Edit document to make changes. Saving creates a new revision and preserves this version.";
  }
  async function load() {
    if (!Number.isInteger(documentId) || documentId < 1) { $("notice").textContent="Invalid document number."; $("edit").disabled=true; return; }
    try { const [document,clauses]=await Promise.all([api(`/api/contracts/${documentId}`),api(`/api/contracts/${documentId}/clauses`)]); renderDocument(document,clauses); }
    catch(error) { $("notice").textContent=error.message; $("pageTitle").textContent="Document unavailable"; $("edit").disabled=true; }
  }
  $("edit").addEventListener("click",()=>setEditing(true));
  $("cancel").addEventListener("click",()=>{ renderDocument(currentDocument,[]); load(); setEditing(false); });
  $("save").addEventListener("click",async()=>{
    const button=$("save"); button.disabled=true;
    try {
      const result=await api(`/api/contracts/${currentDocument.root_contract_id}/revisions/text`,{method:"POST",body:JSON.stringify({title:$("title").value,version:$("version").value,effective_date:$("effectiveDate").value||null,content:$("content").value})});
      $("notice").textContent=`Revision #${result.id} saved successfully. Opening the new version…`;
      window.location.assign(`/documents/${result.id}`);
    } catch(error) { $("notice").textContent=error.message; button.disabled=false; }
  });
  $("delete").addEventListener("click",async()=>{
    if(!currentDocument)return;
    const scope=currentDocument.parent_contract_id===null?"This will also remove its amendments from the active library.":"Only this amendment or revision will be removed from the active library.";
    if(!window.confirm(`Delete “${currentDocument.title}” version ${currentDocument.version}?\n\n${scope}\nAudit and ticket history will be preserved.`))return;
    const button=$("delete");button.disabled=true;
    try{await api(`/api/contracts/${currentDocument.id}`,{method:"DELETE"});window.location.assign("/documents");}
    catch(error){$("notice").textContent=error.message;button.disabled=false;}
  });
  load();
