// GEN-21, GEN-32: the deployment's packs (docs/AI-STACK.md §6). Each pack that runs, at its approved commit, with what
// it brings; each commit that waits for the owner, with everything needed to decide it: its manifest, its agents'
// prompts, its commands, its problems and its diff from the commit that runs now; and what is refused, with why.
// A commit runs only after Approve; meanwhile the old one keeps running.
let PK_SIG = "";                                     // the packs as last drawn: the page is redrawn only when they change
function packList() { return S?.engine?.packs || { packs: [], pending: [], refused: [] }; }
function packSig() { return JSON.stringify(S?.engine?.packs || {}); }

function packBrings(p) {
  const n = (xs, one, many) => xs?.length ? `${nf(xs.length)} ${xs.length === 1 ? one : many}` : "";
  return [n(p.agents, "agent", "agents"), n(p.skills, "skill", "skills"), n(p.templates, "template", "templates"),
    n(p.jobs, "command", "commands"), n(p.exams, "exam set", "exam sets")].filter(Boolean).join(" · ") || "nothing yet";
}

function vPacks() {
  const L = packList(), name = route.args[0];
  PK_SIG = packSig();
  if (name) return packPage(name, L);
  view.innerHTML = `
  <a class="back" href="#/templates">${ic.back} Templates</a>
  <div class="hero"><div class="grow"><h1>Packs</h1><p>${nf(L.packs.length)} running${L.pending.length ? ` · <b>${nf(L.pending.length)} waiting for you</b>` : ""} · <a href="#/trackers">Trackers</a> · ${explain("packs-what", "A pack is a domain kept outside the stack's repository: its agents, skills, commands, templates and exams, pinned by commit in the deployment's packs.txt. A new commit runs only after you approve it here; until then the commit you approved before keeps running. Its commands are still approved on each worker by their hash.")}</p></div></div>
  ${L.pending.map((p) => `<a class="card eng-row pk-wait" href="#/packs/${encodeURIComponent(p.name)}"><div class="row"><b class="grow wrap">${esc(p.name)}: ${p.runs ? `update to ${esc(p.commit.slice(0, 12))}` : `first commit ${esc(p.commit.slice(0, 12))}`}</b><span class="pill">waits for you</span></div>
    <div class="sub wrap">${esc(packBrings(p))}${p.problems.length ? ` · <span class="err-t">${nf(p.problems.length)} problem${p.problems.length === 1 ? "" : "s"}</span>` : ""}</div></a>`).join("")}
  <div class="stack">${L.packs.map((p) => `<a class="card eng-row" href="#/packs/${encodeURIComponent(p.name)}"><div class="row"><b class="grow wrap">${esc(p.name)}${p.version ? ` ${esc(p.version)}` : ""}</b><span class="pill">${esc(p.commit.slice(0, 12))}</span></div>
    <div class="sub wrap">${p.about ? `${esc(p.about)} · ` : ""}${esc(packBrings(p))}</div></a>`).join("")}</div>
  ${L.refused.length ? `<div class="section-h"><h2>Refused</h2></div><div class="stack">${L.refused.map((r) => `<div class="card pad"><b>${esc(r.name)}</b>${r.commit ? ` <span class="tiny faint">${esc(r.commit.slice(0, 12))}</span>` : ""}<div class="sub wrap err-t">${esc(r.why)}</div></div>`).join("")}</div>` : ""}
  ${!L.packs.length && !L.pending.length && !L.refused.length ? `<div class="card"><p class="muted">No packs: this deployment's packs.txt lists none.</p></div>` : ""}`;
}

function packPage(name, L) {
  const run = L.packs.find((p) => p.name === name), wait = L.pending.find((p) => p.name === name), no = L.refused.filter((r) => r.name === name);
  if (!run && !wait && !no.length) { view.innerHTML = `<a class="back" href="#/packs">${ic.back} Packs</a><div class="card"><p>There is no pack ${esc(name)}.</p></div>`; return; }
  const agents = (xs) => xs.map((a) => `<details class="pk-item"><summary><b>${esc(a.id)}</b>${a.purpose ? ` · ${esc(a.purpose)}` : ""}${a.harness ? ` <span class="tiny faint">${esc(a.harness)}${a.model ? ` · ${esc(a.model)}` : ""}</span>` : ""}</summary><pre class="wrap small">${esc(a.prompt || "")}</pre></details>`).join("");
  const jobs = (xs) => xs.map((j) => `<details class="pk-item"><summary><b>${esc(j.kind)}</b>${j.about ? ` · ${esc(j.about)}` : ""}</summary><pre class="wrap small">${esc(JSON.stringify(j.spec, null, 2))}</pre></details>`).join("");
  view.innerHTML = `
  <a class="back" href="#/packs">${ic.back} Packs</a>
  <div class="hero"><div class="grow"><h1 class="wrap">${esc(name)}</h1><p>${run ? `runs ${esc(run.commit.slice(0, 12))}${run.version ? ` (${esc(run.version)})` : ""}` : "does not run yet"}${(run || wait)?.about ? ` · ${esc((run || wait).about)}` : ""}</p></div></div>
  ${wait ? `<div class="card pad pk-decide">
    <div class="row wrap"><b class="grow">${wait.runs ? `Update from ${esc(wait.runs.slice(0, 12))} to ${esc(wait.commit.slice(0, 12))}?` : `Run its first commit, ${esc(wait.commit.slice(0, 12))}?`}</b>
      <button class="btn" data-pk="pack_refuse">Refuse</button><button class="btn primary" data-pk="pack_approve">Approve</button></div>
    <p class="sub">${esc(packBrings(wait))}. ${wait.runs ? "The commit that runs now keeps running until you approve." : "Nothing of it runs until you approve."}</p>
    ${wait.problems.length ? `<div class="err-t small">${wait.problems.map(esc).join("<br>")}</div>` : ""}
    ${wait.agents.length ? `<div class="section-h"><h2>Its agents and their prompts</h2></div>${agents(wait.agents)}` : ""}
    ${wait.jobs.length ? `<div class="section-h"><h2>Its commands</h2></div>${jobs(wait.jobs)}` : ""}
    ${wait.templates.length ? `<p class="small">Templates: ${wait.templates.map(esc).join(", ")}</p>` : ""}
    <details data-keep="pkdiff" open><summary>What changed${wait.runs ? ` since ${esc(wait.runs.slice(0, 12))}` : " (the whole pack)"}</summary><pre class="wrap small pk-diff">${esc(wait.diff || "")}</pre></details>
  </div>` : ""}
  ${run ? `<div class="card pad"><div class="section-h"><h2>What it brings, at ${esc(run.commit.slice(0, 12))}</h2></div>
    ${agents(run.agents)}${jobs(run.jobs)}
    ${run.skills.length ? `<p class="small">Skills: ${run.skills.map((s) => esc(s.id)).join(", ")}</p>` : ""}
    ${run.templates.length ? `<p class="small">Templates: ${run.templates.map((t) => `<a href="#/templates/${encodeURIComponent(t.name)}">${esc(t.name)}</a>`).join(", ")}</p>` : ""}
    ${run.exams.length ? `<p class="small">Exam sets: ${run.exams.map(esc).join(", ")}</p>` : ""}
    ${run.mcp.length ? `<p class="small">MCP servers: ${run.mcp.map(esc).join(", ")}</p>` : ""}
    ${run.problems.length ? `<div class="err-t small">${run.problems.map(esc).join("<br>")}</div>` : ""}</div>` : ""}
  ${no.map((r) => `<div class="card pad"><div class="sub wrap err-t">${esc(r.why)}</div></div>`).join("")}`;
  view.querySelectorAll("[data-pk]").forEach((b) => (b.onclick = async () => {
    const why = b.dataset.pk === "pack_refuse" ? prompt("Why not? (kept with the refusal)", "") : "";
    if (why === null) return;
    b.disabled = true;
    const r = await act({ action: b.dataset.pk, name, commit: wait.commit, why }, b.dataset.pk === "pack_approve" ? "Approved: this commit runs from now on" : "Refused: the commit that ran keeps running");
    if (!r) b.disabled = false;
  }));
}
