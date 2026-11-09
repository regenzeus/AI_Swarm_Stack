"""Every call of the app has a time limit (APP-23): a request that stalled on the way once left the "Drafting the brief"
button spinning for good (the owner's report of 2026-10-30, FND-51)."""
import webjs
import json
import re
import subprocess

APP = webjs.app_js()


def run(js):
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True, timeout=30).stdout)


def fns():
    return "\n".join(re.search(rf"^async function {n}\(.*?^\}}$", APP, re.M | re.S)[0] for n in ("api", "act"))


def test_a_request_that_never_answers_ends_with_a_clear_message_instead_of_spinning():
    js = fns() + """
const toasts = [];
const toast = (m, bad) => toasts.push([m, !!bad]);
globalThis.fetch = (path, o) => new Promise((_, rej) => o.signal.addEventListener("abort", () => rej(Object.assign(new Error("aborted"), { name: "AbortError" }))));
(async () => {
  let err = ""; try { await api("/api/state", { timeout: 50 }); } catch (e) { err = e.message; }
  const r = await act({ action: "create", title: "Copper" });
  process.stdout.write(JSON.stringify([err, r, toasts]));
})();"""
    src = js.replace('timeout: 30000', 'timeout: 60')                                     # the test waits 60 ms, not 30 s
    err, r, toasts = run(src)
    assert err == "Mission Control did not answer within 0 s" or err.startswith("Mission Control did not answer within")
    assert r is None and toasts[0][1] is True
    assert "did not answer" in toasts[0][0] and "Look under Missions before trying again" in toasts[0][0]


def test_a_poll_that_stalls_is_retried_and_a_finished_request_still_arrives():
    js = fns() + """
const toasts = []; const toast = (m, bad) => toasts.push([m, !!bad]);
let polls = 0;
globalThis.setTimeout = ((st) => (f, ms) => st(f, Math.min(ms, 5)))(setTimeout);   // the 2 s pauses, fast
globalThis.fetch = (path, o) => {
  if (path === "/api/request") return Promise.resolve({ ok: true, status: 200, headers: { get: () => "application/json" }, json: () => ({ ok: true, pending: true, id: "x" }) });
  polls++;
  if (polls < 3) return new Promise((_, rej) => o.signal.addEventListener("abort", () => rej(Object.assign(new Error("a"), { name: "AbortError" }))));
  return Promise.resolve({ ok: true, status: 200, headers: { get: () => "application/json" }, json: () => ({ ok: true, slug: "copper" }) });
};
(async () => { const r = await act({ action: "create", title: "Copper" }, "Mission created"); process.stdout.write(JSON.stringify([r, polls, toasts])); })();"""
    r, polls, toasts = run(js)
    assert r == {"ok": True, "slug": "copper"} and polls == 3 and toasts == [["Mission created", False]]   # two stalled polls, then the answer
