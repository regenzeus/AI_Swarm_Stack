// Shopping agents in Mission Control (ops/shopping.py): purchase proposals on the agent page and on Home ("needs
// you"), Approve purchase / Not now / Change, and the limits under the agent's Settings. Loaded before app.js; uses its
// globals (S, esc, ic, api, toast, route, render, grantRow) at render time. Approving works only here, from the owner's
// own device: the server refuses it from the AI phone, and no agent tool can do it.
const SHOP_STATE = {
  proposed: ["warn", "Needs you: approve or not"], watching: ["paused", "Watching the price"], approved: ["run", "Approved · buying"],
  buying: ["run", "Buying on the AI phone"], needs_owner: ["failed", "Stopped before buying: needs you"], bought: ["ok", "Ordered"],
  shipped: ["ok", "Shipped"], delivered: ["ok", "Delivered"], over_limit: ["paused", "Over your limits"], superseded: ["paused", "Replaced"],
};

function shopProposals(slug) {
  return (S.shopping?.proposals || []).filter((p) => !slug || p.slug === slug);
}

function shopCard(p, m) {
  const [pill, label] = SHOP_STATE[p.status] || ["paused", p.status];
  const v = p.verdict || {}, hist = (p.history || []).map((h) => h.total_eur);
  const gm = S.connections?.gmail?.grants?.read;
  const shot = (sid) => (sid ? `<a class="btn sm ghost" href="/api/phone/shot/${encodeURIComponent(sid)}" target="_blank" rel="noopener">Screenshot</a>` : "");
  return `<div class="card pad-l shopcard" id="shop-${p.id}" style="margin-bottom:14px">
    <div class="row between wrap" style="gap:8px;align-items:center"><span class="pill ${pill}">${esc(label)}</span><span class="tiny faint">${esc(p.id)} · ${dt(p.updated || p.created)}</span></div>
    <h2 style="margin:10px 0 2px">${esc(p.item)}</h2>
    <div class="small">${esc(p.variant || "")}</div>
    <div class="small muted" style="margin-top:4px">${esc(p.shop)} · seller ${esc(p.seller || "?")}${p.rating ? " · ★ " + esc(p.rating) : ""}</div>
    <div class="row wrap" style="gap:14px;margin-top:10px;align-items:baseline"><div><div class="tiny faint">Price incl. shipping</div><b style="font-size:20px">${eur(p.total_eur)}</b> <span class="tiny muted">${eur(p.price_eur)} + ${eur(p.shipping_eur)}</span></div>
      ${p.delivery ? `<div><div class="tiny faint">Delivery</div><b>${esc(p.delivery)}</b></div>` : ""}${hist.length > 1 ? `<div><div class="tiny faint">Price seen</div>${spark(hist)}</div>` : ""}</div>
    <div class="small" style="margin-top:8px"><span class="muted">To:</span> ${esc(p.address || "your account's default address")}</div>
    ${p.why ? `<div class="small" style="margin-top:8px"><b>Why this one:</b> ${esc(p.why)}</div>` : ""}
    ${p.why_now ? `<div class="small" style="margin-top:4px"><b>${p.status === "watching" ? "Why wait" : "Why now"}:</b> ${esc(p.why_now)}</div>` : ""}
    ${p.status === "watching" ? `<div class="small" style="margin-top:4px"><b>Waiting for:</b> ≤ ${eur(v.target_eur)} or ${esc(v.until || "?")} · keeps watching and proposes again</div>` : ""}
    ${p.trend || p.price_history ? `<div class="tiny muted" style="margin-top:6px">${esc(p.price_history || "")}${p.trend ? " · trend: " + esc(p.trend) : ""}</div>` : ""}
    ${p.app_check ? `<div class="tiny muted" style="margin-top:4px">Checked in the ${esc(p.shop)} app on the AI phone ${dt(p.app_check.at)}: ${p.app_check.price_eur ? "first price " + eur(p.app_check.price_eur) : "no price read"} ${shot(p.app_check.shot)}</div>` : ""}
    ${p.over ? `<div class="banner" style="margin-top:10px">${ic.alert}<span class="grow">${esc(p.over)}. Only a buy-it-yourself link.</span></div>` : ""}
    ${p.status === "needs_owner" ? `<div class="banner" style="margin-top:10px">${ic.alert}<span class="grow">Nothing was bought: ${esc(p.stopped_reason || "")}</span>${shot(p.stopped_shot)}</div>` : ""}
    ${p.order ? `<div class="small" style="margin-top:8px"><b>Order</b> ${esc(p.order)}${p.shipping?.status ? ` · ${esc(p.shipping.status)}${p.shipping.carrier ? " · " + esc(p.shipping.carrier) : ""}${p.shipping.eta ? " · expected " + esc(p.shipping.eta) : ""}` : ""} ${shot(p.order_shot)}</div>` : ""}
    <div class="row wrap" style="gap:8px;margin-top:12px">
      ${p.status === "proposed" ? `<button class="btn primary" data-shop="approve:${p.id}">${ic.check}Approve purchase</button><button class="btn" data-shop="not_now:${p.id}">Not now</button><button class="btn ghost" data-shop="change:${p.id}">${ic.tune}Change</button>` : ""}
      ${["watching", "over_limit", "needs_owner"].includes(p.status) ? `<button class="btn ghost" data-shop="change:${p.id}">${ic.tune}Change</button>` : ""}
      ${p.url && ["over_limit", "needs_owner", "watching", "proposed"].includes(p.status) ? `<a class="btn ${p.status === "over_limit" ? "primary" : "ghost"}" href="${esc(safeUrl(p.url))}" target="_blank" rel="noopener">Buy it yourself</a>` : ""}
      ${p.report ? `<a class="btn ghost" href="#/read?path=${encodeURIComponent(p.report)}&m=${encodeURIComponent(p.slug)}">${ic.doc}Report</a>` : ""}
    </div>
    ${["proposed", "bought", "shipped"].includes(p.status) ? `<div style="margin-top:12px"><div class="tiny faint" style="margin-bottom:6px">To follow the order (confirmation and shipping mails) it needs Gmail read access:</div>${grantRow("gmail", "read", "read the order's mails", gm, m.slug)}</div>` : ""}
    ${p.status === "proposed" ? `<div class="tiny faint" style="margin-top:8px">Approving lets the AI phone put exactly this in the cart and go to checkout. It taps the final buy button once, only if the final screen shows this item, variant and seller, a total of at most ${eur(Math.min((p.total_eur || 0) * 1.03 + 1, S.shopping?.limits?.per_purchase_eur || 150))} and your address; otherwise it stops and asks you. It never types payment data or passwords and never changes the address or payment method.</div>` : ""}
    ${p.offers?.length > 1 ? `<details style="margin-top:10px"><summary class="small muted">All offers compared · ${p.offers.length}</summary><div class="tablewrap"><table class="tbl small"><tr><th>Product</th><th>Shop · seller</th><th>Total</th><th>Delivery</th></tr>${p.offers.map((o) => `<tr><td>${o.url ? `<a href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener">${esc(o.product)}</a>` : esc(o.product)}<div class="tiny faint">${esc(o.variant || "")}</div></td><td>${esc(o.shop)} · ${esc(o.seller || "?")}${o.rating ? `<div class="tiny faint">★ ${esc(o.rating)}</div>` : ""}</td><td>${eur(o.total_eur)}</td><td>${esc(o.delivery || "")}</td></tr>`).join("")}</table></div></details>` : ""}
    ${p.journal?.length ? `<details style="margin-top:6px"><summary class="small muted">What happened · ${p.journal.length}</summary><ul class="phlog">${p.journal.slice().reverse().map((j) => `<li><span class="tiny faint">${dt(j.at)}</span> ${esc(j.text)}</li>`).join("")}</ul></details>` : ""}
  </div>`;
}

function shopMissionHtml(m) {
  const all = shopProposals(m.slug).filter((p) => p.status !== "superseded" || route.q.get("shop") === p.id);
  const ps = all.slice(0, 4);                   // the newest four; the rest are named (review APP-R17: a stopped one vanished)
  setTimeout(shopDeepLink, 0);
  if (!ps.length) return "";
  return `<div class="section-h"><h2>Purchase</h2></div>${ps.map((p) => shopCard(p, m)).join("")}${moreOf(all.length, 4)}`;
}

function shopLimitsHtml() {
  const l = S.shopping?.limits || {}, spent = S.shopping?.spent_month || 0;
  return `<div class="card pad-l" style="margin-bottom:14px" id="shoplimits"><h2>Limits</h2>
    <div class="small muted" style="margin-top:4px">For all shopping agents. Over a cap there is only a "buy it yourself" link; this month so far: <b>${eur(spent)}</b>.</div>
    <div class="grid g2" style="gap:10px;margin-top:10px">
      <label class="small">Per purchase (€)<input class="input" id="sl-pp" type="number" min="1" max="5000" step="1" value="${esc(l.per_purchase_eur ?? 150)}"></label>
      <label class="small">Per month (€)<input class="input" id="sl-pm" type="number" min="1" max="5000" step="1" value="${esc(l.per_month_eur ?? 300)}"></label>
      <label class="small">Shops it buys from (comma-separated)<input class="input" id="sl-shops" value="${esc((l.shops || ["amazon.de"]).join(", "))}"></label>
      <label class="small">Delivery-address check: words on the final screen (your postcode)<input class="input" id="sl-addr" value="${esc((l.address_words || []).join(", "))}" placeholder="e.g. 12345"></label>
    </div>
    <div class="tiny faint" style="margin-top:6px">The address is never changed: the order goes to the shop account's default address. The postcode is only compared on the final screen; without it nothing can be bought.</div>
    <button class="btn primary" style="margin-top:10px" id="sl-save">${ic.check}Save limits</button></div>`;
}

async function shopAsk(path, body) {
  try {
    let r = await api(path, { method: "POST", body: JSON.stringify(body) });
    for (let i = 0; r.pending && i < 30; i++) {
      await new Promise((res) => setTimeout(res, 1500));
      const x = await api(`/api/result/${r.id}`);
      if (!x.pending) r = x;
    }
    return r;
  } catch (e) { return { ok: false, error: e.message }; }
}

async function shopDecide(decision, id) {
  const p = shopProposals().find((x) => x.id === id);
  if (!p) return toast("This proposal is gone", true);
  let note = "";
  if (decision === "approve" && !confirm(`Buy ${p.item}${p.variant ? " (" + p.variant + ")" : ""} from ${p.shop}, seller ${p.seller || "?"}, for ${eur(p.total_eur)} incl. shipping, to your account's default address?\n\nThe AI phone puts exactly this in the cart and taps the final buy button only if the final screen matches; otherwise it stops and asks you.`)) return;
  if (decision === "change" && !(note = prompt("What should be different? (e.g. another colour, cheaper, a different shop, deliver by Friday)") || "").trim()) return;
  const r = await shopAsk("/api/shop/decide", { id, decision, note, seen: p.updated || "" });   // the card you saw (CNX-R5)
  toast(r.ok === false || r.error ? r.error || "Error" : { approve: "Approved: the AI phone is buying it now", not_now: "Not now: it keeps watching the price", change: "OK: it looks again with your change" }[decision], r.ok === false || !!r.error);
  setTimeout(() => render(true), 1500);
}

function shopDeepLink() {                     // from Telegram: #/mission/<slug>?shop=<id>&do=approve|not_now|change
  const id = route.q.get("shop"), d = route.q.get("do");
  const el = id && document.getElementById(`shop-${id}`);
  if (el) el.scrollIntoView({ block: "center" });
  if (id && ["approve", "not_now", "change"].includes(d)) {
    route.q.delete("do");
    history.replaceState(history.state, "", location.hash.replace(/&do=[a-z_]+/, ""));
    shopDecide(d, id);
  }
}

document.addEventListener("click", async (e) => {    // cards are redrawn live: delegate
  const b = e.target.closest("[data-shop]");
  if (b) {
    const [d, id] = b.dataset.shop.split(":");
    b.disabled = true;
    await shopDecide(d, id);
    b.disabled = false;
    return;
  }
  if (e.target.closest("#sl-save")) {
    const list = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
    const r = await shopAsk("/api/shop/limits", { per_purchase_eur: +$("#sl-pp").value, per_month_eur: +$("#sl-pm").value,
      shops: list($("#sl-shops").value), address_words: list($("#sl-addr").value) });
    toast(r.ok === false || r.error ? r.error || "Error" : "Limits saved", r.ok === false || !!r.error);
  }
});
