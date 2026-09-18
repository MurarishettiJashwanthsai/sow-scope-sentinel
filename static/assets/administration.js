const $ = id => document.getElementById(id);
function clearFields(...ids) { ids.forEach(id => $(id).value = ""); }
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

  async function authenticate(path) {
    $("bootstrapUser").disabled = true;
    $("loginUser").disabled = true;
    try {
      const result = await api(path, { method: "POST", headers: path.endsWith("/bootstrap") ? { "X-Bootstrap-Token": $("setupToken").value } : {}, body: JSON.stringify({
        name: $("userName").value || "Administrator",
        email: $("userEmail").value,
        password: $("userPassword").value
      }) });
      $("authNotice").textContent = `Logged in as ${result.name} (${result.role}).`;
      clearFields("userName", "userEmail", "userPassword", "setupToken");
      $("securityOutput").textContent = "";
      $("securityOutput").classList.add("hidden");
      window.refreshSessionStatus();
      await refreshUserManagement();
    } catch (error) { $("authNotice").textContent = error.message; }
    finally {
      $("bootstrapUser").disabled = false;
      $("loginUser").disabled = false;
    }
  }
  $("bootstrapUser").addEventListener("click", () => authenticate("/api/auth/bootstrap"));
  $("loginUser").addEventListener("click", () => authenticate("/api/auth/login"));
  $("logoutUser").addEventListener("click", async () => {
    try {
      await api("/api/auth/logout", {method: "POST"});
      clearFields("userName", "userEmail", "userPassword", "setupToken");
      $("authNotice").textContent = "Signed out successfully.";
      // Discard any private results still present in the page after sign-out.
      window.location.replace("/administration");
    } catch (error) { $("authNotice").textContent = error.message; }
  });
  $("loadSecurityStatus").addEventListener("click", async () => {
    try { $("securityOutput").textContent = JSON.stringify(await api("/api/security/status"), null, 2); }
    catch (error) { $("securityOutput").textContent = error.message; }
    $("securityOutput").classList.remove("hidden");
  });
  $("loadSecurityAudit").addEventListener("click", async () => {
    try { $("securityOutput").textContent = JSON.stringify(await api("/api/security/audit-events?limit=100"), null, 2); }
    catch (error) { $("securityOutput").textContent = error.message; }
    $("securityOutput").classList.remove("hidden");
  });

async function refreshUserManagement() {
  try {
    const user = await api("/api/auth/me");
    $("userManagement").classList.toggle("hidden", !user.authenticated || user.role !== "ADMIN");
  } catch { $("userManagement").classList.add("hidden"); }
}
$("createUserForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("createTeamUser").disabled = true;
  try {
    const result = await api("/api/users", {method: "POST", body: JSON.stringify({
      name: $("memberName").value.trim(), email: $("memberEmail").value.trim(),
      password: $("memberPassword").value, role: $("memberRole").value
    })});
    clearFields("memberName", "memberEmail", "memberPassword");
    $("memberRole").value = "VIEWER";
    $("memberNotice").textContent = `${result.name} created as ${result.role}. No invitation email was sent.`;
  } catch (error) { $("memberNotice").textContent = error.message; }
  finally { $("createTeamUser").disabled = false; }
});
refreshUserManagement();
