"""ASK-13 to ASK-16: the app's Needs you (web/static/app-asks.js), run in node against small stubs: the card answers in
place (chips, words, Later, Dismiss, Always, its page as a quiet link), a gate takes only a tap, a tap shows on the card
before the network answers, an answer the app cannot send is kept on the device, the runner's held, queued, asked-back
and suggested states read on the card, and the policy page shows the tiers, the rules, the undo records and the stop
switch."""
import json
import os
import tempfile
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "images/mission-control/web/static"
HARNESS = r"""
const vm = require("vm"), fs = require("fs");
const store = {}, posted = [];
const el = () => ({ innerHTML: "", hidden: false, dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, setAttribute() {}, contains: () => false,
  replaceWith() {}, remove() {}, appendChild() {}, closest: () => null, querySelector: () => null, scrollIntoView() {} });
const g = { console, Math, JSON, Date, Map, Set, Array, Object, String, Number, Promise, RegExp, Error, encodeURIComponent,
  setTimeout: (f) => 0, clearTimeout() {}, CSS: { escape: (s) => s }, crypto: { randomUUID: () => "0123456789abcdef0123456789abcdef" },
  localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } }, confirm: () => true, prompt: () => "",
  document: { activeElement: null, createElement: el, body: el() }, view: el(), route: { q: new URLSearchParams("") },
  esc: (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
  explain: (k, html, label) => `<details class="explain">${html}</details>`, prose: (s) => s, youText: (s) => String(s ?? ""), dt: (x) => `T${x}`, nf: (n) => String(n),
  ic: new Proxy({}, { get: () => "" }), APPNAME: () => "Mission Control", notConnected: () => false, linkWords: () => "",
  IDEA_CLS: new Set(["ideas"]), HOME_ICON: {}, toast: (m) => posted.push(["toast", m]), act: (req, m) => posted.push(["act", req, m]),
  emptyState: (t, a) => `<div class="empty">${t}${a}</div>`, $: () => null, $$: () => [], typing: () => false };
g.api = async (path, opts) => { posted.push(["api", JSON.parse(opts.body)]); if (g.FAIL) throw new Error("no answer"); return g.REPLY; };
g.globalThis = g;
const ctx = vm.createContext(g);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
vm.runInContext(fs.readFileSync(0, "utf8"), ctx).then((out) => process.stdout.write(JSON.stringify({ out, posted, store })));
"""


def run(script):
    h = Path(tempfile.gettempdir()) / f"asks_harness_{os.getpid()}.cjs"
    h.write_text(HARNESS)
    p = subprocess.run(["node", str(h), str(STATIC / "app-asks.js")], input=f"(async () => {{ {script} }})()", capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


ASK = {"id": "a1", "kind": "tax", "question": "How do you file for 2025?", "why": "It decides the forms.", "facts": [{"k": "year", "v": "2025"}],
       "choices": [{"id": "single", "label": "Single"}, {"id": "joint", "label": "Joint"}, {"id": "page", "label": "Look", "href": "#/tax"}],
       "status": "open", "role": "owner", "people": ["owner"], "href": "#/tax", "group": True}
GATE = {**ASK, "id": "g1", "kind": "coding", "question": "Deploy build #7?", "gate": True, "group": False,
        "choices": [{"id": "deploy", "label": "Deploy"}, {"id": "reject", "label": "Reject"}]}


def state(**kw):
    return "S = " + json.dumps({"asks": [ASK, GATE], "decisions": [], "ask_policy": {"kinds": [], "stop": {"on": False}, "hold_s": 15}, "viewer_login": "me@x", **kw}) + ";"


def test_a_card_answers_in_place_with_chips_words_later_dismiss_and_its_page_as_a_quiet_link():
    html = run(state() + "return askCard(S.asks[0]);")["out"]
    for part in ('data-achip="a1" data-out="single"', 'data-achip="a1" data-out="joint"', 'href="#/tax">Look</a>', 'data-areply="a1"',
                 "Or answer in your own words", 'data-alater="a1"', 'data-adismiss="a1"', 'data-aalways="a1"', "Its page",
                 "tomorrow morning", "It decides the forms.", "year:</span> 2025"):
        assert part in html, part
    assert "How do you file for 2025?" in html


def test_a_gate_takes_a_tap_only_never_always_and_says_who_can_answer():
    out = run(state() + "return [askCard(S.asks[1]), askCard({...S.asks[1], role: 'reviewer', people: ['rev@x']})];")["out"]
    assert "a tap by you" in out[0] and 'data-achip="g1" data-out="deploy"' in out[0] and "placeholder=\"Add a comment\"" in out[0]
    assert "data-aalways" not in out[0]
    assert "Only rev@x can answer this (reviewer)" in out[1] and "data-achip" not in out[1] and "data-areply" not in out[1]


def test_a_tap_shows_on_the_card_before_the_network_answers_and_a_failed_send_is_kept_on_the_device():
    got = run(state() + """
      g = globalThis; g.REPLY = new Promise(() => {});                 // the network never answers
      askSend(S.asks[0], { action: "ask_answer", outcome: "joint" }, "Joint");
      const at_once = askState(S.asks[0]).text;
      g.FAIL = true; g.REPLY = null;
      await askSend(S.asks[1], { action: "ask_answer", outcome: "deploy" }, "Deploy");
      return [at_once, askState(S.asks[1]).text, outboxRead().map((x) => x.req)];""")
    at_once, kept, box = got["out"]
    assert at_once == "Sending: Joint…"
    assert kept.startswith("Kept on this device") and box[0]["action"] == "ask_answer" and box[0]["outcome"] == "deploy" and box[0]["answer_id"]
    sent = [p[1] for p in got["posted"] if p[0] == "api"]
    assert sent[0] == {"action": "ask_answer", "outcome": "joint", "id": "a1", "answer_id": "0123456789abcdef0123456789abcdef"}


def test_the_card_reads_the_runners_held_queued_asked_back_and_suggested_states():
    held = {**ASK, "status": "answered", "pending": {"state": "held", "answer_id": "x1", "undo_until": 9}, "answer": {"outcome": "joint", "interpreted_as": "Joint, like last year"}}
    back = {**ASK, "id": "a2", "pending": {"state": "asked_back", "ask_back": "So 23 km one way?", "understood": "23 km"}}
    sug = {**GATE, "pending": {"state": "suggested", "suggest": "deploy"}}
    out = run("S = " + json.dumps({"asks": [held, back, sug, {**ASK, "id": "a3"}], "asks_queued": [{"id": "a3", "action": "ask_answer"}]}) + """;
      return [askState(S.asks[0]), askState(S.asks[1]), askState(S.asks[2]), askState(S.asks[3]), askCard(S.asks[0]), askCard(S.asks[2])];""")["out"]
    assert out[0]["text"] == "Understood as: Joint, like last year" and out[0]["undo"] == "x1" and 'data-aundo="a1"' in out[4]
    assert out[1]["back"] == "So 23 km one way?"
    assert out[2]["text"].startswith("Did you mean Deploy?") and 'class="btn sm primary" data-achip="g1" data-out="deploy"' in out[5]
    assert out[3]["text"].startswith("Kept: the stack is restarting")


def test_an_undo_of_an_answer_that_never_left_the_device_is_taken_back_there():
    got = run(state() + """
      globalThis.FAIL = true;
      await askSend(S.asks[0], { action: "ask_answer", outcome: "joint" }, "Joint");
      const id = outboxRead()[0].req.answer_id;
      await askUndo("a1", id);
      return outboxRead();""")
    assert got["out"] == [] and ["toast", "Undone: it waits for your answer again"] in got["posted"]


def test_the_policy_page_shows_tiers_rules_undo_records_and_the_stop_switch():
    pol = {"kinds": [{"kind": "phone-routine", "title": "Phone routine", "tier": "ask", "gate": False, "role": "owner"},
                     {"kind": "coding", "title": "Code", "tier": "ask", "gate": True, "role": "owner"}],
           "rules": [{"id": "r1", "kind": "phone-routine", "effect": "allow", "outcome": "approve", "under": {"fact": "size_gb", "max": 1}, "by": "me@x", "at": 5}],
           "undo": [{"id": "u1", "what": "Empty the caches", "by": "rule:r1", "at": 5, "until": 9, "state": "open"}],
           "stop": {"on": True, "at": 7, "paused": {"agent runs queued": 2, "swarm": "paused"}}}
    out = run("S = " + json.dumps({"ask_policy": pol}) + "; vPolicy(); return [view.innerHTML, stopHtml()];")["out"]
    page, stop = out
    for part in ("Phone routine", "Asks you first", "Gate: a tap only", "1 rule", "always “approve”", "size_gb is at most", "me@x",
                 'data-rdel="r1"', "Empty the caches", 'data-uundo="u1"', "Everything is stopped", 'data-astop="off"'):
        assert part in page, part
    assert "Held: agent runs queued: 2 · swarm: paused" in stop


def test_the_app_loads_its_asks_part_after_tasks_and_caches_it():
    html = (ROOT / "images/mission-control/web/index.html").read_text()
    assert html.index("app-tasks.js") < html.index("app-asks.js") < html.index("app.js\"")
    assert "/static/app-asks.js" in (ROOT / "images/mission-control/web/sw.js").read_text()
    base = (STATIC / "app-base.js").read_text()
    assert "policy: vPolicy" in base and '"policy"' in base.split("const LIVE = ")[1].split("\n")[0]
