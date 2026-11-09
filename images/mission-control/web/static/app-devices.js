// The app, part of app-base.js, app-tasks.js, app-runs.js, app-devices.js, app-wiki-code.js, app-memory.js, app.js (PLT-25): the AI phone, the House and what the phone shared. Loaded in that order; one global scope.
// ---------- the AI phone (images/phone): approvals, Stop, pairing, log ----------
let phoneTimer = null;
const PHONE_NOT_TAKEN = "The AI phone did not pick this up (its service may be restarting). It asks again if still needed.";
async function vPhone() {
  clearInterval(phoneTimer);
  const pre = route.q.get("do"), pid = route.q.get("id");             // a button in the Telegram message
  if (pre && pid) {
    history.replaceState(history.state, "", "#/phone");
    const r = await api("/api/phone/decide", { method: "POST", body: JSON.stringify({ id: pid, allow: pre !== "deny", minutes: pre === "allow5" ? 5 : 0 }) })
      .catch((e) => ({ error: e.message }));
    toast(r.error ? `Too late: ${r.error}` : !r.taken ? PHONE_NOT_TAKEN : pre === "deny" ? "Declined" : pre === "allow5" ? "Allowed, and for the next 5 minutes" : "Allowed: the AI phone is doing it", !!r.error || !r.taken);
    if (route.name !== "phone") return;
  }
  view.innerHTML = `<div class="hero"><div class="grow"><h1>AI phone</h1></div>${liveLink("phone", "What it did")}</div><div id="ph"></div>`;
  let last = "";
  const draw = async () => {
    if (route.name !== "phone") return clearInterval(phoneTimer);
    const P = await api("/api/phone").catch(() => null);
    if (route.name !== "phone") return clearInterval(phoneTimer);
    const sig = JSON.stringify([P?.state?.connected, P?.state?.foreground, P?.state?.error, P?.stopped, P?.pending?.map((p) => p.id), P?.log?.[0]?.ts, P?.state?.trust_until > Date.now() / 1000, P?.state?.screen_held, Math.round((P?.state?.screen_until || 0) / 30), P?.state?.task?.until, P?.state?.task?.actions]);
    if (sig === last || typing()) return;
    last = sig;
    $("#ph").innerHTML = phoneHtml(P);
    bindPhone(P);
  };
  await draw();
  phoneTimer = setInterval(draw, 2000);
  document.onvisibilitychange = () => { if (!document.hidden && route.name === "phone") draw(); };   // a background tab is paused
}

function phoneHtml(P) {
  if (!P?.installed) return `<div class="card pad-l empty">The AI phone service is not running.</div>`;
  const st = P.state, trust = st.trust_until > Date.now() / 1000, forever = st.trust_until > Date.now() / 1000 + 365 * 86400;
  const status = P.stopped ? `<span class="pill failed">Stopped</span>` : st.connected ? `<span class="pill ok">Connected</span>` : `<span class="pill paused">Not connected</span>`;
  return `<div class="stack">
    ${!P.push_devices ? `<a class="banner" href="#/system">${ic.bell}<span class="grow">No device gets notifications, so approval requests only reach you on Telegram. Switch notifications on under <b>This device</b>.</span>${ic.next}</a>` : ""}
    <div class="card pad-l"><div class="row between wrap" style="gap:10px;align-items:center">
      <div><div class="row" style="gap:8px;align-items:center">${status}<b>${esc(st.model || "Phone")}</b>${st.android ? `<span class="small muted">Android ${esc(st.android)}</span>` : ""}</div>
        <div class="small muted" style="margin-top:4px">${st.connected ? `In front: <span class="mono">${esc(st.foreground || "home screen")}</span>` : esc(st.error || "")}${forever ? " · <b>actions allowed until you stop it</b>" : trust ? ` · <b>actions allowed until ${dt(st.trust_until)}</b>` : ""}</div></div>
      ${P.stopped ? `<button class="btn primary" id="phresume">${ic.play}Switch on</button>` : `<button class="btn danger" id="phstop">${ic.pause}Stop</button>`}
    </div>${st.connected && !P.stopped ? phoneScreenHtml(st) : ""}${trust ? `<button class="btn sm ghost" id="phuntrust" style="margin-top:10px">Ask me for each job instead</button>`
      : st.connected && !P.stopped ? `<div class="row wrap" style="gap:8px;margin-top:10px;align-items:center"><span class="small"><b>Let it use the phone freely:</b></span>
        ${[[10, "10 min"], [60, "1 hour"], [480, "8 hours"], [-1, "Until I stop it"]].map(([m, l]) => `<button class="btn sm" data-trust="${m}">${l}</button>`).join("")}
        <input class="input" id="phmin" inputmode="numeric" placeholder="min" style="width:70px;padding:6px 8px"><button class="btn sm ghost" id="phcustom">Set</button></div>
        ${explain("freely-taps-swipes-openi", `Freely: taps, swipes, opening apps and typing run without asking. Still asking: spending money, and typing or a web address that holds an e-mail address, phone number, IBAN or key. Passwords are never typed, blocked apps stay blocked, Stop ends it.`, "What still asks")}` : ""}</div>
    ${phoneTaskHtml(st)}
    ${P.pending.map((p) => `<div class="card pad-l phreq${p.money ? " money" : ""}">
      <div class="tag">Waiting for your OK · ${esc(p.app || "")}</div><h2 style="margin:8px 0 4px">${esc(p.text)}</h2><div class="small">${esc(p.why || "")}</div>
      <div class="row wrap" style="gap:8px;margin-top:14px"><button class="btn primary" data-allow="${p.id}">${ic.check}${p.tool === "phone_task" ? "Allow this job" : "Allow"}</button><button class="btn ghost" data-deny="${p.id}">${ic.x}Decline</button></div>
      ${p.shot ? `<img class="phshot" src="/api/phone/shot/${p.shot}" alt="The phone's screen now; a red circle marks a planned tap">` : ""}
    </div>`).join("")}
    ${!st.connected && !P.stopped ? `<div class="card pad-l"><h2>${st.paired ? "Reconnect" : "Pair the phone"}</h2>
      ${st.paired ? `<div class="small muted" style="margin-top:6px">Paired before. Make sure Wireless debugging is on, then:</div><button class="btn primary" id="phconnect" style="margin-top:10px">Connect</button>` : ""}
      <ol class="small" style="margin:10px 0 0 18px;line-height:1.6"><li>On the old phone: Settings → Developer options → <b>Wireless debugging</b> → <b>Pair device with pairing code</b>.</li>
        <li>Enter the 6-digit code and the port (the digits after the colon in “IP address &amp; Port” of that dialog).</li></ol>
      <form id="phpair" class="row wrap" style="gap:8px;margin-top:10px"><input class="input" name="code" inputmode="numeric" maxlength="6" placeholder="Code (6 digits)" style="width:150px"><input class="input" name="port" inputmode="numeric" maxlength="5" placeholder="Port" style="width:110px"><button class="btn primary">Pair</button></form></div>` : ""}
    ${st.connected && st.boot ? `<div class="card pad-l"><div class="row between wrap" style="gap:8px;align-items:center"><h2>Starts in AI mode after a restart</h2>
      ${Object.values(st.boot).every(Boolean) ? `<span class="pill ok">Ready</span>` : `<button class="btn sm primary" id="phboot">Set it up</button>`}</div>
      <ul class="phlog" style="margin-top:8px">${[["keepadb_allowed", "Wireless debugging switches itself on (KeepADB)"], ["keeps_pairing", "The pairing does not lapse (Android's 7-day limit is off)"], ["tailscale_always_on", "Tailscale connects by itself (always-on VPN)"],
        ["no_battery_limit", "Android never stops Tailscale or KeepADB (no battery limit)"]].map(([k, l]) => `<li>${st.boot[k] ? "✓" : "○"} ${esc(l)}</li>`).join("")}</ul>
      ${Object.values(st.boot).every(Boolean) ? "" : `<div class="tiny muted" style="margin-top:6px">Each change asks for your Allow (here and on Telegram) before it runs.</div>`}</div>` : ""}
    <div class="card pad-l"><h2>What it did</h2>${P.log.length ? `<ul class="phlog">${P.log.map((e) => `<li><span class="tiny faint">${e.ts ? clock(e.ts) : ""}</span> <b>${esc(e.tool)}</b> ${esc(e.decision || e.result || "")}${e.why ? `<div class="tiny muted">${esc(e.why)}</div>` : ""}</li>`).join("")}</ul>` : `<div class="small muted" style="margin-top:6px">Nothing yet. Ask Hermes in chat, e.g. “On the AI phone, open Chrome and look up the weather”.</div>`}</div>
    <details class="card pad-l"><summary><b>Never touched</b> <span class="small muted">· ${P.blocklist.length} apps and words</span></summary><div class="small muted" style="margin-top:8px">Banking, investment, payment, password and settings apps: the AI phone never reads or touches them; if one comes up it goes to the home screen. Edit <span class="mono">/srv/ai/phone/blocklist.txt</span>.</div><div class="row wrap" style="gap:6px;margin-top:8px">${P.blocklist.map((b) => `<span class="tag">${esc(b)}</span>`).join("")}</div></details>
  </div>`;
}

// PHN-18: a task the owner allowed once: its apps, the texts it may type, until when, how many actions so far
function phoneTaskHtml(st) {
  const t = st.task;
  if (!t || t.until < Date.now() / 1000) return "";
  return `<div class="card pad-l"><div class="row between wrap" style="gap:4px 8px;align-items:center"><h2>Task allowed once</h2><button class="btn sm ghost" id="phendtask">End task</button></div>
    <div class="small" style="margin-top:6px"><b>${esc(t.task)}</b></div>
    <div class="small muted" style="margin-top:4px">In ${esc((t.apps || []).join(", "))} · types ${t.texts?.length ? esc(t.texts.join("; ")) : "nothing"} · until ${clock(t.until)} · ${nf(t.actions || 0)} action${t.actions === 1 ? "" : "s"} so far without asking</div></div>`;
}

// PHN-17: the screen is on while the agents work (and while an action waits for you), off when idle; watch on demand
function phoneScreenHtml(st) {
  const on = st.screen_held && st.screen_until > Date.now() / 1000;
  return `<div class="row wrap" style="gap:8px;margin-top:10px;align-items:center"><span class="small"><b>Screen:</b> ${on ? `on until ${clock(st.screen_until)} · ${esc(st.screen_why || "")}` : "off when idle (saves the battery)"}</span>
    <button class="btn sm" data-phscreen="10">${on ? "Keep on 10 min" : "Watch 10 min"}</button>${on ? `<button class="btn sm ghost" data-phscreen="0">Turn off now</button>` : ""}</div>`;
}

function bindPhone(P) {
  const ctl = async (body) => { const r = await api("/api/phone/control", { method: "POST", body: JSON.stringify(body) }).catch((e) => ({ error: e.message })); if (r.error) toast(r.error, true); return r; };
  // the tap shows at once on the card; it stays as "doing it" until the phone is done and the card goes away
  const decide = async (id, allow, minutes, btn) => {
    const row = btn.parentElement;
    row.innerHTML = `<span class="small"><span class="spin" style="width:12px;height:12px;vertical-align:-1px"></span> ${allow ? "Allowed. The AI phone is doing it…" : "Declining…"}</span>`;
    const r = await api("/api/phone/decide", { method: "POST", body: JSON.stringify({ id, allow, minutes }) }).catch((e) => ({ error: e.message }));
    if (r.error || !r.taken) row.innerHTML = `<span class="small err-t">${esc(r.error || PHONE_NOT_TAKEN)}</span>`;
    toast(r.error || (!r.taken ? PHONE_NOT_TAKEN : allow ? "Allowed: the AI phone is doing it" : "Declined"), !!r.error || !r.taken);
  };
  $("#phstop") && ($("#phstop").onclick = () => ctl({ do: "stop" }).then(() => toast("AI phone stopped")));
  $("#phresume") && ($("#phresume").onclick = () => ctl({ do: "resume" }).then(() => ctl({ do: "connect" })));
  $("#phconnect") && ($("#phconnect").onclick = (e) => { e.target.disabled = true; ctl({ do: "connect" }).then(() => toast("Connecting…")); });
  $("#phboot") && ($("#phboot").onclick = (e) => { e.target.disabled = true; ctl({ do: "boot_setup" }).then((r) => r.ok && toast("Asking for your OK on each setting…")); });
  $("#phuntrust") && ($("#phuntrust").onclick = () => ctl({ do: "trust", minutes: 0 }));
  $("#phendtask") && ($("#phendtask").onclick = () => ctl({ do: "end_task" }).then((r) => r.ok && toast("Task ended: every action asks again")));
  $$("[data-phscreen]").forEach((b) => (b.onclick = () => ctl({ do: "screen", minutes: +b.dataset.phscreen }).then((r) => r.ok && toast(+b.dataset.phscreen ? "The screen stays on for 10 minutes" : "The screen turns off"))));
  const trustFor = (m) => ctl({ do: "trust", minutes: m }).then((r) => r.ok && toast(m < 0 ? "Allowed until you stop it" : `Allowed for ${m} minutes`));
  $$("[data-trust]").forEach((b) => (b.onclick = () => trustFor(+b.dataset.trust)));
  $("#phcustom") && ($("#phcustom").onclick = () => { const m = parseInt($("#phmin").value, 10); if (m > 0) trustFor(m); else toast("Minutes, e.g. 30", true); });
  $$("[data-allow]").forEach((b) => (b.onclick = () => decide(b.dataset.allow, true, 0, b)));
  $$("[data-allow5]").forEach((b) => (b.onclick = () => decide(b.dataset.allow5, true, 5, b)));
  $$("[data-deny]").forEach((b) => (b.onclick = () => decide(b.dataset.deny, false, 0, b)));
  const f = $("#phpair");
  if (f) f.onsubmit = async (e) => { e.preventDefault(); const r = await ctl({ do: "pair", code: f.code.value.trim(), port: f.port.value.trim() }); if (r.ok) { toast("Pairing… this takes a few seconds"); f.code.value = ""; f.port.value = ""; } };
}

// ---------- House: Home Assistant on the NAS (ops/house.py): setup, rooms, Echos, the voice bridge ----------
function houseSteps(h) {
  const has = (d) => (h.integrations || []).some((x) => x.domain === d);
  const ha = h.url || DEPLOY.HA_URL;
  return [
    { done: h.reachable, title: "Home Assistant runs on the NAS", sub: h.reachable ? ha : "not reachable from the PC: is the NAS on?" },
    { done: h.onboarded, title: "Create your Home Assistant account", sub: "once, on your home Wi-Fi: name, user, password, your location",
      btn: !h.onboarded && h.reachable ? `<a class="btn sm primary" href="${esc(ha)}" target="_blank" rel="noopener">Open Home Assistant</a>` : "" },
    { done: h.connected, title: "Connect it to the AI stack", sub: h.connected ? "the stack holds its own token (encrypted)" : "sign in to Home Assistant once more; it sends you back here",
      btn: h.onboarded && !h.connected ? `<a class="btn sm primary" href="/api/house/connect">Connect</a>` : "" },
    { done: has("alexa_devices"), title: "Sign in to Amazon (Alexa)", sub: has("alexa_devices") ? `${(h.echos || []).length} Echo${(h.echos || []).length === 1 ? "" : "s"} found` : "Amazon e-mail, password and the code from your authenticator app",
      btn: h.connected && !has("alexa_devices") ? `<a class="btn sm primary" href="${esc(ha)}/config/integrations/dashboard/add?domain=alexa_devices" target="_blank" rel="noopener">Add Alexa</a>` : "" },
    { done: has("tplink"), optional: true, title: "Tapo plugs (optional)", sub: has("tplink") ? "connected" : "Home Assistant usually finds them by itself; then sign in with your TP-Link account",
      btn: h.connected && !has("tplink") ? `<a class="btn sm" href="${esc(ha)}/config/integrations/dashboard/add?domain=tplink" target="_blank" rel="noopener">Add Tapo</a>` : "" },
  ];
}

// VOI-08: Hermes on the AI phone, as steps that tick themselves where the stack can see them (in Home Assistant)
const PLAY_HA = "https://play.google.com/store/apps/details?id=io.homeassistant.companion.android";
function phoneVoiceSteps(h, ha) {
  const link = (name, label) => { const m = ha?.menus.find((x) => x.name === name); return m ? `<a class="btn sm primary" href="${esc(toolUrl(ha, m))}" target="_blank" rel="noopener">${label}</a>` : ""; };
  const person = (h.people || []).find((n) => /ai.?phone/i.test(n)), app = (h.integrations || []).filter((x) => x.domain === "mobile_app");
  return [
    { done: (h.pipelines || []).includes("Hermes"), title: "Hermes' voice in Home Assistant", sub: "speech to text, Hermes and an English voice, set up by the stack" },
    { done: !!person, title: "Add a person “AI phone” in Home Assistant", sub: person ? `“${person}” can log in` : "Add person → name “AI phone” → switch on “Allow login” → a username and a password you choose → leave “Administrator” off → Create",
      btn: person ? "" : link("People", "Open People") },
    { done: app.length > 0, title: "Install the Home Assistant app on the AI phone", sub: app.length ? `signed in: ${app.map((x) => x.title).join(", ")}` : "On the S22: Install, open it, it finds Home Assistant on your Wi-Fi, sign in as “AI phone”",
      btn: app.length ? "" : `<a class="btn sm primary" href="${PLAY_HA}" target="_blank" rel="noopener">Open in Play Store</a>` },
    { done: !!(S.phone?.voice?.assistant && S.phone?.voice?.mic && S.phone?.voice?.awake), title: "Make it the phone's voice assistant",
      sub: S.phone?.voice?.assistant && S.phone?.voice?.mic && S.phone?.voice?.awake ? "the default assistant, with the microphone, listening also when locked"
        : "the stack sets it after your one Allow: the default assistant instead of Google's, the microphone, and no battery limit so it hears you when locked",
      btn: S.phone?.voice?.assistant && S.phone?.voice?.mic && S.phone?.voice?.awake ? "" : `<button class="btn sm primary" data-phvoice>Set it up</button>` },
    { manual: true, title: "Wake word on in the app", sub: "Hermes switches it on in Home Assistant's Assist settings (“Okay Nabu”)" },
    { manual: true, title: "Say “Okay Nabu”, then ask Hermes anything", sub: "the answer comes from the phone in English; the conversation is the Voice chat",
      btn: `<a class="btn sm" href="#/chat?c=voicechat">Open the Voice chat</a>` },
  ];
}

function phoneVoiceHtml(h, ha) {
  const steps = phoneVoiceSteps(h, ha), left = steps.filter((s) => !s.done && !s.manual).length;
  return `<div class="card pad-l"><div class="row between wrap" style="gap:4px 8px;align-items:center"><h2>Talk to Hermes on the AI phone</h2><span class="tiny faint">${left ? `${left} step${left > 1 ? "s" : ""} for you` : "ready to try"}</span></div>
    <ol class="hsteps">${steps.map((s) => `<li class="${s.done ? "done" : ""}"><span class="hs-ic">${s.done ? ic.check : s.manual ? "·" : ""}</span><div class="grow"><div class="ttl">${esc(s.title)}</div><div class="sub">${esc(s.sub)}</div></div>${s.btn || ""}</li>`).join("")}</ol>
    ${explain("you-type-the-password-yo", `You type the password yourself; the agents never open the Home Assistant app on the AI phone (its login reaches the house, the router and the NAS).`, "About this")}</div>`;
}

function houseThingHtml(t) {
  const on = t.state === "on" || t.state === "open";
  const ctl = t.domain === "cover"
    ? `<button class="btn sm" data-hs="${esc(t.entity_id)}" data-op="open">Up</button><button class="btn sm" data-hs="${esc(t.entity_id)}" data-op="stop">Stop</button><button class="btn sm" data-hs="${esc(t.entity_id)}" data-op="close">Down</button>`
    : `<button class="btn sm ${on ? "primary" : ""}" data-hs="${esc(t.entity_id)}" data-op="${on ? "off" : "on"}"${t.state === "unavailable" ? " disabled" : ""}>${on ? "On" : "Off"}</button>`;
  const extra = [t.brightness != null && on ? `${t.brightness} %` : "", t.position != null ? `position ${t.position}` : "", t.power_w != null ? `${t.power_w} W` : "",
    t.state === "unavailable" ? "unavailable" : "", t.protected ? "protected: agents never switch it" : ""].filter(Boolean).join(" · ");
  return `<div class="hrow"><div class="grow" style="min-width:0"><div class="ttl wrap">${esc(t.name)}</div><div class="sub wrap">${esc(extra || t.domain)}</div></div><div class="row" style="gap:6px">${ctl}</div></div>`;
}

function houseHtml(h) {
  if (!h) return `<div class="card pad-l empty">The runner has not reported the House yet.</div>`;
  const steps = houseSteps(h), open = steps.filter((s) => !s.done && !s.optional);
  const rooms = {};
  for (const t of h.things || []) (rooms[t.area || "No room yet"] ||= []).push(t);
  const echos = h.echos || [], ha = toolOf("homeassistant");
  return `<div class="stack">
    ${h.error ? `<div class="banner warn">${ic.alert}<span class="small">${esc(h.error)}</span></div>` : ""}
    ${ha && h.reachable ? `<div class="card pad-l"><div class="row between wrap" style="gap:4px 8px;align-items:baseline"><h2>Home Assistant</h2><span class="tiny faint">home Wi-Fi · opens in a new tab</span></div>
      <div class="chips" style="margin-top:8px">${toolLinks(ha)}</div></div>` : ""}
    ${h.connected ? phoneVoiceHtml(h, ha) : ""}
    <div class="card pad-l"><div class="row between" style="align-items:center"><h2>${open.length ? "Set up" : "Set up · done"}</h2>${open.length ? `<span class="tiny faint">${steps.filter((s) => s.done).length} of ${steps.length}</span>` : ""}</div>
      <ol class="hsteps">${steps.map((s) => `<li class="${s.done ? "done" : ""}"><span class="hs-ic">${s.done ? ic.check : ""}</span><div class="grow"><div class="ttl">${esc(s.title)}</div><div class="sub">${esc(s.sub)}</div></div>${s.btn || ""}</li>`).join("")}</ol>
      ${!h.onboarded || !h.connected ? `<div class="tiny muted" style="margin-top:8px">Home Assistant is reached on your home Wi-Fi only (nothing is open to the internet). You type every password into Home Assistant yourself; the stack never sees one.</div>` : ""}</div>
    ${h.connected ? `<div class="card pad-l"><h2>Tell Alexa</h2><div class="small muted" style="margin-top:4px">For the lights and devices that live in the Alexa app: the command runs as if you said it to an Echo.</div>
      <form id="halexa" class="row wrap" style="gap:8px;margin-top:10px"><input class="input grow" name="cmd" placeholder="e.g. schalte das Licht im Wohnzimmer aus" style="min-width:200px">
        ${echos.length > 1 ? `<select class="input" name="echo" style="width:auto">${echos.map((e) => `<option value="${esc(e.id)}">${esc(e.name)}</option>`).join("")}</select>` : ""}
        <button class="btn primary"${echos.length ? "" : " disabled"}>${ic.send}Send</button></form>
      <div class="suggest" style="margin-top:10px">${["Alle Lichter aus", "Licht im Wohnzimmer an", "Gute Nacht"].map((x) => `<button class="btn sm" data-hcmd="${esc(x)}"${echos.length ? "" : " disabled"}>${esc(x)}</button>`).join("")}</div></div>` : ""}
    ${Object.keys(rooms).length ? Object.entries(rooms).map(([room, ts]) => `<div class="card pad-l"><h2>${esc(room)}</h2><div class="hlist">${ts.map(houseThingHtml).join("")}</div></div>`).join("")
      : h.connected ? `<div class="card pad-l small muted">No lights, plugs or shutters in Home Assistant yet. The ones in the Alexa app work through <b>Tell Alexa</b>; Tapo plugs show up here once they are added.</div>` : ""}
    ${h.connected ? `<div class="card pad-l"><div class="row between wrap" style="gap:8px;align-items:center"><h2>Talk to Hermes through an Echo</h2>
        <label class="row" style="gap:6px;align-items:center"><input type="checkbox" id="hvoice"${h.voice ? " checked" : ""}><span class="small">${h.voice ? "On" : "Off"}</span></label></div>
      <div class="small" style="margin-top:6px">Say <b>“Alexa, Hermes, …”</b> or <b>“Alexa, frag Hermes …”</b>. Alexa may first say it can't help (it doesn't know Hermes); then the same Echo speaks Hermes' answer, usually within 5-20 seconds. Only requests that start with “Hermes” are passed on; nothing else you say to Alexa is kept.</div>
      ${echos.length ? `<div class="hlist" style="margin-top:10px">${echos.map((e) => `<div class="hrow"><div class="grow"><div class="ttl">${esc(e.name)}</div><div class="sub">${esc([e.area, e.model].filter(Boolean).join(" · ") || "Echo")}</div></div><button class="btn sm" data-hsay="${esc(e.id)}">Test voice</button></div>`).join("")}</div>`
        : `<div class="small muted" style="margin-top:8px">No Echo yet: sign in to Amazon (step 4).</div>`}</div>` : ""}
    <div class="card pad-l"><div class="row between" style="align-items:center"><h2>What happened</h2>${liveLink("house", "Run view")}</div>${(h.log || []).length ? `<ul class="phlog">${h.log.map((e) => `<li class="${e.ok ? "" : "err"}"><span class="tiny faint">${dt(e.ts)}</span> <b>${esc(e.what)}</b> ${esc(e.text)} <span class="tiny muted">· ${esc(e.by)}</span></li>`).join("")}</ul>`
      : `<div class="small muted" style="margin-top:6px">Nothing yet. Ask Hermes in chat, e.g. “Turn off all the lights” or “Say on the Echo that dinner is ready”.</div>`}</div>
  </div>`;
}

let houseSig = "";
function vHouse() {
  const err = route.q.get("err"), ok = route.q.get("connected");
  if (err || ok) { history.replaceState(history.state, "", "#/house"); toast(err || "Home Assistant is connected. The stack restarts briefly to load it.", !!err); }
  view.innerHTML = `<div class="hero"><div class="grow"><h1>House</h1></div></div><div id="housebody"></div>`;
  houseSig = "";
  houseUpdate();
  if (!TOOLS) toolsLoad().then(() => { houseSig = ""; houseUpdate(); });   // Home Assistant's menus come from the tools list
}

function houseUpdate() {
  const box = $("#housebody");
  if (!box || typing()) return;
  const h = S?.house, sig = JSON.stringify([h || null, S?.phone?.voice]);     // the phone's voice step ticks from the phone
  if (sig === houseSig) return;
  houseSig = sig;
  box.innerHTML = houseHtml(h);
  bindHouse();
}

function bindHouse() {
  const pv = $("[data-phvoice]");
  if (pv) pv.onclick = async () => {
    pv.disabled = true;
    const r = await api("/api/phone/control", { method: "POST", body: JSON.stringify({ do: "voice_setup" }) }).catch((e) => ({ error: e.message }));
    toast(r.error || "One Allow: the card is on the AI phone page (and on Telegram)", !!r.error);
  };
  const call = async (body, okMsg) => {
    const r = await api("/api/house", { method: "POST", body: JSON.stringify(body) }).catch((e) => ({ ok: false, error: e.message }));
    if (r.ok === false) toast(r.error || "Error", true); else if (r.pending) toast("Sent; Home Assistant is slow to answer"); else toast(okMsg || r.done || "Done");
    return r;
  };
  $$("[data-hs]").forEach((b) => (b.onclick = () => { b.disabled = true; call({ do: "switch", entity: b.dataset.hs, op: b.dataset.op }); }));
  const f = $("#halexa");
  const send = (cmd) => cmd && call({ do: "alexa", command: cmd, echo: f?.echo?.value || "" });
  if (f) f.onsubmit = (e) => { e.preventDefault(); send(f.cmd.value.trim()); f.cmd.value = ""; };
  $$("[data-hcmd]").forEach((b) => (b.onclick = () => send(b.dataset.hcmd)));
  $$("[data-hsay]").forEach((b) => (b.onclick = () => call({ do: "say", echo: b.dataset.hsay, message: "Hello, this is Hermes. I can speak on this Echo." }, "Speaking…")));
  const v = $("#hvoice");
  if (v) v.onchange = () => call({ do: "settings", voice: v.checked }, v.checked ? "Echo bridge on" : "Echo bridge off");
}

// ---------- share: what the phone's Share menu sent (server.py share) ----------
async function vShare() {
  const s = await api(`/api/share/${route.args[0]}`).catch(() => null);
  if (route.name !== "share") return;
  if (!s || s.error) { view.innerHTML = emptyState("This shared item is gone (they are kept two weeks).", `<a class="btn sm" href="#/">${ic.home || ""}Go to Home</a>`, "card pad-l"); return; }
  const about = clipped([s.title, s.url, s.text && s.text !== s.url ? s.text : ""].filter(Boolean).join("\n"), 4000);   // cap: prompt: what a new mission or chat starts from
  const ctx = about ? `\n\n${about}` : "";
  const ask = (q, send) => `#/chat?share=${s.id}&prompt=${encodeURIComponent(q + ctx)}${send ? "&send=1" : ""}`;
  const quick = [["Summarise this", "Summarise this for me: the key points and why it matters."],
    ["What should I do?", "What should I do with this? Suggest next steps, and say if a mission or a reminder would help."],
    ["Explain it simply", "Explain this simply, as to a smart friend outside the field."]];
  view.innerHTML = `<div class="stack">
    <div class="card pad-l">
      <div class="row wrap" style="gap:8px;align-items:center"><span class="tag">Shared ${rel(s.at)}</span><h1 class="grow wrap" style="margin:0">${esc(s.title || (s.url ? new URL(s.url).hostname : s.files[0]?.name || "Shared text"))}</h1></div>
      ${s.url ? `<a class="small mono wrap" style="display:block;margin-top:8px" href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener">${esc(s.url)}</a>` : ""}
      ${s.text && s.text !== s.url ? `<div class="small" style="margin-top:8px;white-space:pre-wrap;max-height:220px;overflow:auto">${esc(s.text)}</div>` : ""}
      ${s.files.length ? `<div class="pend" style="margin-top:10px">${s.files.map((a) => `<span class="pchip">${a.kind === "image" ? `<img src="/api/chat/files/${a.id}">` : ic.doc} <span class="wrap">${esc(a.name)}</span></span>`).join("")}</div>` : ""}
      ${s.errors.length ? `<div class="banner warn" style="margin-top:10px">${ic.alert}<span class="small">${s.errors.map(esc).join("<br>")}</span></div>` : ""}
    </div>
    <div class="card pad-l"><h2>One tap</h2><div class="suggest" style="margin-top:10px">${quick.map(([l, q]) => `<a class="btn" href="${ask(q, true)}">${esc(l)}</a>`).join("")}</div></div>
    <div class="card pad-l"><h2>Or</h2><div class="stack" style="margin-top:10px;gap:8px">
      <a class="btn" href="${ask("", false)}">${ic.chat}Ask Hermes about it…</a>
      <button class="btn" id="shsave">${ic.wiki}Save to my knowledge</button>
      <a class="btn" href="#/tasks?new=1&text=${encodeURIComponent(about.slice(0, 1500) /* cap: api: a link carries at most this much */)}">${ic.rocket}Make it a task</a>
    </div></div>
  </div>`;
  $("#shsave").onclick = async (e) => {
    e.target.disabled = true;
    const r = await api(`/api/share/${s.id}/save`, { method: "POST" }).catch((err) => ({ errors: [err.message] }));
    if (r.saved) toast(`Saved to your knowledge${r.of > 1 ? ` (${r.saved} of ${r.of})` : ""}; it is filed in a minute`);
    else { toast(r.errors?.[0] || "Nothing to save", true); e.target.disabled = false; }
  };
}

// Copy to the clipboard; true when it worked, otherwise it says why (a copy button never claims "Copied" for nothing)
async function copyText(text) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error("this browser gives no clipboard access here");
    await navigator.clipboard.writeText(String(text ?? ""));
    return true;
  } catch (e) { toast("Could not copy: " + e.message, true); return false; }
}

function scrollChat(force) {
  const box = $("#msgs");
  if (box && (force || box.scrollHeight - box.scrollTop - box.clientHeight < 260)) box.scrollTop = box.scrollHeight;
}

function bindMsgActions() {
  $$("[data-copy]").forEach((b) => (b.onclick = async () => {
    const x = cur?.messages?.[+b.dataset.copy];
    if (x && (await copyText(x.content))) toast("Copied");
  }));
  $$("[data-edit]").forEach((b) => (b.onclick = () => {
    if (streaming) return;
    const i = +b.dataset.edit, x = cur?.messages?.[i];
    if (!x) return;
    editing = i; $("#editbar").hidden = false;
    const ta = $("#cf").q; ta.value = x.content === "(see attachment)" ? "" : x.content; ta.focus(); ta.oninput();
  }));
  $$("[data-retrynow]").forEach((b) => (b.onclick = async () => {   // AST-12: try the waiting message now
    b.disabled = true;
    const id = cur?.id, r = await api(`/api/chats/${id}/retry`, { method: "POST" }).catch((e) => ({ ok: false, error: e.message }));
    toast(r.ok ? "Trying now: the answer appears here within half a minute" : r.error, !r.ok);
    if (r.ok) setTimeout(() => { if (cur?.id === id && route.name === "chat") vChat(); }, 25000);
  }));
  $$("[data-regen]").forEach((b) => (b.onclick = () => {
    if (streaming) return;
    const i = +b.dataset.regen;
    let u = i - 1;
    while (u >= 0 && cur.messages[u].role !== "user") u--;
    if (u < 0) return;
    const x = cur.messages[u];
    pending = (x.attachments || []).map((a) => ({ ...a }));
    send(x.content === "(see attachment)" ? "" : x.content, cur.mission, u);
  }));
}

function setSending(on) {
  streaming = on;
  const b = $("#sendbtn");
  if (b) { b.innerHTML = on ? ic.stop : ic.up; b.classList.toggle("stopping", on); if (on) b.classList.remove("idle"); else b.classList.add("idle"); b.title = on ? "Stop" : "Send"; b.setAttribute("aria-label", on ? "Stop" : "Send"); }
}

async function stopChat() {
  if (!cur?.id) return;
  await api(`/api/chats/${cur.id}/stop`, { method: "POST" }).catch(() => {});
  toast("Stopping…");
}

async function send(q, mis, truncate) {
  const box = $("#msgs");
  $(".empty-chat")?.remove();
  const atts = pending; pending = []; if ($("#pend")) $("#pend").innerHTML = "";
  if (typeof truncate === "number" && cur?.messages) {
    cur.messages = cur.messages.slice(0, truncate);
    box.innerHTML = ""; cur.messages.forEach((x, i) => box.insertAdjacentHTML("beforeend", bubble(x, i)));
  }
  const userMsg = { role: "user", content: q || "(see attachment)", attachments: atts };
  box.insertAdjacentHTML("beforeend", bubble(userMsg, (cur?.messages || []).length));
  scrollChat(true);
  setSending(true);
  try {
    const r = await api("/api/chat", { method: "POST", body: JSON.stringify({ chat: cur?.id, mission: mis, message: q, truncate,
      model: $("#pmodel")?.value, effort: $("#peffort")?.value, attachments: atts.map((a) => ({ id: a.id })) }) });
    if (r.error) throw new Error(r.error);
    if (!cur?.id) { cur = { id: r.chat, title: r.title, messages: [] }; history.replaceState(history.state, "", `#/chat?c=${r.chat}`); route.q = new URLSearchParams(`c=${r.chat}`); $("#ctitle").textContent = r.title; setPref(LAST_CHAT, r.chat); }
    cur.messages = [...(cur.messages || []), userMsg];
    follow(r.chat);
    loadChats().then(refreshList);
  } catch (e) {
    box.insertAdjacentHTML("beforeend", `<div class="mrow assistant"><div class="msg assistant"><div class="md">⚠ Could not send (${esc(e.message)}). Try again.</div></div></div>`);
    setSending(false);
  }
}

function follow(cid) {
  follower?.close();
  const box = $("#msgs");
  if (!box) return;
  $("#curmsg")?.remove();
  box.insertAdjacentHTML("beforeend", `<div class="mrow assistant" id="curmsg"><div class="msg assistant"><div class="typing"><span></span><span></span><span></span></div></div></div>`);
  scrollChat(true);
  setSending(true);
  const es = (follower = new EventSource(`/api/chats/${cid}/stream`));
  es.onmessage = (e) => {
    let d; try { d = JSON.parse(e.data); } catch (_) { return; }
    const c = $("#curmsg .msg");
    if (c && (d.text || d.tools?.length || d.reasoning)) c.innerHTML = `${toolsHtml(d.tools, !d.done)}${reasoningHtml(d.reasoning, !d.done && !d.text)}<div class="md">${d.text ? md(d.text) : '<div class="typing"><span></span><span></span><span></span></div>'}</div>`;
    scrollChat();
    if (d.done) {
      es.close(); follower = null; setSending(false);
      api(`/api/chats/${cid}`).then((full) => {
        if (full?.messages && $("#msgs")) {
          cur = full; const b = $("#msgs"); b.innerHTML = "";
          full.messages.forEach((x, i) => b.insertAdjacentHTML("beforeend", bubble(x, i)));
          codeCopy(b); bindMsgActions(); drawMade(); watchMade(); scrollChat(true);
        }
      }).catch(() => {});
      loadChats().then(refreshList);
    }
  };
}

