"""The fixes of the UX review of 2026-10-30 (APP-25, docs/UX-REVIEW-2026-10-30.md): what the owner asked for comes before
the stack's diagnostics, the feed shows his own things first, a copy button never claims "Copied" for nothing, a failed
job is named, and every screen was clicked through (ops/ui_crawl.js)."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "images/mission-control/web/static/app.js").read_text()


def fn(name, src=APP):
    return re.search(rf"^(?:async )?function {name}\(.*?^\}}$", src, re.M | re.S)[0]


def node(js):
    p = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_a_mission_card_shows_its_result_not_a_note_for_the_health_doctor():
    js = "\n".join(["const esc = (s) => String(s ?? ''), ic = new Proxy({}, { get: () => '' }), when = () => 'soon';",
        "const agentHealth = () => 'ok', issueKeys = () => [];", fn("agentCard"),
        "const base = { key: 'm', kind: 'mission', href: '#/m', title: 'RAM', icon: '', what: 'Shopping', schedule: 'daily', needs: [], last: 1, group: 'yours' };",
        "const note = { severity: 'note', text: 'mcp__webfetch__swarm_swarm_context called 3 times' }, alert = { severity: 'alert', text: 'failed 2 times' };",
        "process.stdout.write(JSON.stringify([agentCard({ ...base, result: 'Wait: EUR 136.90 at Alternate', issues: [note] }),",
        "  agentCard({ ...base, result: 'Wait', issues: [note, alert] }), agentCard({ ...base, result: '', issues: [note] })]));"])
    with_note, with_alert, only_note = node(js)
    assert "Wait: EUR 136.90 at Alternate" in with_note and "mcp__webfetch" not in with_note and "+1 note" in with_note
    assert "failed 2 times" in with_alert and "err-t" in with_alert and "+1 note" in with_alert
    assert "mcp__webfetch__swarm_swarm_context" in only_note                         # nothing else to say: the note, marked
    v = fn("vAgent")
    assert "technical note" in v and '<details class="agnotes"' in v and 'x.severity === "alert"' in v


def test_the_latest_result_comes_before_the_run_s_log_unless_a_run_is_live():
    now = fn("agentNow")
    assert now.index('m?.outputs?.length && !A.live ? `<div class="card pad-l" id="latest"') < now.index('<div id="agrun">') < now.index("m?.outputs?.length && A.live")


def test_the_home_feed_shows_the_owner_s_things_first_and_the_stack_s_on_their_chips():
    assert 'let homeFilter = "mine"' in APP
    js = "\n".join(["let homeFilter = 'mine', homeShow = 40; const homeEx = new Map();", "const esc = (s) => String(s ?? '');",
        "const toIso = (x) => x, dayOf = () => 'Today', clockOf = () => '10:00';",
        "const items = [{ ts: '3', cat: 'results', agent: 'Job report', head: 'the answer', href: '#' }, { ts: '2', cat: 'code', agent: 'Session deploy', head: 'deployed x', href: '#' },",
        "  { ts: '1', cat: 'code', agent: 'Session deploy', head: 'DEPLOY FAILED', tone: 'err', href: '#' }, { ts: '0', cat: 'housekeeping', agent: 'Swarm', head: 'proposed wiki #417', href: '#' }];",
        "const feedItems = () => items;", fn("feedHtml"),
        "const mine = feedHtml(); homeFilter = 'all'; const every = feedHtml();",
        "process.stdout.write(JSON.stringify([mine, every]));"])
    mine, every = node(js)
    assert "the answer" in mine and "DEPLOY FAILED" in mine and "deployed x" not in mine and "proposed wiki" not in mine
    assert "deployed x" in every and "proposed wiki" in every and ">For you<" in mine and ">Everything<" in mine


def test_a_copy_button_says_copied_only_when_it_copied():
    js = fn("copyText") + """
const toasts = []; const toast = (m, bad) => toasts.push([m, !!bad]);
Object.defineProperty(globalThis, "navigator", { configurable: true,                 // node has a read-only navigator
  value: { clipboard: { writeText: () => Promise.reject(new Error("Document is not focused.")) } } });
(async () => { const a = await copyText("x"); navigator.clipboard.writeText = () => Promise.resolve(); const b = await copyText("y");
  process.stdout.write(JSON.stringify([a, b, toasts])); })();"""
    a, b, toasts = node(js)
    assert a is False and b is True and toasts == [["Could not copy: Document is not focused.", True]]
    assert APP.count("navigator.clipboard?.writeText(") == 0 or "copyText" in APP               # no bare write that ignores a failure
    assert 'b.textContent = "Copied"' in APP and "await copyText(" in APP


def test_the_stack_page_names_each_failed_job_and_links_it_and_the_crawl_is_kept():
    sysv = fn("vSystem")
    assert "failed: ${sy.failed.map((u)" in sysv and 'href="#/crew/${encodeURIComponent(c.id)}"' in sysv
    crawl = (ROOT / "ops/ui_crawl.js").read_text()
    assert "RECORDED, NOT SENT" in crawl and 'u === "/api/swarm" && m === "POST"' in crawl and "navigator.sendBeacon = () => true" in crawl
