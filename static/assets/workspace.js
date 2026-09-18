// Run before rendering so refresh never restores a stale hash or scroll position.
(() => {
  // Keep previously bookmarked dashboard Administration links working.
  if (location.pathname === "/" && location.hash === "#adminPanel") {
    location.replace("/administration" + location.search);
    return;
  }
  const reloading = performance.getEntriesByType("navigation")[0]?.type === "reload";
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  if (reloading && location.hash) history.replaceState(history.state, "", location.pathname + location.search);
  addEventListener("pageshow", () => {
    if (reloading || !location.hash) window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  });
  window.formatApiError = (body, status) => {
    if (status === 401) return "Please sign in through Administration to continue.";
    if (status === 403) return typeof body.detail === "string" ? body.detail : "Your account cannot perform this action.";
    if (Array.isArray(body.detail)) return body.detail.map(error =>
      error.loc.filter(part => !["body", "query"].includes(part)).join(" · ") + ": " + error.msg
    ).join("\n");
    return typeof body.detail === "string" ? body.detail : "The request could not be completed (" + status + ").";
  };
  document.addEventListener("DOMContentLoaded", () => {
    const main = document.querySelector("main");
    if (!main) return;
    const bar = document.createElement("div");
    bar.className = "workspace-bar";
    bar.innerHTML = '<span class="workspace-label">SCOPE SENTINEL / WORKSPACE</span><span id="sessionStatus" role="status">Connecting…</span>';
    main.prepend(bar);
    document.querySelectorAll(".nav-icon").forEach(icon => icon.setAttribute("aria-hidden", "true"));
    document.querySelectorAll(".notice").forEach(notice => { notice.setAttribute("role", "status"); notice.setAttribute("aria-live", "polite"); });

    function navigateSection() {
      const target = location.hash ? document.getElementById(location.hash.slice(1)) : null;
      if (target?.tagName === "DETAILS") target.open = true;
      document.querySelectorAll(".sidebar nav a").forEach(link => {
        const url = new URL(link.href);
        const selected = location.pathname.startsWith("/documents")
          ? url.pathname === "/documents"
          : url.pathname === location.pathname && url.hash === location.hash;
        link.classList.toggle("active", selected);
        if (selected) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
      });
      if (target) requestAnimationFrame(() => target.scrollIntoView({ block: "start", behavior: "instant" }));
    }
    // Same-page links keep the current contract query and avoid reloading the form.
    document.querySelectorAll('.sidebar a[href^="/#"]').forEach(link => {
      if (location.pathname === "/") link.href = location.pathname + location.search + new URL(link.href).hash;
      link.addEventListener("click", () => {
        if (location.hash === new URL(link.href).hash) navigateSection();
      });
    });
    addEventListener("hashchange", navigateSection);
    navigateSection();

    window.refreshSessionStatus = async () => {
      const status = document.getElementById("sessionStatus");
      try {
        const [systemResponse, userResponse] = await Promise.all([fetch("/api/system/status"), fetch("/api/auth/me")]);
        if (!systemResponse.ok) throw new Error("offline");
        const system = await systemResponse.json();
        const user = userResponse.ok ? await userResponse.json() : {};
        status.textContent = user.authenticated ? user.name + " · " + user.role : system.auth_required ? "Sign in required" : "Local demo · Login optional";
        status.className = user.authenticated ? "session-ready" : "session-demo";
      } catch { status.textContent = "Server unavailable"; status.className = "session-demo"; }
    };
    window.refreshSessionStatus();
  });
})();
