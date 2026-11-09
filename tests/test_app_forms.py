"""New task and a repeating task's settings form send what they should (FND-52: since 2026-10-28 "Start mission" threw
"watch is not defined" right after showing its spinner, so nothing was sent; the settings form read a field it lacks).
New task took the mission form's place on 8 Nov 2026 (DEC-46)."""
import webjs
import json
import re
import subprocess

APP = webjs.app_js()
STUBS = """
const sent = [], toasts = [];
const ic = new Proxy({}, { get: () => "" }), esc = (s) => String(s ?? ""), route = { q: new URLSearchParams("") };
const field = (value, checked = false) => ({ value, checked });
const btn = { disabled: false, innerHTML: "" };
let form;
const view = { set innerHTML(_) {} };
const $ = (s) => (s === "#nf" || s === "#sf" ? form : s.startsWith("button") ? btn : { hidden: false, set innerHTML(_) {} });
const $$ = () => [];
const trigEditor = () => "", deliverHtml = () => "", schedHtml = () => "", bindSched = () => {}, bindTrig = () => {};
const readSched = () => "manual", readTrig = () => [], readDeliver = () => ["telegram"];
const lines = (s) => String(s).split("\\n").filter(Boolean);
const toast = (m, bad) => toasts.push([m, !!bad]);
const act = async (req) => { sent.push(req); return { ok: true, slug: "x", changed: ["title"] }; };
const location = {};
"""


def run(body):
    fns = "\n".join(re.search(rf"^function {n}\(.*?^\}}$", APP, re.M | re.S)[0] for n in ("settingsForm",))
    out = subprocess.run(["node", "-e", STUBS + fns + body], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_start_mission_sends_the_request_for_every_type_and_a_price_watch_runs_daily():
    """New task: every kind of the old form is one of its kinds, and a price watch checks daily unless the owner picks
    another When; the old form's address opens New task with its kind."""
    kinds = APP.split("const TNEW_KINDS", 1)[1].split("\n", 1)[0]
    assert all(f'"{k}"' in kinds for k in ("briefing", "research", "shopping", "cleanup"))
    assert 'const OLD_NEW_KIND = { briefing: "briefing", task: "research", shopping: "shopping", cleanup: "cleanup" };' in APP
    bind = re.search(r"^function bindNewTask\(\) \{.*?^\}$", APP, re.M | re.S)[0]
    assert 'r.value === "shopping" && r.checked && !f.querySelector("[name=rtype]:checked")' in bind
    assert 'f.smode.value = "daily"; f.stime.value = "08:00";' in bind and '$$("[name=kind]:checked", f).forEach(watch);' in bind
    assert 'req.rhythm = { type: "schedule", schedule: s }' in bind and 'action: "task_create"' in bind


def test_mission_settings_save_without_a_type_field():
    js = """
(async () => {
  form = { title: field("RAM upgrade"), goal: field("32 GB"), deep: field("", false), kq: field(""), search: field(""), feeds: field(""),
           notes: field(""), filings: field(""), watch: field("") };
  settingsForm({ set innerHTML(_) {} }, { slug: "ram", type: "task", title: "RAM upgrade", schedule: "manual", deliver: [], triggers: [] });
  await form.onsubmit({ preventDefault() {} });
  process.stdout.write(JSON.stringify(sent.map((r) => [r.action, r.slug, r.fields.title, r.fields.goal])));
})();"""
    assert run(js) == [["update", "ram", "RAM upgrade", "32 GB"]]


def test_an_error_in_the_app_is_told_to_the_owner_not_only_reported():
    assert 'window.addEventListener("error", (e) => { reportError(' in APP and "toldError(e.message)" in APP
    assert "Something went wrong in the app:" in APP
