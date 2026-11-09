"""The running card on Home (FND-82): it opens its mission on a tap, a step's finding is the agent's markdown folded
under "What it found" (the newest open), and a long link wraps instead of widening the card past a phone screen.
Run in node on the app's own functions, not by reading the source."""
import webjs
import json
import re
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "images/mission-control/web/static"
APP, CSS = webjs.app_js(), (STATIC / "app.css").read_text()
STUBS = """
const ic = new Proxy({}, { get: (_, k) => `[${String(k)}]` });
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const md = (s) => `<md>${esc(s)}</md>`;
const TRIG = { manual: "on demand" };
let S = {};
"""


def run(body):
    fns = "\n".join(re.search(rf"^function {n}\(.*?^\}}$", APP, re.M | re.S)[0] for n in ("stepsHtml", "runningCard"))
    out = subprocess.run(["node", "-e", STUBS + fns + body], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_running_card_opens_its_mission_and_folds_each_finding_as_markdown():
    url = "https://jobs.example.com/en/job/Mandatory-Internship-Full-Stack-Development-for-Release-Automation?id=a467fe93-85f5"
    h = run(f"""
S.running = {{ slug: "job-report-2", title: "Job report", started: "2026-10-31T17:25:00+01:00", trigger: "manual", mode: "deep",
  steps: [{{ status: "done", title: "Profile", question: "What is established?", finding: "- ten years\\n- RTE" }},
          {{ status: "done", title: "Verify vacancies", question: "Which are open?", finding: "Official live posting: {url}" }},
          {{ status: "running", title: "Salary", question: "What pays?" }}], tail: [] }};
process.stdout.write(JSON.stringify(runningCard()));""")
    assert 'data-href="#/mission/job-report-2"' in h and '<a class="row grow" href="#/mission/job-report-2">' in h
    assert h.count('<details class="sfind"') == 2 and h.count('<details class="sfind" open>') == 1      # only the newest open
    assert h.index('<details class="sfind">') < h.index('<details class="sfind" open>')
    assert "<md>- ten years\n- RTE</md>" in h and url in h and h.count('class="sbody"') == 3
    assert ".steps .sbody { flex: 1; min-width: 0; overflow-wrap: anywhere; }" in CSS    # the flex item may shrink below its link


def test_a_tap_on_a_card_opens_its_page_but_not_on_its_own_links_or_folds():
    js = re.search(r"// a card that stands for a page.*?\n\}\);", APP, re.S)[0]
    out = subprocess.run(["node", "-e", """
let handler; const document = { addEventListener: (_, f) => { handler = f; } };
const location = { hash: "" }; let selected = "";
const getSelection = () => selected;
const el = (inside) => ({ closest: (q) => (q === "[data-href]" ? { dataset: { href: "#/mission/x" } } : inside.some((t) => q.split(",").includes(t)) ? {} : null) });
""" + js + """
const seen = [];
for (const [inside, sel] of [[[], ""], [["a"], ""], [["summary"], ""], [["button"], ""], [[], "some text"]]) {
  location.hash = ""; selected = sel; handler({ target: el(inside) }); seen.push(location.hash);
}
process.stdout.write(JSON.stringify(seen));"""], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == ["#/mission/x", "", "", "", ""]
