// REC-06: the Measures view of a deployment's tracker of record (#/measures, ?tracker=<name> when it has more than one):
// the measures its pack declares, computed from the stack's read cache with the records behind each number
// (#/measures/<tracker>/m/<measure>), the records missing a required work product, a link of a type, or a required
// field, the record types with their templates, and each record with its links both ways (#/measures/<tracker>/r/<key>).
// From GET /api/records, which the tracker poller writes after each pass (ops/domain/records.py); nothing here is typed
// in, kept on the device or written to the tracker. Loaded before app.js: it uses app.js's helpers only when drawn.
let msrLink = "";

async function msrData() {
  try { return await api("/api/records"); }
  catch (e) { return { trackers: [], error: /403/.test(e.message) ? "The records show on your own devices, signed in." : e.message }; }
}
const msrField = (f) => String(f).replace(/_/g, " ");      // a field as the pack names it, in words: affected_version -> affected version
const msrPct = (v) => (v == null ? "–" : `${nf(v * 100)} %`);
const msrHours = (h) => (h == null ? "–" : h >= 72 ? `${nf(h / 24, 1)} days` : `${nf(h, h < 10 ? 1 : 0)} h`);
const msrHome = (t) => `#/measures?tracker=${encodeURIComponent(t.name)}`;
const msrRecHref = (t, key) => `#/measures/${encodeURIComponent(t.name)}/r/${encodeURIComponent(key)}`;
function msrValue(m) {                             // [the number, what it is of]
  if (m.kind === "share") return [msrPct(m.value), m.of ? `${nf(m.n)} of ${nf(m.of)} records` : "no record to count yet"];
  if (m.kind === "duration") return [msrHours(m.value), `${m.stat} of ${nf(m.n)} record${m.n === 1 ? "" : "s"}${m.open.length ? ` · ${nf(m.open.length)} not there yet` : ""}`];
  return [nf(m.value), m.groups.length ? `record${m.value === 1 ? "" : "s"} in ${nf(m.groups.length)} group${m.groups.length === 1 ? "" : "s"}` : `record${m.value === 1 ? "" : "s"}`];
}
function msrRow(t, key, extra = "") {             // one record as a row: its key, title, type and status, a tap to its page
  const r = t.records[key];
  if (!r) return `<div><div class="grow"><div class="ttl wrap">${esc(key)}</div><div class="sub wrap">not in the stack's copy of ${esc(t.name)}</div></div></div>`;
  return `<a href="${msrRecHref(t, key)}"><div class="grow"><div class="ttl wrap">${esc(key)} · ${esc(r.title)}</div>
    <div class="sub wrap">${[r.type_name, r.status].filter(Boolean).map(esc).join(" · ")}${extra}</div></div>${ic.next}</a>`;
}
const msrList = (t, keys, empty, extra = () => "") => (keys.length ? `<div class="card list">${keys.map((k) => msrRow(t, k, extra(k))).join("")}</div>` : `<div class="small muted">${esc(empty)}</div>`);
const msrBack = (t) => `<a class="back" href="${t ? msrHome(t) : "#/measures"}">${ic.back}Measures</a>`;
const msrSkel = () => `<div class="stack"><div class="skeleton" style="height:96px"></div><div class="skeleton" style="height:320px"></div></div>`;

async function vMeasures() {
  const [tn, what, id] = route.args;
  view.innerHTML = msrSkel();
  const d = await msrData();
  if (route.name !== "measures") return;
  const ts = d.trackers || [];
  const t = ts.find((x) => x.name === (tn || route.q.get("tracker"))) || ts.find((x) => !x.problem) || ts[0];
  if (t && !t.problem && what === "m") return msrMeasure(t, id);
  if (t && !t.problem && what === "r") return msrRecord(t, id);
  const head = `<div class="hero"><div class="grow row between wrap gap-2"><h1>Measures</h1>${explain("msr-what", `Each number is computed from the stack's copy of the tracker of record, read one way after every pass of the tracker poller; nobody types it in, and nothing is written back. What counts, the record types, their required fields, work products and links, come from the deployment's pack. Tap a number for the records behind it. ${how("measures")}`, "About measures")}</div></div>`;
  if (!t) {
    view.innerHTML = head + emptyState(esc(d.error || "No tracker of this deployment names its records. A tracker with records: <pack> in trackers.yaml fills this page after the poller's next pass."), `<a class="btn sm" href="#/guide/measures">${ic.doc}How records come in</a>`, "card pad");
    return;
  }
  const seg = ts.length > 1 ? `<div class="seg sm mb-3" role="tablist" aria-label="Tracker">${ts.map((x) => `<a href="${msrHome(x)}" class="${x.name === t.name ? "on" : ""}">${esc(x.name)}</a>`).join("")}</div>` : "";
  if (t.problem) { view.innerHTML = `${head}${seg}<div class="card pad small err-t wrap">${esc(t.problem)}</div>`; return; }
  const n = Object.keys(t.records).length;
  const links = t.links.filter((l) => l.needed_by.length).concat(t.links.filter((l) => !l.needed_by.length));
  if (!links.some((l) => l.id === msrLink)) msrLink = links[0]?.id || "";
  const need = (r) => r.missing.map((m) => ` · no ${esc(m.type_name)} (${esc(m.link_name)})`).join("");
  view.innerHTML = `${head}${seg}
    <div class="small muted wrap">${esc(t.name)} · ${t.read_only ? "read-only · " : ""}${nf(n)} record${n === 1 ? "" : "s"}${t.untyped ? `, ${nf(t.untyped)} of no type` : ""} · read ${esc(when(t.synced))}</div>
    <div class="grid msr-grid section">${t.measures.map((m) => { const [v, of] = msrValue(m);
      return `<div class="card kpi msr" data-href="#/measures/${encodeURIComponent(t.name)}/m/${encodeURIComponent(m.id)}"><div class="kpi-l wrap">${esc(m.name)}</div><div class="kpi-v">${esc(v)}</div><div class="kpi-s wrap">${esc(of)}</div></div>`; }).join("")
      || `<div class="small muted">The pack declares no measures.</div>`}</div>
    <div class="section"><div class="section-h"><h2>Missing a work product</h2><span class="pill${t.missing_work_products.length ? " warn" : " ok"}">${nf(t.missing_work_products.length)}</span></div>
      ${msrList(t, t.missing_work_products.map((r) => r.key), "Every record has the work products its type needs.", (k) => need(t.missing_work_products.find((r) => r.key === k)))}</div>
    <div class="section"><div class="section-h"><h2>Missing a link</h2></div>
      ${links.length ? `<div class="seg sm msr-links mb-3" role="tablist" aria-label="Link type">${links.map((l) => `<button type="button" data-mlink="${esc(l.id)}" class="${l.id === msrLink ? "on" : ""}">${esc(l.name)} <span class="tiny">${nf(t.missing_links[l.id].length)}</span></button>`).join("")}</div><div id="msrlinks"></div>`
        : `<div class="small muted">The pack declares no link types.</div>`}</div>
    <div class="section"><div class="section-h"><h2>Missing a required field</h2><span class="pill${t.missing_fields.length ? " warn" : " ok"}">${nf(t.missing_fields.length)}</span></div>
      ${msrList(t, t.missing_fields.map((r) => r.key), "Every record has the fields its type needs.", (k) => ` · no ${t.missing_fields.find((r) => r.key === k).missing.map((f) => esc(msrField(f))).join(", ")}`)}</div>
    <div class="section"><div class="section-h"><h2>Record types</h2></div><div class="card list">${t.types.map((x) => `<div><div class="grow">
        <div class="ttl wrap">${esc(x.name)}</div><div class="sub wrap">${[x.fields.length ? `fields ${x.fields.map(msrField).join(", ")}` : "", ...x.needs.map((m) => `a ${m.type_name} (${m.link_name})`), x.links.length ? `linked as ${x.links.map((l) => t.links.find((y) => y.id === l)?.name || l).join(", ")}` : ""].filter(Boolean).map(esc).join(" · ") || "nothing required"}</div>
        ${x.template ? `<details class="msr-tpl"><summary class="tiny faint">Template</summary><article class="md small">${md(x.template)}</article></details>` : ""}</div><span class="num">${nf(x.n)}</span></div>`).join("")}</div></div>
    ${t.gates.length ? `<div class="section"><div class="section-h"><h2>Approved by a person only</h2></div><div class="card list">${t.gates.map((g) => `<div><div class="grow"><div class="ttl wrap">${esc(t.types.find((x) => x.id === g.type)?.name || g.type)} to ${esc(g.to)}</div><div class="sub wrap">only a tap by the role ${esc(g.role)}</div></div></div>`).join("")}</div></div>` : ""}
    <div class="tiny faint section">Shown as of ${esc(when(d.made))}.</div>`;
  const drawLinks = () => {
    const el = $("#msrlinks");
    if (!el) return;
    const l = links.find((x) => x.id === msrLink);
    const scope = l.needed_by.length ? `of the types that need it (${l.needed_by.map((y) => t.types.find((x) => x.id === y)?.name || y).join(", ")})` : "of every type";
    el.innerHTML = `<div class="tiny faint mb-2 wrap">Records ${esc(scope)} with no link "${esc(l.name)}" or "${esc(l.inverse)}"</div>${msrList(t, t.missing_links[l.id], "None: every one has it.")}`;
    $$("[data-mlink]").forEach((b) => b.classList.toggle("on", b.dataset.mlink === msrLink));
  };
  $$("[data-mlink]").forEach((b) => (b.onclick = () => { msrLink = b.dataset.mlink; drawLinks(); }));
  drawLinks();
}

// ---------- one measure: its number and the records behind it ----------
function msrMeasure(t, id) {
  const m = t.measures.find((x) => x.id === id);
  if (!m) { view.innerHTML = `${msrBack(t)}<div class="card pad small muted">The pack declares no measure ${esc(id || "")}.</div>`; return; }
  const [v, of] = msrValue(m);
  const hrs = (rows) => (k) => ` · ${esc(msrHours((rows.find((r) => r.key === k) || {}).hours))}`;
  const part = (m2) => (m.kind === "share"
    ? `<h3 class="mt-3">Counted · ${nf(m2.n)}</h3>${msrList(t, m2.counted, "None.")}<h3 class="mt-3">Not counted · ${nf(m2.not_counted.length)}</h3>${msrList(t, m2.not_counted, "None.")}`
    : m.kind === "duration"
      ? `<h3 class="mt-3">Measured · ${nf(m2.n)}</h3>${msrList(t, m2.rows.map((r) => r.key), "None yet.", hrs(m2.rows))}${m2.open.length ? `<h3 class="mt-3">Not there yet · ${nf(m2.open.length)}</h3>${msrList(t, m2.open, "")}` : ""}`
      : msrList(t, m2.counted, "None."));
  view.innerHTML = `${msrBack(t)}<div class="hero"><div class="grow"><h1 class="wrap">${esc(m.name)}</h1><p class="wrap">${esc(m.about)}</p></div></div>
    <div class="card kpi"><div class="kpi-v">${esc(v)}</div><div class="kpi-s wrap">${esc(of)}</div></div>
    ${m.groups.length ? m.groups.map((g) => { const [gv, gof] = msrValue({ ...m, ...g, groups: [] });
      return `<div class="section"><div class="section-h wrap"><h2 class="wrap">${esc(g.group)}</h2><span class="small muted">${esc(gv)} · ${esc(gof)}</span></div>${part(g)}</div>`; }).join("")
      : `<div class="section">${part(m)}</div>`}
    <div class="tiny faint section">Computed from ${esc(t.name)}, read ${esc(when(t.synced))}.</div>`;
}

// ---------- one record: its fields, what it lacks, its links both ways, its status changes ----------
function msrRecord(t, key) {
  const r = t.records[key];
  if (!r) { view.innerHTML = `${msrBack(t)}<div class="card pad small muted wrap">${esc(key || "")} is not in the stack's copy of ${esc(t.name)}.</div>`; return; }
  const miss = [...r.missing.fields.map((f) => `the field ${msrField(f)}`), ...r.missing.needs.map((m) => `a ${m.type_name} (${m.link_name})`),
    ...r.missing.links.map((l) => `a link "${t.links.find((x) => x.id === l)?.name || l}"`)];
  const linkRows = (xs, empty) => (xs.length ? `<div class="card list">${xs.map((x) => msrRow(t, x.key, ` · ${esc(x.name)}`)).join("")}</div>` : `<div class="small muted">${empty}</div>`);
  const gates = t.gates.filter((g) => g.type === r.type);
  view.innerHTML = `${msrBack(t)}<div class="hero"><div class="grow"><h1 class="wrap">${esc(key)} · ${esc(r.title)}</h1>
      <div class="row wrap gap-2 mt-2">${r.type_name ? `<span class="pill">${esc(r.type_name)}</span>` : `<span class="pill">no type</span>`}<span class="pill">${esc(r.status || "no status")}</span></div></div>
      ${t.browse ? `<a class="btn sm" target="_blank" rel="noopener" href="${esc(t.browse + encodeURIComponent(key))}">${ic.next}In the tracker</a>` : ""}</div>
    ${miss.length ? `<div class="banner">${ic.alert}<span class="grow wrap">It lacks ${esc(miss.join(", "))}.</span></div>` : r.type ? `<div class="small ok-t">It has every required field, work product and link.</div>` : ""}
    <div class="section"><div class="section-h"><h2>Fields</h2></div><div class="card list">${r.fields.map((f) => `<div><div class="grow"><div class="sub">${esc(msrField(f.name))}${f.required ? " · required" : ""}</div>
      <div class="wrap">${f.value ? esc(f.value) : `<span class="muted">empty</span>`}</div></div></div>`).join("")}</div></div>
    <div class="section"><div class="section-h"><h2>Links from it</h2></div>${linkRows(r.out, "None.")}</div>
    <div class="section"><div class="section-h"><h2>Links to it</h2></div>${linkRows(r.in, "None.")}</div>
    ${gates.length ? `<div class="section"><div class="section-h"><h2>Approvals</h2></div><div class="card list">${gates.map((g) => `<div><div class="grow"><div class="ttl wrap">To ${esc(g.to)}: only a tap by the role ${esc(g.role)}</div>
      <div class="sub wrap">${r.gates.filter((a) => a.to.toLowerCase() === g.to.toLowerCase()).map((a) => `approved by ${esc(a.person)} ${esc(dt(a.at))}`).join(" · ") || "not approved through the stack"}</div></div></div>`).join("")}</div></div>` : ""}
    <div class="section"><div class="section-h"><h2>Status</h2></div><div class="card list">
      <div><div class="grow"><div class="ttl">Created</div></div><span class="small muted">${esc(dt(r.created))}</span></div>
      ${r.history.map((h) => `<div><div class="grow"><div class="ttl wrap">${esc(h.to)}</div></div><span class="small muted">${esc(dt(h.at))}</span></div>`).join("")}</div></div>
    <div class="tiny faint section">As ${esc(t.name)} held it ${esc(when(t.synced))}.</div>`;
}
