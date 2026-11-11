// ---------- Needs you: the Asks (ASK-13 to ASK-16, docs/ASKS.md) ----------
// Every question for you is an Ask (ops/asks.py): its question, chips, a reply box in your own words (not at a gate),
// Dismiss and Later, and its source as a quiet link. An answer shows at once (optimistic): "Sending…", then "Answered"
// with a one-tap Undo while the stack holds it; the runner keeps it by its answer id, so a retry never answers twice.
// While the runner restarts an answer waits in its inbox ("Kept"), and while the app itself cannot be reached it waits
// on this device and is sent when the app is back. Asks of one kind fold into one card with one answer for all and
// each item's own chips. The policy page (#/policy) shows each kind's tier, the standing rules, what the stack did for
// you with its undo, and the stop switch, which Home shows too.
const ASK_LOCAL = new Map();          // ask id -> {state, label, words, answer_id, error, at}: what you did, before the runner says
const ASK_OUTBOX = "mc-ask-outbox";   // answers the app could not take yet, on this device (sent when it is back)
let askAlways = new Set();            // ask ids whose next chip also makes a standing rule ("Yes, and always for this kind")

const askNewId = () => (crypto?.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Array.from({ length: 32 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join(""));
const outboxRead = () => { try { return JSON.parse(localStorage.getItem(ASK_OUTBOX) || "[]"); } catch (_) { return []; } };
const outboxWrite = (xs) => { try { localStorage.setItem(ASK_OUTBOX, JSON.stringify(xs)); } catch (_) {} };

// every Ask that waits, in the queue's order: the runner's, and the three only the app sees (in S.decisions with a srv: key)
function askList() {
  const own = (S?.decisions || []).filter((d) => String(d.source_key || "").startsWith("srv:")).map((d) => ({
    id: d.ask, source_key: d.source_key, kind: d.cls, title: d.cls, question: d.what, why: d.why, status: "open", app_only: true,
    choices: (d.answers || []).map((x, i) => ({ id: `l${i}`, label: x.label, href: x.href })), href: d.href, unanswered: d.unanswered, rank: -1 }));
  const rank = (a) => (a.rank ?? 999);
  return [...own, ...(S?.asks || [])].sort((a, b) => rank(a) - rank(b) || (a.created || 0) - (b.created || 0));
}
// what waits, and what you answered that the stack still holds for its Undo ("Understood as …")
const askWaiting = () => askList().filter((a) => a.status === "open" || a.status === "escalated" || a.pending?.state === "held" || ASK_LOCAL.has(a.id));
const askKinds = () => Object.fromEntries((S?.ask_policy?.kinds || []).map((k) => [k.kind, k]));
const askQueued = (id) => (S?.asks_queued || []).find((q) => q.id === id) || outboxRead().find((q) => q.req.id === id);
const viewerHolds = (a) => !a.people || a.people.includes("owner") || a.people.includes(S?.viewer_login);

// what the card says about your answer, from what you did here and what the runner holds
function askState(a) {
  const loc = ASK_LOCAL.get(a.id), p = a.pending || {}, q = askQueued(a.id);
  if (loc?.state === "error") return { cls: "bad", text: `Couldn't send: ${loc.error}` };
  if (q?.req) return { cls: "warn", text: `Kept on this device: ${APPNAME()} can't be reached. It is sent when it's back.` };
  if (q || loc?.state === "kept") return { cls: "warn", text: "Kept: the stack is restarting or busy. It is sent once, when it's back." };
  if (p.state === "held") return { cls: "ok", text: `${a.answer?.interpreted_as ? `Understood as: ${a.answer.interpreted_as}` : `Answered: ${askLabel(a, a.answer?.outcome)}`}`, undo: p.answer_id, until: p.undo_until };
  if (p.state === "reading" || loc?.state === "reading") return { cls: "run", text: "Reading your answer…" };
  if (p.state === "asked_back") return { cls: "warn", back: p.ask_back, text: p.understood ? `Understood so far: ${p.understood}` : "" };
  if (p.state === "suggested" && p.suggest) return { cls: "warn", suggest: p.suggest, text: `Did you mean ${askLabel(a, p.suggest)}? A gate counts only a tap.` };
  if (p.state === "comment") return { cls: "", text: "Kept as a comment." };
  if (loc?.state === "sending") return { cls: "run", text: loc.label ? `Sending: ${loc.label}…` : "Sending…" };
  if (loc?.state === "done") return { cls: "ok", text: loc.label || "Done", undo: loc.answer_id };
  if (a.error) return { cls: "bad", text: a.error };
  return null;
}
const askLabel = (a, id) => (a.choices || []).find((c) => c.id === id)?.label || id || "";

function askChips(a, small = false) {
  const st = askState(a), p = a.pending || {};
  return (a.choices || []).map((c) => c.href
    ? `<a class="btn sm ghost" href="${esc(c.href)}">${esc(c.label)}</a>`
    : `<button type="button" class="btn sm${st?.suggest === c.id ? " primary" : ""}" data-achip="${esc(a.id)}" data-out="${esc(c.id)}"${c.words ? ` data-words="${esc(c.words)}"` : ""}${p.state === "held" ? " disabled" : ""}>${esc(c.label)}</button>`).join("") + (small ? "" : "");
}

// one Ask as a card: the question first, the facts and why on a tap, its chips, the reply box, Later and Dismiss
function askCard(a, compact = false) {
  const k = askKinds()[a.kind] || {}, st = askState(a), title = k.title || a.title || a.kind || "";
  const who = a.gate ? `a tap by ${a.role === "owner" ? "you" : a.role}` : "";
  const facts = (a.facts || []).map((f) => `<div><span class="muted">${esc(f.k)}:</span> ${esc(youText(f.v))}</div>`).join("");
  const rec = a.recommend ? `<div>The stack would say <b>${a.recommend.answer === "yes" ? "yes" : "no"}</b>${a.recommend.why ? `: ${esc(a.recommend.why)}` : ""}</div>` : "";
  const more = [a.why ? `<div>${prose(youText(a.why))}</div>` : "", facts, rec, a.unanswered ? `<div class="muted">Without an answer: ${esc(a.unanswered)}</div>` : "",
    a.default ? `<div class="muted">Without an answer by ${dt(a.deadline)}: ${esc(askLabel(a, a.default.outcome))}</div>` : "",
    (a.comments || []).map((c) => `<div class="muted">${esc(c.person)}: “${esc(c.words)}”</div>`).join("")].join("");
  const holds = viewerHolds(a) && (a.pending || {}).state !== "held";   // answered and held for its Undo: only Undo is left
  return `<div class="card pad acard${st?.cls === "ok" ? " adone" : ""}" data-ask="${esc(a.id)}">
    <div class="row between wrap" style="gap:6px"><span class="tiny faint">${esc(title)}${who ? ` · ${esc(who)}` : ""}${a.status === "escalated" ? " · escalated" : ""}</span>
      ${a.expires ? `<span class="tiny">answer by ${dt(a.expires)}</span>` : ""}</div>
    <div class="ttl wrap aq">${esc(youText(a.question))}</div>
    ${more ? explain(`ask-${a.id}`, more, "Why and the facts") : ""}
    ${!viewerHolds(a) ? `<div class="small muted">Only ${esc((a.people || []).join(", "))} can answer this (${esc(a.role)}).</div>` : ""}
    ${st?.back ? `<div class="small aback"><b>${esc(st.back)}</b></div>` : ""}
    ${holds ? `<div class="row wrap achips" style="gap:8px;margin-top:10px">${askChips(a)}</div>` : ""}
    ${holds && !a.app_only && (a.gate ? !compact : a.allow_words !== false) ? `<form class="areply row" data-areply="${esc(a.id)}"><input class="input" name="w" autocomplete="off" maxlength="4000" placeholder="${a.gate ? "Add a comment" : st?.back ? "Your answer" : "Or answer in your own words"}" aria-label="Your answer"><button class="btn sm" type="submit" aria-label="Send">${ic.send}</button></form>` : ""}
    ${st ? `<div class="small astate ${st.cls}" role="status">${esc(st.text)}${st.undo ? ` <button type="button" class="linkbtn" data-aundo="${esc(a.id)}" data-aid="${esc(st.undo)}">Undo</button>` : ""}</div>` : ""}
    ${holds ? `<div class="row wrap aquiet" style="gap:6px;margin-top:8px">
      <button type="button" class="btn sm ghost" data-alater="${esc(a.id)}">${ic.clock}Later</button>
      <button type="button" class="btn sm ghost" data-adismiss="${esc(a.id)}">${ic.x}Dismiss</button>
      ${!a.gate && !a.app_only && !compact ? `<button type="button" class="btn sm ghost${askAlways.has(a.id) ? " on" : ""}" data-aalways="${esc(a.id)}" aria-pressed="${askAlways.has(a.id)}">${ic.repeat}Always for this kind</button>` : ""}
      ${a.href && !compact ? `<a class="tiny faint asrc" href="${esc(a.href)}">Its page ${ic.next}</a>` : ""}</div>` : ""}
    <div class="alater" data-alaterbox="${esc(a.id)}" hidden><div class="row wrap" style="gap:6px;margin-top:8px">${["in 1 hour", "tonight", "tomorrow morning", "next week"].map((w) => `<button type="button" class="btn sm ghost" data-alaterw="${esc(a.id)}" data-w="${w}">${w[0].toUpperCase() + w.substring(1)}</button>`).join("")}</div></div>
  </div>`;
}

// many Asks of one kind: one card, one answer for all, and each item with its own chips (every row shows)
function askGroupCard(kind, items) {
  const k = askKinds()[kind] || {}, first = items[0];
  const common = (first.choices || []).filter((c) => !c.href && !c.words && items.every((a) => (a.choices || []).some((x) => x.id === c.id)));
  return `<div class="card pad acard agroup" data-agroup="${esc(kind)}">
    <div class="tiny faint">${esc(k.title || first.title || kind)} · ${items.length} waiting</div>
    ${common.length ? `<div class="row wrap" style="gap:8px;margin-top:8px">${common.map((c) => `<button type="button" class="btn sm" data-agall="${esc(kind)}" data-out="${esc(c.id)}">${esc(c.label)}: all ${items.length}</button>`).join("")}</div>` : ""}
    <div class="stack" style="margin-top:10px">${items.map((a) => askCard(a, true)).join("")}</div></div>`;
}

function askGroups(list) {
  const by = new Map(), out = [];
  for (const a of list) {
    if (!a.group || a.gate || a.app_only) { out.push({ one: a }); continue; }
    if (!by.has(a.kind)) { by.set(a.kind, []); out.push({ kind: a.kind, items: by.get(a.kind) }); }
    by.get(a.kind).push(a);
  }
  return out.map((g) => (g.items && g.items.length === 1 ? { one: g.items[0] } : g));
}

// ---------- sending: at once on the card, then the runner's word ----------
function askToast(text, undo) {
  let t = $("#atoast");
  if (!t) { t = document.createElement("div"); t.id = "atoast"; t.className = "toast atoast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
  t.innerHTML = `<span>${esc(text)}</span>${undo ? ` <button type="button" class="linkbtn" id="atoastundo">Undo</button>` : ""}`;
  t.classList.add("on");
  clearTimeout(askToast.t); askToast.t = setTimeout(() => t.classList.remove("on"), ((S?.ask_policy?.hold_s) || 15) * 1000);
  if (undo) $("#atoastundo").onclick = () => { t.classList.remove("on"); undo(); };
}

async function askPost(req) {
  try {
    return await api("/api/request", { method: "POST", body: JSON.stringify(req), timeout: 12000 });
  } catch (e) {                                        // the app cannot be reached: kept on this device, sent when it is back
    outboxWrite([...outboxRead().filter((x) => x.req.answer_id !== req.answer_id), { req, at: Date.now() }]);
    askFlushLater();
    return { kept: true, error: e.message };
  }
}

async function askSend(a, req, label) {
  const answer_id = askNewId(), full = { ...req, id: a.id, answer_id, ...(a.source_key ? { source_key: a.source_key } : {}) };
  ASK_LOCAL.set(a.id, { state: req.words && !req.outcome ? "reading" : "sending", label, answer_id, at: Date.now() });
  askRedraw(a.id);                                     // feedback at once, before the network
  const r = await askPost(full);
  const at = Date.now();
  if (r.kept || r.pending) { ASK_LOCAL.set(a.id, { state: "kept", label, answer_id, at }); askRedraw(a.id); return; }
  if (r.ok === false) { ASK_LOCAL.set(a.id, { state: "error", error: r.error || "refused", answer_id, at }); askRedraw(a.id); return; }
  if (r.reading || r.comment) { ASK_LOCAL.set(a.id, { state: r.comment ? "comment" : "reading", answer_id, at }); askRedraw(a.id); return; }
  const said = r.message || label;
  ASK_LOCAL.set(a.id, { state: "done", label: said, answer_id, at });
  askRedraw(a.id);
  if (req.action === "ask_answer") askToast(said, () => askUndo(a.id, answer_id));
  else askToast(said);
}

async function askUndo(id, answer_id) {
  const box = outboxRead();
  if (box.some((x) => x.req.answer_id === answer_id)) {           // never left this device: taken back here
    outboxWrite(box.filter((x) => x.req.answer_id !== answer_id)); ASK_LOCAL.delete(id); askRedraw(id); toast("Undone: it waits for your answer again"); return;
  }
  ASK_LOCAL.set(id, { state: "sending", label: "Undo", answer_id });
  askRedraw(id);
  const r = await askPost({ action: "ask_undo", id, answer_id });
  if (r.ok === false) { ASK_LOCAL.set(id, { state: "error", error: r.error, answer_id }); askRedraw(id); return; }
  ASK_LOCAL.delete(id);
  askRedraw(id);
  toast("Undone: it waits for your answer again");
}

function askFlushLater() {
  clearTimeout(askFlushLater.t);
  askFlushLater.t = setTimeout(async () => {
    for (const x of outboxRead()) {
      try {
        await api("/api/request", { method: "POST", body: JSON.stringify(x.req), timeout: 12000 });
        outboxWrite(outboxRead().filter((y) => y.req.answer_id !== x.req.answer_id));
      } catch (_) { askFlushLater(); return; }
    }
  }, 5000);
}

// a state from the runner replaces what this device said: an Ask the runner moved on from forgets its local word
function askSettle() {
  for (const [id, loc] of ASK_LOCAL) {
    const a = (S?.asks || []).find((x) => x.id === id), q = askQueued(id);
    if (q) continue;
    if (!a && loc.state !== "sending") ASK_LOCAL.delete(id);
    else if (a && a.pending && a.pending.answer_id === loc.answer_id && loc.state !== "error") ASK_LOCAL.delete(id);
    else if (a && loc.at && Date.now() - loc.at > 60000 && loc.state === "done") ASK_LOCAL.delete(id);   // a kept one stays until the runner takes it
  }
}

// you are typing in it: a box with focus inside this element (a tapped chip is no typing)
const typingIn = (el) => el.contains(document.activeElement) && ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName);

function askRedraw(id) {
  for (const el of $$(`[data-ask="${CSS.escape(id)}"]`)) {
    if (typingIn(el)) continue;
    const a = askList().find((x) => x.id === id);
    if (!a) { el.remove(); continue; }
    const tmp = document.createElement("div");
    tmp.innerHTML = askCard(a, !!el.closest(".agroup") || !!el.closest("#homeneeds"));
    el.replaceWith(tmp.firstElementChild);
  }
  bindAsks();
}

function bindAsks() {
  const find = (id) => askList().find((x) => x.id === id);
  $$("[data-achip]").forEach((b) => (b.onclick = () => {
    const a = find(b.dataset.achip);
    if (!a) return;
    if (b.dataset.words) {                              // this answer needs your words: the box asks for them
      const f = $(`[data-areply="${CSS.escape(a.id)}"]`);
      if (f) { f.dataset.out = b.dataset.out; f.w.placeholder = b.dataset.words; f.w.focus(); return; }
      const w = prompt(b.dataset.words, "");
      if (!w) return;
      return askSend(a, { action: "ask_answer", outcome: b.dataset.out, words: w }, b.textContent);
    }
    const always = askAlways.has(a.id);
    askAlways.delete(a.id);
    askSend(a, { action: "ask_answer", outcome: b.dataset.out, ...(always ? { always: true } : {}) }, `${b.textContent}${always ? ", and always for this kind" : ""}`);
  }));
  $$("[data-areply]").forEach((f) => (f.onsubmit = (e) => {
    e.preventDefault();
    const a = find(f.dataset.areply), w = f.w.value.trim();
    if (!a || !w) return;
    f.w.blur();                                        // sent: the card may show what happens to it
    askSend(a, { action: "ask_answer", words: w, ...(f.dataset.out ? { outcome: f.dataset.out } : {}) }, w);
  }));
  $$("[data-aundo]").forEach((b) => (b.onclick = () => askUndo(b.dataset.aundo, b.dataset.aid)));
  $$("[data-alater]").forEach((b) => (b.onclick = () => { const box = $(`[data-alaterbox="${CSS.escape(b.dataset.alater)}"]`); if (box) box.hidden = !box.hidden; }));
  $$("[data-alaterw]").forEach((b) => (b.onclick = () => { const a = find(b.dataset.alaterw); if (a) askSend(a, { action: "ask_later", words: b.dataset.w }, `Later: ${b.dataset.w}`); }));
  $$("[data-adismiss]").forEach((b) => (b.onclick = () => {
    const a = find(b.dataset.adismiss), f = a && $(`[data-areply="${CSS.escape(a.id)}"]`);
    if (a) askSend(a, { action: "ask_dismiss", words: f?.w.value.trim() || "" }, "Dismissed");
  }));
  $$("[data-aalways]").forEach((b) => (b.onclick = () => {
    const id = b.dataset.aalways;
    askAlways.has(id) ? askAlways.delete(id) : askAlways.add(id);
    b.classList.toggle("on", askAlways.has(id)); b.setAttribute("aria-pressed", askAlways.has(id));
  }));
  $$("[data-agall]").forEach((b) => (b.onclick = async () => {
    const kind = b.dataset.agall, items = askWaiting().filter((a) => a.kind === kind && !a.gate);
    items.forEach((a) => ASK_LOCAL.set(a.id, { state: "sending", label: b.textContent }));
    items.forEach((a) => askRedraw(a.id));
    const r = await askPost({ action: "ask_group", kind, outcome: b.dataset.out, ids: items.map((a) => a.id), answer_id: askNewId() });
    items.forEach((a) => ASK_LOCAL.set(a.id, r.ok === false ? { state: "error", error: r.error } : { state: r.kept || r.pending ? "kept" : "done", label: b.textContent }));
    items.forEach((a) => askRedraw(a.id));
    if (r.message) askToast(r.message);
  }));
  $$("[data-astop]").forEach((b) => (b.onclick = () => {
    const on = b.dataset.astop === "on";
    if (on && !confirm("Stop every agent and workflow? What runs now finishes; nothing new starts until you resume.")) return;
    act({ action: "ask_stop", on }, on ? "Stopped: nothing new starts until you resume" : "Resumed: agents and workflows go on");
  }));
}

// ---------- the stop switch (Home and the policy page) ----------
function stopHtml(full = false) {
  const s = S?.ask_policy?.stop || {};
  if (s.on) {
    const held = Object.entries(s.paused || {}).filter(([, v]) => v != null && v !== 0).map(([k, v]) => `${k}: ${typeof v === "number" ? nf(v) : v}`).join(" · ");
    return `<div id="askstop" class="banner warn astop">${ic.stop}<span class="grow"><b>Everything is stopped</b> since ${dt(s.at)}${held ? `. Held: ${esc(held)}` : ""}.</span><button type="button" class="btn sm primary" data-astop="off">${ic.play}Resume</button></div>`;
  }
  return full ? `<div id="askstop" class="row between wrap astop-off"><span class="small muted">Agents and workflows run.</span><button type="button" class="btn sm ghost" data-astop="on">${ic.stop}Stop everything</button></div>`
    : `<div id="askstop" class="row astop-off" style="justify-content:flex-end"><button type="button" class="btn sm ghost" data-astop="on" title="Stop every agent, workflow and crew job">${ic.stop}Stop everything</button></div>`;
}

// ---------- Home: what needs you, answered in place ----------
function askNeedsHtml() {
  const list = askWaiting();
  if (!list.length) return `<div id="homeneeds" class="needs-calm">${ic.check}<span>Nothing needs you right now.</span></div>`;
  const mine = list.filter((a) => !IDEA_CLS.has(a.cls || a.kind));
  return `<div id="homeneeds"><div class="section-h"><h2>Needs you <span class="hcount">${mine.length}</span></h2><a class="tiny" href="#/decide">All</a></div>
    <div class="stack">${askGroups(list).map((g) => g.one ? askCard(g.one, true) : askGroupCard(g.kind, g.items)).join("")}</div></div>`;
}

// ---------- #/decide: every Ask in full ----------
function vDecide() {
  askSettle();
  const list = askWaiting(), st = S.decide || {}, tg = st.target || {}, later = (S.asks || []).filter((a) => a.status === "snoozed");
  const focus = route.q.get("a");
  const page = `<div id="askspage"><div class="hero heading row between wrap"><h1>Needs you <span class="hcount">${nf(list.length)}</span></h1><a class="small" href="#/policy">What the stack may do ${ic.next}</a></div>
  ${explain("asks-numbers", `${st.per_day ?? "–"} a day (target at most ${tg.per_day ?? 5}) · answered in ${st.median_h != null ? `${st.median_h} h` : "–"} at the median (target ${tg.answer_h ?? 12} h) · ${nf(st.expired || 0)} expired, over ${st.days ?? 0} day${st.days === 1 ? "" : "s"}. Answer with a chip or in your own words; Later puts a question off, Dismiss lets it go. A gate counts only a tap by a person in its role.`, "About Needs you")}
  ${stopHtml().includes("Everything is stopped") ? stopHtml() : ""}
  ${list.length ? `<div class="stack" style="margin-top:12px">${askGroups(list).map((g) => g.one ? askCard(g.one) : askGroupCard(g.kind, g.items)).join("")}</div>`
    : `<div class="needs-calm" style="margin-top:12px">${ic.check}<span>Nothing needs you right now.</span></div>`}
  ${later.length ? `<div class="section-h" style="margin-top:18px"><h2>Put off <span class="hcount">${later.length}</span></h2></div><div class="card list">${later.map((a) => `<div class="row between wrap" style="gap:8px"><span class="small wrap grow">${esc(a.question)}</span><span class="tiny muted">until ${dt(a.wake)}</span></div>`).join("")}</div>` : ""}</div>`;
  const cur = $("#askspage");
  if (cur && typingIn(cur)) {        // you are typing: only the cards you are not in are redrawn
    for (const a of list) askRedraw(a.id);
    return;
  }
  view.innerHTML = page;
  bindAsks();
  if (focus) $(`[data-ask="${CSS.escape(focus)}"]`)?.scrollIntoView({ block: "center" });
}

// ---------- #/policy: what the stack may do ----------
const TIER_WORDS = { do: ["ok", "Does it"], tell: ["ok", "Does it, then tells you"], ask: ["warn", "Asks you first"], never: ["err", "Never"] };
function vPolicy() {
  const P = S.ask_policy || {}, kinds = P.kinds || [], rules = P.rules || [], undo = (P.undo || []).filter((u) => u.state === "open");
  const kindTitle = (k) => (kinds.find((x) => x.kind === k) || {}).title || k;
  const outcomeWord = (r) => ((kinds.find((x) => x.kind === r.kind) || {}).outcomes || []).find((o) => o.id === r.outcome)?.label
    || ((S.asks || []).flatMap((a) => (a.kind === r.kind ? a.choices || [] : [])).find((c) => c.id === r.outcome) || {}).label || r.outcome.replace(/-/g, " ");
  view.innerHTML = `<div class="hero heading"><h1>What the stack may do</h1></div>
  ${explain("policy-what", "Each kind of action has a tier: it does it, does it and tells you, asks you first, or never does it. Your standing rules change that for a kind (\"Yes, and always for this kind\" on a question makes one). A gate always asks and only a tap by a person in its role answers it: no rule, default or reading of your words does. What the stack did on its own can be undone here while its window is open.", "About this page")}
  <div class="section-h" style="margin-top:12px"><h2>Stop switch</h2></div><div class="card pad">${stopHtml(true)}</div>
  <div class="section-h" style="margin-top:18px"><h2>Your standing rules <span class="hcount">${rules.length}</span></h2></div>
  <div class="card list">${rules.length ? rules.map((r) => `<div class="row between wrap" style="gap:8px"><div class="grow" style="min-width:0"><div class="small wrap"><b>${esc(kindTitle(r.kind))}</b>: ${r.effect === "allow" ? "always" : "never asked, always"} “${esc(outcomeWord(r))}”${r.under ? ` while ${esc(r.under.fact)} is at most ${nf(r.under.max, 1)}` : ""}</div><div class="tiny muted wrap">${esc(r.by || "")}, ${dt(r.at)}${r.note ? ` · ${esc(r.note)}` : ""}</div></div><button type="button" class="btn sm ghost" data-rdel="${esc(r.id)}">Remove</button></div>`).join("")
    : emptyState("No standing rules yet: an answer with “Always for this kind” makes one.", `<a class="btn sm" href="#/decide">Open Needs you</a>`)}</div>
  ${undo.length ? `<div class="section-h" style="margin-top:18px"><h2>Done for you <span class="hcount">${undo.length}</span></h2></div><div class="card list">${undo.map((u) => `<div class="row between wrap" style="gap:8px"><div class="grow" style="min-width:0"><div class="small wrap">${esc(u.what)}</div><div class="tiny muted">${esc(u.by)} · ${dt(u.at)} · undo until ${dt(u.until)}</div></div><button type="button" class="btn sm ghost" data-uundo="${esc(u.id)}">Undo</button></div>`).join("")}</div>` : ""}
  <div class="section-h" style="margin-top:18px"><h2>Each kind of question</h2></div>
  <div class="card list">${kinds.map((k) => { const [c, w] = TIER_WORDS[k.tier] || ["", k.tier]; const r = rules.filter((x) => x.kind === k.kind).length;
    return `<div class="row between wrap" style="gap:8px"><span class="small wrap grow">${esc(k.title)}${k.role && k.role !== "owner" ? ` <span class="tiny muted">· ${esc(k.role)}</span>` : ""}</span><span class="row" style="gap:6px">${k.gate ? `<span class="pill err">Gate: a tap only</span>` : `<span class="pill ${c}">${esc(w)}</span>`}${r ? `<span class="pill ok">${r} rule${r > 1 ? "s" : ""}</span>` : ""}</span></div>`; }).join("")}</div>`;
  bindAsks();
  $$("[data-rdel]").forEach((b) => (b.onclick = () => act({ action: "ask_rule_delete", rule_id: b.dataset.rdel }, "Rule removed: that kind asks you again")));
  $$("[data-uundo]").forEach((b) => (b.onclick = () => act({ action: "ask_undo_action", undo_id: b.dataset.uundo }, "Undone: the stack took it back")));
}
