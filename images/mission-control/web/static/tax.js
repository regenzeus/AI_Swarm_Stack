// TAX-10, TAX-11: the tax desk's result, on the page of your task "Your taxes" (task.js taskOverview) and as pages of its
// own for its files (#/tax/<year>/workbook | belege | return). Per year: the papers found per form, the sums per form
// line, what is missing, the questions with the way to Needs you, the earlier return as the reader understood it, and
// where each file lies on the NAS. The figures come from GET /api/tax, which the app serves to your own signed-in
// session only; they are never kept on this device, in the app's state or in a log. Loaded before app.js: it uses
// app.js's helpers only when a page is drawn.
let taxYear = null;
const TAX_PAGES = { workbook: "The workbook", belege: "Belege", return: "Your return as read" };
const TAX_FACTS = [["assessment", "Assessed"], ["church_tax", "Church tax"], ["children", "Children"], ["commute_km", "Commute, km one way"],
  ["commute_days", "Days at the workplace"], ["home_office_days", "Days at home"]];

async function taxData() {
  try { return await api("/api/tax"); }
  catch (e) { return { years: [], refused: /403/.test(e.message) ? "Your tax figures show only on your own devices, signed in." : e.message }; }
}
function taxPick(d) {                              // the year you chose, else the newest one that asks you something, else with papers
  const ys = d.years || [];
  return ys.find((y) => y.year === taxYear) || ys.find((y) => y.prepared && (y.questions || []).length) || ys.find((y) => y.prepared && y.total)
    || ys.find((y) => y.prepared) || ys[0];
}
const taxFact = (k, v) => (v == null || v === "" ? "–" : typeof v === "boolean" ? (v ? "yes" : "no") : k === "assessment" ? String(v) : nf(v));
function taxCopy(text) {
  const done = () => toast("Copied: paste it into the Explorer's address bar");
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done, () => toast("Could not copy: select the path and copy it", true));
  else toast("Select the path and copy it", true);
}
function taxPath(p) {                              // a place on the NAS share, whole, with a copy button
  return p ? `<div class="taxpath"><code class="wrap">${esc(p)}</code><button type="button" class="icon-btn" data-tcopy="${esc(p)}" title="Copy the path">${ic.copy}</button></div>` : "";
}
function taxBind(el) {
  $$("[data-tcopy]", el).forEach((b) => (b.onclick = () => taxCopy(b.dataset.tcopy)));
}

// ---------- the result on the task's page ----------
async function taxViewInto(el, t) {
  if (!el) return;
  const d = await taxData();
  if (!el.isConnected) return;
  const head = `<div class="row between wrap gap-2"><h2>Your tax drafts</h2>${explain("tax-what", `The tax desk's draft per year, from the papers in your mail and your earlier returns. Each run brings it up to date; correct a paper in Belege.csv on the NAS and it keeps your change. ${how("taxes")}`, "About the drafts")}</div>`;
  if (d.refused) { el.innerHTML = `${head}<div class="small muted mt-1">${esc(d.refused)}</div>`; return; }
  const v = taxPick(d);
  if (!v) {
    el.innerHTML = head + emptyState(esc(d.error || "The drafts show here after the tax desk's first run."), t?.door === "flow" ? `<button class="btn sm" data-tflow="${t.id}">${ic.play}Run now</button>` : "");
    $$("[data-tflow]", el).forEach((b) => (b.onclick = () => act({ action: "task_run", id: +b.dataset.tflow }, "Started: its steps show here as they run")));
    return;
  }
  taxYear = v.year;
  el.innerHTML = `${head}<div class="banner tax-draft mt-2">${ic.alert}<span class="grow wrap">${esc(d.draft || "")}</span></div>
    <div class="seg sm taxyears mt-3" role="tablist" aria-label="Year">${d.years.map((y) => `<button type="button" data-tyear="${y.year}" class="${y.year === v.year ? "on" : ""}">${y.year}</button>`).join("")}</div>
    <div id="taxyear">${taxYearHtml(v, d)}</div>`;
  $$("[data-tyear]", el).forEach((b) => (b.onclick = () => { taxYear = +b.dataset.tyear; taxViewInto(el, t); }));
  taxBind(el);
}
function taxYearHtml(v, d) {
  const forms = v.papers || [], miss = v.missing || [], qs = v.questions || [], lines = v.lines || [];
  const kpis = [[nf(v.total), v.total === 1 ? "paper found" : "papers found"], [nf(forms.length), forms.length === 1 ? "form" : "forms"]];
  if (v.prepared) kpis.push([nf(miss.length), "expected, missing"], [nf(qs.length), qs.length === 1 ? "question for you" : "questions for you"]);
  const byForm = {};
  for (const l of lines) (byForm[l.name] = byForm[l.name] || []).push(l);
  const files = [v.workbook ? ["workbook", v.files?.workbook] : null, (v.belege || []).length ? ["belege", v.files?.belege] : null, v.erklaerung ? ["return", v.files?.erklaerung] : null].filter(Boolean);
  const r = v.return;
  return `<div class="small muted mt-2">${v.prepared ? (v.open ? "Being prepared: each run adds what came." : "Prepared; the year is closed.") : r ? "Your own return, the base for the years after it." : "Papers filed under this year; it is not summed."}</div>
    <div class="tmnums mt-2">${kpis.map(([x, l]) => `<div class="card pad tmnum"><b>${esc(x)}</b><span class="tiny faint">${esc(l)}</span></div>`).join("")}</div>
    ${forms.length ? `<div class="section"><h3>Papers found</h3><div class="list taxlist">${forms.map((f) => `<div><div class="grow ttl wrap">${esc(f.name)}</div><span class="num">${nf(f.n)}</span></div>`).join("")}</div></div>` : ""}
    ${v.prepared ? `<div class="section"><h3>Sums per form line</h3>${lines.length ? Object.entries(byForm).map(([f, ls]) => `<div class="taxform"><div class="small muted">${esc(f)}</div>
        <div class="list taxlist">${ls.map((l) => `<div><div class="grow"><div class="ttl wrap">${esc(l.label || "(no label)")}</div><div class="sub wrap">${[l.line, `${nf(l.papers.length)} paper${l.papers.length === 1 ? "" : "s"}`].filter(Boolean).map(esc).join(" · ")}</div></div><span class="num">${esc(eur(l.sum))}</span></div>`).join("")}</div></div>`).join("")
      : `<div class="small muted">No amounts yet.</div>`}</div>
      <div class="section"><h3>Missing</h3>${miss.length ? `<div class="list taxlist">${miss.map((m) => `<div><div class="grow"><div class="ttl wrap">${esc(m.label)}</div><div class="sub wrap">${esc(m.name)}${m.last_year ? ` · in your ${m.last_year} return${m.last != null ? `: ${esc(eur(m.last))}` : ""}` : ""}</div></div></div>`).join("")}</div>`
        : `<div class="small muted">Nothing your earlier returns lead to expect is missing.</div>`}</div>
      <div class="section"><div class="row between wrap gap-2"><h3>Questions for you</h3>${qs.length ? `<a class="btn sm primary" href="#/decide">${ic.check}Answer in Needs you</a>` : ""}</div>
        ${qs.length ? `<ul class="tjudge">${qs.map((q) => `<li class="wrap">${esc(q.text)}</li>`).join("")}</ul>` : `<div class="small muted">None open for ${v.year}.</div>`}</div>` : ""}
    ${r ? `<div class="section"><h3>Your ${v.year} return, as read</h3>${r.unread ? `<div class="small err-t wrap">Not read: ${esc(r.unread)}</div>` : ""}
      <div class="taxfacts">${TAX_FACTS.map(([k, l]) => `<div><span class="tiny faint">${esc(l)}</span><b>${esc(taxFact(k, r[k]))}</b></div>`).join("")}</div>
      ${(r.items || []).length ? `<div class="list taxlist mt-2">${r.items.map((i) => `<div><div class="grow"><div class="ttl wrap">${esc(i.label || i.line || "(no label)")}</div><div class="sub wrap">${[i.name, i.line, i.recurring ? "comes every year" : ""].filter(Boolean).map(esc).join(" · ")}</div></div><span class="num">${i.value != null ? esc(eur(i.value)) : "–"}</span></div>`).join("")}</div>` : ""}</div>` : ""}
    <div class="section"><h3>Files</h3><div class="row wrap gap-2">${files.map(([k]) => `<a class="btn sm" href="#/tax/${v.year}/${k}">${ic.doc}${esc(TAX_PAGES[k])}</a>`).join("") || `<span class="small muted">None yet.</span>`}</div>
      <div class="tiny faint mt-2">The year's folder on the NAS</div>${taxPath(v.files?.folder)}</div>
    <div class="tiny faint section">${d.ran ? `The desk ran ${esc(when(d.ran))}; ` : ""}shown as of ${esc(when(d.made))}.</div>`;
}

// ---------- a file of a year as a page: the workbook, Belege, the earlier return ----------
async function vTax() {
  const y = +route.args[0], what = TAX_PAGES[route.args[1]] ? route.args[1] : "workbook";
  const back = (S?.tasks || []).find((t) => t.door === "flow" && t.result_view === "tax");
  const backHtml = `<a class="back" href="${back ? `#/task/${back.id}` : "#/workflows"}">${ic.back}${back ? esc(back.title) : "Workflows"}</a>`;
  view.innerHTML = `${backHtml}<div class="stack"><div class="skeleton" style="height:96px"></div><div class="skeleton" style="height:320px"></div></div>`;
  const d = await taxData();
  if (route.name !== "tax") return;
  const v = (d.years || []).find((x) => x.year === y);
  if (d.refused || !v) { view.innerHTML = `${backHtml}<div class="card pad small muted">${esc(d.refused || `The tax desk has nothing for ${y || "that year"} yet.`)}</div>`; return; }
  const path = what === "workbook" ? v.files?.workbook : what === "belege" ? v.files?.belege : v.files?.erklaerung;
  let body;
  if (what === "belege") {
    const rows = v.belege || [];
    body = rows.length ? `<div class="list taxlist taxbelege">${rows.map((b) => `<div><div class="grow"><div class="ttl wrap">${esc(b.name || "(no copy yet: the mail only)")}</div>
        <div class="sub wrap">${[b.form, b.kind, b.issuer, b.date ? day(b.date) : "", b.checked ? "checked by you" : ""].filter(Boolean).map(esc).join(" · ")}</div>${b.nas ? taxPath(b.nas) : ""}</div>
        <span class="num">${b.amount != null ? esc(eur(b.amount)) : "–"}</span></div>`).join("")}</div>`
      : `<div class="small muted">No paper filed for ${y} yet.</div>`;
  } else {
    const text = what === "workbook" ? v.workbook : v.erklaerung;
    body = text ? `<article class="md reader">${md(String(text).replace(/^#[^\n]*\n+(>[^\n]*\n+)?/, ""))}</article>` : `<div class="small muted">Not made for ${y}.</div>`;
  }
  view.innerHTML = `${backHtml}<div class="hero"><div class="grow"><h1>${esc(TAX_PAGES[what])} · ${y}</h1></div></div>
    <div class="banner tax-draft">${ic.alert}<span class="grow wrap">${esc(d.draft || "")}</span></div>
    <div class="card pad-l section">${body}</div>
    ${path ? `<div class="section"><div class="tiny faint">On the NAS${what === "belege" ? ": correct a paper here, the desk keeps your change" : ""}</div>${taxPath(path)}</div>` : ""}`;
  taxBind(view);
}
