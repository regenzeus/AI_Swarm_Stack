// Wiki title copy interactions with a fake clipboard and DOM; run: node --test tests/wiki.test.cjs.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const web = path.join(__dirname, "../images/mission-control/web");      // the app's parts in the order index.html loads them (PLT-25)
const source = [...fs.readFileSync(path.join(web, "index.html"), "utf8").matchAll(/<script src="\/static\/(app[^"]*\.js)"/g)]
  .map((m) => fs.readFileSync(path.join(web, "static", m[1]), "utf8")).join("");
const markdown = '---\ntitle: Original title\n---\n# Original title\n\n**Bold** & <tags> [[concepts/test|Link]]\n\n```js\nconst x = "<copy>";\n```\n';

function setup(clipboard) {
  const button = { disabled: false };
  const body = { innerHTML: "", querySelector: () => button };
  const toast = { textContent: "", className: "toast" };
  const elements = new Map(["#view", "#toast", "#nav-side", "#nav-bottom", "#live-chip", "#lgraph"].map((id) => [id, {}]));
  elements.set("#toast", toast);
  const pages = [];
  const context = vm.createContext({
    document: { querySelector: (id) => elements.get(id), addEventListener() {} },
    window: { addEventListener() {}, scrollTo() {} },
    location: { hash: "", hostname: "localhost" },
    history: { state: null, replaceState() {} },
    navigator: { clipboard },
    URLSearchParams,
    EventSource: class {},
    setTimeout() {}, clearTimeout() {}, setInterval() {},
    DOMPurify: { sanitize: (html) => html },
    marked: { parse: () => "<p>Rendered content, not markdown</p>" },
    vGuide() {},
    loadGuide: async () => {},
    explain: (key, html) => html,                         // guide.js: a folded explanation
    fetch: async (url) => ({ ok: true, headers: { get: () => "application/json" }, json: async () => url === "/api/version" ? { version: "test" } : pages.shift() }),
  });
  vm.runInContext(source, context);
  return {
    button, body, toast,
    async render(text = markdown, error) {
      pages.push(error ? { error } : { title: "Original <title>", body: "# Original title\n\nRendered body without frontmatter.\n", markdown: text, links: {}, backlinks: [], meta: {} });
      context.host = body;
      await vm.runInContext('wikiPage(host, "wiki", "concepts/test", { nodes: [], links: [] })', context);
    },
  };
}

test("wiki title has Correct or research and a small copy button with the existing document icon", async () => {
  const app = setup({ writeText: async () => {} });
  await app.render();
  assert.match(app.body.innerHTML, /class="row wrap wtitle"><h1>Original &lt;title&gt;<\/h1><button type="button" class="btn sm primary" id="wrefb">[^]*?Correct or research<\/button><button type="button" class="btn sm" data-copy-markdown><svg[^]*?<\/svg>Copy markdown<\/button>/);
  assert.match(app.body.innerHTML, /Linked mentions/);
  assert.match(app.body.innerHTML, /Local graph/);
});

test("copies the untouched markdown and only toasts after the write resolves", async () => {
  let finish;
  const writes = [];
  const app = setup({ writeText: (text) => { writes.push(text); return new Promise((resolve) => { finish = resolve; }); } });
  await app.render();
  const copying = app.button.onclick();
  assert.deepEqual(writes, [markdown]);
  assert.equal(app.button.disabled, true);
  assert.equal(app.toast.textContent, "");
  finish();
  await copying;
  assert.equal(app.toast.textContent, "Copied");
  assert.equal(app.toast.className, "toast on");
  assert.equal(app.button.disabled, false);
});

test("copies the current page after navigating, including an empty page", async () => {
  const writes = [];
  const app = setup({ writeText: async (text) => { writes.push(text); } });
  for (const text of [markdown, "# Another page\n\nSecond page.\n", "# Windows page\r\n\r\nText.\r\n", ""]) {
    await app.render(text);
    await app.button.onclick();
    assert.equal(writes.at(-1), text);
  }
});

test("a rejected clipboard write shows an error, permits retry, and never reports success", async () => {
  let reject;
  let fail = true;
  const app = setup({ writeText: () => fail ? new Promise((_, rejectWrite) => { reject = rejectWrite; }) : Promise.resolve() });
  await app.render();
  const copying = app.button.onclick();
  assert.equal(app.toast.textContent, "");
  reject(new Error("Permission denied"));
  await copying;
  assert.equal(app.toast.textContent, "Could not copy: Permission denied");
  assert.equal(app.toast.className, "toast on err");
  assert.equal(app.button.disabled, false);
  fail = false;
  await app.button.onclick();
  assert.equal(app.toast.textContent, "Copied");
  assert.equal(app.toast.className, "toast on");
});

for (const clipboard of [undefined, {}]) {
  test(`unavailable clipboard (${clipboard ? "missing writeText" : "missing API"}) shows only an error`, async () => {
    const app = setup(clipboard);
    await app.render();
    await app.button.onclick();
    assert.equal(app.toast.textContent, "Could not copy: Clipboard unavailable");
    assert.equal(app.toast.className, "toast on err");
    assert.equal(app.button.disabled, false);
  });
}

test("a missing wiki page does not offer a copy action", async () => {
  const app = setup({ writeText: async () => assert.fail("must not copy") });
  await app.render("", "no such page");
  assert.doesNotMatch(app.body.innerHTML, /data-copy-markdown/);
  assert.equal(app.button.onclick, undefined);
});
