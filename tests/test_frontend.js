// Run with: node --test tests/test_frontend.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../static/assets/workspace.js"), "utf8");

function workspace(navigationType, hash = "") {
  const events = {};
  const replacements = [];
  const redirects = [];
  const scrolls = [];
  const context = {
    performance: { getEntriesByType: () => [{ type: navigationType }] },
    history: { scrollRestoration: "auto", state: null, replaceState: (_, __, url) => replacements.push(url) },
    location: { pathname: "/", search: "?contract_id=2", hash, replace: url => redirects.push(url) },
    addEventListener: (name, fn) => { events[name] = fn; },
    document: { addEventListener: () => {} },
    window: { scrollTo: options => scrolls.push(options) },
  };
  vm.runInNewContext(source, context);
  return { context, events, replacements, redirects, scrolls };
}

test("reload clears the section anchor without losing the selected SOW", () => {
  const app = workspace("reload", "#reviewPanel");
  assert.equal(app.context.history.scrollRestoration, "manual");
  assert.deepEqual(app.replacements, ["/?contract_id=2"]);
  app.events.pageshow();
  assert.equal(app.scrolls[0].top, 0);
});

test("legacy Administration anchors open the separate page", () => {
  for (const type of ["navigate", "reload"]) {
    const app = workspace(type, "#adminPanel");
    assert.deepEqual(app.redirects, ["/administration?contract_id=2"]);
  }
});

test("reload without an anchor still starts at the top", () => {
  const app = workspace("reload");
  app.events.pageshow();
  assert.equal(app.scrolls[0].top, 0);
  assert.equal(app.replacements.length, 0);
});

test("normal section navigation keeps its anchor", () => {
  const app = workspace("navigate", "#historyPanel");
  app.events.pageshow();
  assert.equal(app.replacements.length, 0);
  assert.equal(app.scrolls.length, 0);
});

test("validation errors are field messages, not object placeholders", () => {
  const { context } = workspace("navigate");
  assert.equal(context.window.formatApiError({ detail: [{ loc: ["body", "title"], msg: "Too short" }] }, 422), "title: Too short");
  assert.match(context.window.formatApiError({}, 401), /sign in/i);
});
