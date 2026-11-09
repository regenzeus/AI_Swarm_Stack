// GEN-25: the deployment's trackers (docs/AI-STACK.md §8). Each tracker with the template its items start and how far
// its poll has read; each kind of write with its state: in shadow (kept here and in Needs you, nothing leaves the stack)
// or live, how many shadow writes you judged right against the measure, the writes waiting for your judgement, and the
// switch, which goes live only once the measure is met and back to shadow at any time.
let TK_SIG = "";
function trackSig() { return JSON.stringify(S?.engine?.trackers || {}); }

function vTrackers() {
  const T = S?.engine?.trackers || { trackers: [], kinds: [], shadow_needed: 0 };
  TK_SIG = trackSig();
  const need = T.shadow_needed || 0;
  view.innerHTML = `
  <a class="back" href="#/packs">${ic.back} Packs</a>
  <div class="hero"><div class="grow"><h1>Trackers</h1><p>${nf(T.trackers.length)} tracker${T.trackers.length === 1 ? "" : "s"} · ${explain("trackers-what", `Each tracker is read by a poll; a new item starts its template's run once, and an answer or comment on it wakes the run. What the stack writes back is in shadow per kind of write: it is kept here and in Needs you, and nothing leaves the stack. Once you judged ${need} of a kind's writes right, you may let that kind go live; you can send it back to shadow at any time.`)}</p></div></div>
  <div class="stack">${T.trackers.map((t) => `<div class="card pad"><div class="row"><b class="grow wrap">${esc(t.name)}</b><span class="pill">${esc(t.kind)}</span></div>
    <div class="sub wrap">starts ${t.template ? `<a href="#/templates/${encodeURIComponent(t.template)}">${esc(t.template)}</a>` : "nothing"} · read up to ${t.cursor ? esc(clock(t.cursor)) : "nothing yet"}</div></div>`).join("") || `<div class="card pad"><p class="muted">No trackers: this deployment's trackers.yaml lists none.</p></div>`}</div>
  <div class="section-h"><h2>What the stack writes</h2></div>
  <div class="stack">${T.kinds.map((k) => `<div class="card pad tk-kind">
    <div class="row wrap"><b class="grow">${esc(k.kind)}</b><span class="pill ${k.live ? "ok" : ""}">${k.live ? "live" : "shadow"}</span>
      ${k.live ? `<button class="btn sm" data-tk-live="0" data-kind="${esc(k.kind)}">Back to shadow</button>`
        : `<button class="btn sm${k.approved >= need ? " primary" : ""}" data-tk-live="1" data-kind="${esc(k.kind)}"${k.approved >= need ? "" : " disabled"}>Go live</button>`}</div>
    <div class="sub">${nf(k.approved)} of ${nf(need)} judged right${k.pending ? ` · <b>${nf(k.pending)} waiting for you</b>` : ""}</div>
    ${(k.items || []).filter((i) => i.status === "pending").map((i) => `<div class="tk-item"><div class="tiny faint">${esc(i.tracker)}/${esc(i.key)} · ${esc(clock(i.at))}</div>
      <pre class="wrap small">${esc(i.body)}</pre><div class="row"><button class="btn sm" data-tk="tracker_shadow_reject" data-kind="${esc(k.kind)}" data-id="${esc(i.id)}">Wrong</button><button class="btn sm primary" data-tk="tracker_shadow_approve" data-kind="${esc(k.kind)}" data-id="${esc(i.id)}">Right</button></div></div>`).join("")}
  </div>`).join("")}</div>`;
  view.querySelectorAll("[data-tk]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    if (!(await act({ action: b.dataset.tk, kind: b.dataset.kind, id: b.dataset.id }, b.dataset.tk === "tracker_shadow_approve" ? "Judged right: it counts toward the measure" : "Judged wrong: it does not count, and this kind stays in shadow"))) b.disabled = false;
  }));
  view.querySelectorAll("[data-tk-live]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    const live = b.dataset.tkLive === "1";
    if (!(await act({ action: "tracker_live", kind: b.dataset.kind, live }, live ? "Live: this kind of write now reaches the tracker" : "Back in shadow: nothing of this kind leaves the stack"))) b.disabled = false;
  }));
}
