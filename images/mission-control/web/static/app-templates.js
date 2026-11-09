// GEN-34: the template editor (docs/AI-STACK.md §5) is Workflow Builder's editor SDK (Apache 2.0, synergycodes), not our
// own: its palette, canvas, a form per block drawn from the block's schema, decisions with a branch per answer, undo,
// zoom and minimap. It is one ES module (images/mission-control/flow, built into /static/vendor/flow), loaded only when a
// template opens. The template's YAML stays the truth: the editor's Save hands the drawing, turned back into the
// template's own fields, to template_save, which checks it with the graph model and writes the canonical YAML; block
// positions go to the template's layout beside it. A test run starts from what was saved.
let TE = null;                                       // the template open: {name, spec, layout, yaml}
let TBF = null;                                      // the mounted editor: {name, el, destroy}
let TB_DESC = { text: "", name: "", busy: false };                // the description being written: kept through the list's live redraws
const FLOW = "/static/vendor/flow/";
const FLOWV = (document.currentScript?.src || "").split("?")[1] || "";   // the page's version: a new editor is never an old cached one

function tbList() { return S?.engine?.templates || []; }
function tbAgents() { return S?.engine?.agents || []; }
function tbTheme() { return document.documentElement.dataset.theme === "light" ? "light" : "dark"; }
function tbUnmount() { if (TBF) { try { TBF.destroy(); } catch (_) { /* already gone with its page */ } TBF = null; } }
window.addEventListener("hashchange", () => { if (TBF && !location.hash.startsWith(`#/templates/${encodeURIComponent(TBF.name)}`)) tbUnmount(); });

function vTemplates() {
  if (!S?.engine) {
    view.innerHTML = `<div class="hero"><div class="grow"><h1>Templates</h1><p>Templates run on the engine, which this deployment starts at the cutover. Until then they are built and tried in the preview.</p></div></div>`;
    return;
  }
  const name = route.args[0];
  if (name) return tbEditor(name);
  tbUnmount();
  TE = null;
  const list = tbList();
  view.innerHTML = `
  <div class="hero"><div class="grow"><h1>Templates</h1><p>${nf(list.length)} template${list.length === 1 ? "" : "s"} · <a href="#/packs">Packs${packList().pending.length ? ` (${nf(packList().pending.length)} waiting)` : ""}</a> · ${explain("templates-what", "A template is a plan of blocks that runs the same way each time it starts: agents, decisions, commands, changes, approvals, waits and tracker steps, joined into forks, joins, branches and loops. Build one here, save it, and start a test run to watch it.")}</p></div></div>
  <form class="card tb-new" id="tbnew">
    <textarea name="text" rows="3" placeholder="Describe what should happen, e.g. When a bug is reported, reproduce it, fix it, run the tests, and let me approve before it is delivered." aria-label="What the template should do">${esc(TB_DESC.text)}</textarea>
    <div class="row tb-newrow"><input name="name" value="${esc(TB_DESC.name)}" placeholder="Its name, e.g. bug-fix" aria-label="The new template's name" class="grow" required pattern="[a-z][a-z0-9-]*(/[a-z0-9-]+)?">
      <button class="btn" type="button" id="tbempty">${ic.plus}Start empty</button><button class="btn primary" id="tbdraft"${TB_DESC.busy ? " disabled" : ""}>${TB_DESC.busy ? "Drafting…" : "Draft it"}</button></div>
    ${explain("templates-describe", "Draft it: the intake's model draws the template from your description with the stack's agents, the graph model checks it, and it opens in the editor as a draft to look over, change and save. Start empty opens the editor with one block.")}
  </form>
  <div class="stack">${list.map((t) => `<a class="card eng-row" href="#/templates/${encodeURIComponent(t.name)}">
    <div class="row"><b class="grow wrap">${esc(t.name)}</b><span class="pill">${esc(t.source)}</span></div>
    <div class="sub wrap">${t.problem ? `<span class="err-t">${esc(t.problem)}</span>` : `${nf(t.nodes)} blocks${t.about ? ` · ${esc(t.about)}` : ""}`}</div></a>`).join("")}</div>`;
  const f = $("#tbnew");
  f.oninput = () => { TB_DESC.text = f.text.value; TB_DESC.name = f.name.value; };
  $("#tbempty").onclick = () => {
    if (!f.name.reportValidity()) return;
    const n = f.name.value.trim();
    TE = { name: n, spec: { template: n, nodes: { start: { block: "agent", title: "First step", agent: tbAgents()[0]?.id || "" } }, edges: [] }, layout: {}, yaml: "" };
    location.hash = `#/templates/${encodeURIComponent(n)}`;
  };
  f.onsubmit = async (e) => {
    e.preventDefault();
    const n = f.name.value.trim(), text = f.text.value.trim();
    if (!text) { f.text.focus(); return; }
    const busy = (on) => { TB_DESC.busy = on; const b = $("#tbdraft"); if (b) { b.disabled = on; b.textContent = on ? "Drafting…" : "Draft it"; } };
    busy(true);
    const r = await act({ action: "template_describe", text, name: n }, "Drafted: look it over, change what you like, and save");
    busy(false);
    const res = r?.result || r;
    if (!res || res.ok === false || !res.spec) return;
    TB_DESC = { text: "", name: "", busy: false };
    TE = { name: res.name || n, spec: res.spec, layout: {}, yaml: res.yaml || "" };
    location.hash = `#/templates/${encodeURIComponent(TE.name)}`;
  };
}

function tbEditor(name) {
  if (TBF && TBF.name === name && document.body.contains(TBF.el)) return;     // the editor keeps its own state: never redrawn under you
  tbUnmount();
  if (!TE || TE.name !== name) {
    const t = tbList().filter((x) => x.name === name).sort((a, b) => (b.source === "draft") - (a.source === "draft"))[0];   // a draft is the newer version
    if (!t || !t.spec) { view.innerHTML = `<a class="back" href="#/templates">${ic.back} Templates</a><div class="card"><p>${t?.problem ? esc(t.problem) : `There is no template ${esc(name)}.`}</p></div>`; return; }
    TE = { name, spec: JSON.parse(JSON.stringify(t.spec)), layout: t.layout || {}, yaml: t.yaml, problem: t.problem || "" };
  }
  view.innerHTML = `
  <a class="back" href="#/templates">${ic.back} Templates</a>
  <div class="hero"><div class="grow"><h1 class="wrap">${esc(TE.spec.template || name)}</h1><p>${esc(TE.spec.about || "")} ${explain("templates-edit", "Drag a block from the palette onto the canvas and draw an arrow from the block before it. Arrows out of one block fork, arrows into one block join, a Decision sends the run down the branch its agent names, and an arrow back to an earlier block is a loop (its rounds are set on the block it leaves). Select a block to set its fields in the panel. Save checks the whole template and keeps it as a draft for review.")}</p></div>
    <button class="btn" id="tbtest">${ic.next}Test run</button></div>
  ${TE.problem ? `<div class="card tb-problem"><b>Mend it here:</b> ${esc(TE.problem.replace(/^template \S+(, |: )/, ""))}</div>` : ""}
  <div class="tb-flow" id="tbflow"><p class="muted tb-wait">Opening the editor…</p></div>
  <details class="card" data-keep="tbyaml"><summary>The template as saved${TE.yaml ? "" : " (not saved yet)"}</summary><pre class="wrap small" id="tbyaml">${esc(TE.yaml || "")}</pre></details>`;
  const el = $("#tbflow");
  const q = FLOWV ? `?${FLOWV}` : "";
  if (!document.querySelector(`link[href="${FLOW}flow.css${q}"]`)) document.head.insertAdjacentHTML("beforeend", `<link rel="stylesheet" href="${FLOW}flow.css${q}">`);
  import(`${FLOW}flow.js${q}`).then((F) => {
    if (!document.body.contains(el)) return;
    el.innerHTML = "";
    const m = F.mount(el, { name: TE.spec.template || name, spec: TE.spec, layout: TE.layout, agents: tbAgents(), roles: S?.engine?.roles || [], theme: tbTheme(), logo: "/static/icons/icon-192.png",
      onProblem: (why) => toast(why, true),
      onSave: async ({ spec, layout }) => {
        const r = await act({ action: "template_save", spec, layout }, "Saved as a draft for review");
        if (!r || r.ok === false) return false;
        TE.spec = spec; TE.layout = layout; TE.problem = ""; $(".tb-problem")?.remove(); TE.yaml = r.yaml || r.result?.yaml || ""; TE.name = r.name || r.result?.name || TE.name;
        const y = $("#tbyaml");
        if (y) y.textContent = TE.yaml;
        return true;
      } });
    TBF = { name, el, destroy: m.destroy };
  }).catch((e) => { el.innerHTML = `<div class="card"><p class="err-t">The editor did not load: ${esc(String(e.message || e))}</p></div>`; });
  $("#tbtest").onclick = async () => {
    const r = await act({ action: "template_test", name: TE.name }, "Test run started");
    const run = r?.run || r?.result?.run;
    if (run) location.hash = `#/engine/${encodeURIComponent(run)}`;
  };
}
