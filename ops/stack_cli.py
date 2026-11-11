#!/usr/bin/env python3
"""stack: the command line for a person or an agent on a site (WAY-01 to WAY-08, docs/CLI.md). All work is a workflow
run, people act through Asks, and nobody edits files on a site by hand: this is the way in.

    stack workflows                          every workflow: its trigger, on or off, its agents, its last run
    stack agents                             every agent and the workflows that have a step with it
    stack runs [--workflow W] [--status S]   the newest runs, newest first (S: running, waiting, done, failed)
    stack run <workflow> [--input k=v ...]   start a run now through its Run now trigger; its id once its first step reports
    stack run show <id>                      one run: its steps, the Asks it waits on, its place in n8n
    stack asks [--all]                       the open Asks (Needs you); --all: the put-off ones too
    stack answer <ask> <choice|"words">      answer an Ask that is no gate; a gate is refused with the reason
    stack pack approve <pack> <commit>       ask for a pack commit's approval: a gate Ask a person taps in the app
    stack doctor                             what keeps this site from running as its deployment says (exit 1)
    stack install                            put the command at ~/.local/bin/stack (the deploy runs it)

Every command takes --json (what the app's API answered, for agents). Exit 0 when it did what was asked, 1 when it was
refused or failed (the reason on stderr), 2 for a command it does not know.

It talks to the app's API on this machine (STACK_URL, default http://127.0.0.1:8090, the app's published port), the same
API the app uses, with the same policy, roles and record. It names itself with the header X-Aistack-Via: cli, which only
takes rights away: the app then takes only its actions (start a run, answer an Ask that is no gate, ask for a pack's
approval), and every answer is recorded as via cli. Who: the site's operator login (STACK_OPERATOR in the environment
or in the deployment's deployment.env, else operator@this-pc); a site with the local gate (APP_GATE=local) records its
owner, as for the app. The roles decide what that login may answer. It never approves, deploys or buys anything, and
it never reads or writes the stack's files itself (the doctor's checks aside, which only read).
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:8090"
VIA = "cli"
CALL_S = 30                 # limit: stops, the app answers a read at once; one that is silent for 30 s is said so
RESULT_S = 120              # limit: waits, the runner takes a request within seconds; after 2 minutes the command says it waits still
RUN_FIND_S = 30             # limit: waits, a started run shows once its first step reports; after 30 s the command says where to look
DOCTOR_S = 600              # limit: stops, a doctor that runs longer than 10 minutes is said to hang
KIND_WORDS = {"agent": "agent step", "crew": "job", "task": "agent step", "ask": "Ask", "notify": "message"}


class Refused(Exception):
    """The app or the runner said no, or could not be reached: the reason, in its words."""


# ---------------------------------------------------------------- who and where
def base():
    return os.environ.get("STACK_URL", URL).rstrip("/")


def operator():
    """The site's operator login: STACK_OPERATOR in the environment, else the deployment's, else operator@this-pc."""
    if os.environ.get("STACK_OPERATOR"):
        return os.environ["STACK_OPERATOR"]
    try:
        sys.path.insert(0, str(ROOT / "ops"))
        import deployment as DEPLOY
        if DEPLOY.VALUES.get("STACK_OPERATOR"):
            return DEPLOY.VALUES["STACK_OPERATOR"]
    except (ImportError, SystemExit, OSError, AttributeError):
        pass
    return "operator@this-pc"


OPEN = [urllib.request.urlopen]                      # how a call goes out (the tests put the app's test client here)


def call(method, path, body=None, timeout=CALL_S):
    """One call to the app's API as the command line. -> its JSON; Refused with the app's reason."""
    req = urllib.request.Request(base() + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Tailscale-User-Login": operator(), "X-Aistack-Via": VIA,
                                          "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with OPEN[0](req, timeout=timeout) as r:  # nosemgrep: dynamic-urllib-use-detected -- the app on this machine
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            said = json.loads(e.read() or b"{}").get("error")
        except (ValueError, AttributeError):
            said = ""
        raise Refused(said or f"the app answered HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise Refused(f"the app does not answer at {base()} ({getattr(e, 'reason', e)}): is it running? (STACK_URL names another)") from None


WAIT = [time.sleep]                                  # how the command waits for the runner (the tests run it here instead)


def ask_runner(body, clock=time.time):
    """A request through the app's inbox, as the app sends it; waits for the runner's answer. -> the answer."""
    r = call("POST", "/api/request", body)
    end = clock() + RESULT_S
    while r.get("pending") and clock() < end:            # limit: waits, RESULT_S above
        WAIT[0](1)
        r = call("GET", f"/api/result/{r['id']}")
    if r.get("pending"):
        raise Refused("the runner has not taken the request yet (it is busy or restarting); it does it when it is back: do not send it again")
    if r.get("ok") is False:
        raise Refused(r.get("error") or "refused")
    return r


# ---------------------------------------------------------------- words
def _time(x):
    try:
        return dt.datetime.fromtimestamp(float(x)).astimezone() if isinstance(x, (int, float)) else dt.datetime.fromisoformat(str(x)).astimezone()
    except ValueError:
        return None


def when(x, since=None):
    """An ISO time or epoch seconds as 11 Nov 10:00 in this machine's time; only the time when it is the day of since."""
    if x in (None, ""):
        return "-"
    t = _time(x)
    if t is None:
        return str(x)
    s = _time(since) if since not in (None, "") else None
    return t.strftime("%H:%M:%S" if s and s.date() == t.date() else "%d %b %H:%M")


def step_line(i, s):
    who = s.get("agent") or s.get("job")
    kind = KIND_WORDS.get(s.get("kind"), s.get("kind") or "step")
    return (f"  {i}. {s.get('title') or kind} ({kind}{', ' + who if who else ''}): {s.get('state')}, "
            f"{when(s.get('started'))}" + (f" to {when(s.get('ended'), s.get('started'))}" if s.get("ended") else ""))


def ask_lines(a):
    out = [f"{a['id']}  {a['question']}"]
    if a.get("why"):
        out.append(f"  why: {a['why']}")
    for f in a.get("facts") or []:
        out.append(f"  {f.get('k')}: {f.get('v')}")
    chips = ", ".join(f"{c['id']} ({c['label']})" if c["id"] != c["label"] else c["id"] for c in a.get("choices") or [])
    if a.get("gate"):
        out.append(f"  a gate: only a person in the role {a.get('role')} answers it, by a tap in the app ({chips or 'its chips'})")
    elif a.get("private"):
        out.append("  private: answered in the app")
    else:
        out.append(f"  answer: {chips or 'no choices'}" + (" or your own words" if a.get("words") else ""))
    if a.get("deadline"):
        out.append(f"  by {when(a['deadline'])}")
    return out


# ---------------------------------------------------------------- the commands
def cmd_workflows(args):
    ws = call("GET", "/api/stack/workflows")["workflows"]
    lines = []
    for w in ws:
        r = w.get("last_run")
        last = f"last run {r['id']} {r['state']}, {when(r['started'])}" if r else "no run yet"
        lines += [f"{w['name']}  ({w['id']})",
                  f"  {w['trigger'] or 'by hand'} · {'on' if w['active'] else 'off'} · {last}"
                  + (f" · agents: {', '.join(w['agents'])}" if w["agents"] else "")]
    return {"workflows": ws}, lines or ["No workflows on this site."]


def cmd_agents(args):
    ags = call("GET", "/api/stack/agents")["agents"]
    lines = []
    for a in ags:
        lines += [f"{a['id']}" + (f" ({a['harness']})" if a.get("harness") else "") + (f": {a['purpose']}" if a.get("purpose") else ""),
                  f"  used in: {', '.join(a['used_in']) or 'no workflow yet'}"]
    return {"agents": ags}, lines or ["No agents on this site."]


def cmd_runs(args):
    q = urllib.parse.urlencode({k: v for k, v in (("workflow", args.workflow), ("status", args.status)) if v})
    rs = call("GET", "/api/stack/runs" + (f"?{q}" if q else ""))["runs"]
    lines = [f"{r['id']}  {r['state']:8} {r['workflow']}  started {when(r['started'])}" + ("" if r["state"] == "done" else f" · on {r['on']}")
             for r in rs]
    return {"runs": rs}, lines or ["No runs."]


def cmd_run_show(rid):
    r = call("GET", f"/api/stack/run/{urllib.parse.quote(str(rid), safe='')}")
    lines = [f"Run {r['id']} of {r['workflow']}: {r['state']}",
             f"Started {when(r['started'])}" + (f", ended {when(r['ended'], r['started'])}" if r.get("ended") else f", now on {r.get('on')}"), "Steps:"]
    lines += [step_line(i, s) for i, s in enumerate(r.get("steps") or [], 1)] or ["  none reported yet"]
    if r.get("asks"):
        lines.append("Asks it waits on:")
        lines += ["  " + x for a in r["asks"] for x in ask_lines(a)]
    lines.append(f"In n8n: {base()}{r['links']['n8n']}")
    return r, lines


def cmd_run(args, clock=time.time):
    if args.target and args.target[0] == "show":
        if len(args.target) != 2:
            raise Refused("say which run: stack run show <id>")
        return cmd_run_show(args.target[1])
    if len(args.target) != 1:
        raise Refused("say which workflow: stack run <workflow> [--input name=value ...] (stack workflows lists them)")
    inputs = {}
    for kv in args.input or []:
        k, eq, v = kv.partition("=")
        if not eq or not k.strip():
            raise Refused(f"an input is name=value, not {kv!r}")
        inputs[k.strip()] = v
    r = ask_runner({"action": "workflow_run", "workflow": args.target[0], "input": inputs})
    lines = [r.get("message") or "Started"]
    run = None
    if not args.no_wait:
        end = clock() + RUN_FIND_S
        while r.get("id") and clock() < end:             # limit: waits, RUN_FIND_S above
            try:
                got = [x for x in call("GET", f"/api/stack/runs?workflow={urllib.parse.quote(r['id'])}")["runs"]
                       if _epoch(x["started"]) >= float(r.get("started") or 0) - 2]
            except Refused:                              # a pack's workflow: its runs are in n8n, not in the stack's view yet
                break
            if got:
                run = got[-1]
                break
            WAIT[0](2)
        lines.append(f"Run {run['id']}: {run['state']} (stack run show {run['id']})" if run else
                     f"Its run shows in stack runs --workflow {r.get('id') or args.target[0]} once its first step reports")
    return {**{k: v for k, v in r.items() if k != "ok"}, "run": run}, lines


def _epoch(iso):
    try:
        return dt.datetime.fromisoformat(str(iso)).timestamp()
    except ValueError:
        return 0.0


def cmd_asks(args):
    asks = call("GET", "/api/stack/asks" + ("?all=1" if args.all else ""))["asks"]
    lines = [x for a in asks for x in ask_lines(a)]
    return {"asks": asks}, lines or ["Nothing waits for an answer."]


def cmd_answer(args):
    reply = " ".join(args.reply).strip()
    r = ask_runner({"action": "ask_answer", "id": args.ask, "reply": reply})
    msg = r.get("message") or "Answered"
    if r.get("undo_until"):
        msg += f". It is held until {when(r['undo_until'])} for an undo in the app, then the stack acts on it"
    elif r.get("reading"):
        msg += ": the stack reads your words; the app shows what it understood, with an undo"
    return {k: v for k, v in r.items() if k != "ok"}, [msg]


def cmd_pack(args):
    if args.what != "approve":
        raise Refused("stack pack approve <pack> <commit>")
    r = ask_runner({"action": "pack_ask", "name": args.pack, "commit": args.commit})
    lines = [r.get("message") or "Asked"]
    if r.get("ask"):
        lines.append(f"The Ask: {r['ask']} (stack asks)")
    return {k: v for k, v in r.items() if k != "ok"}, lines


def _has_doctor(dep):
    try:
        return bool(re.search(r"""["']doctor["']""", Path(dep).read_text(encoding="utf-8")))
    except OSError:
        return False


def doctor(app=True, run=subprocess.run):
    """-> (exit code, text): the site's doctor (python3 ops/deployment.py doctor), or, on a site without it yet, the
    checks there are (the deployment's values, and through the app the runner and the packs)."""
    dep = ROOT / "ops/deployment.py"
    own = _has_doctor(dep)
    lines, bad = [], False
    if not own:
        lines.append("This site has no doctor of its own yet (python3 ops/deployment.py doctor); these are the checks it has:")
    try:
        p = run([sys.executable, str(dep), "doctor" if own else "check"], cwd=ROOT, capture_output=True, text=True, timeout=DOCTOR_S)
        said = "\n".join(x for x in (p.stdout.strip(), p.stderr.strip()) if x)
        lines.append(said or ("the doctor found nothing" if own else "the deployment's values: nothing missing"))
        bad = p.returncode != 0
    except (OSError, subprocess.SubprocessError) as e:
        lines.append(f"the doctor did not run: {type(e).__name__}: {e}")
        bad = True
    if app:
        try:
            st = call("GET", "/api/state")
            link = st.get("link") or {}
            if link.get("state") != "ok":
                bad = True
                lines.append(f"the runner: {link.get('state') or 'unknown'}" + (f" (its state is {link['age_s']} s old)" if link.get("age_s") is not None else ""))
            else:
                lines.append(f"the runner: writes its state ({link.get('age_s')} s ago)")
            if not own:
                packs = st.get("packs") or {}
                for x in packs.get("refused") or []:
                    bad = True
                    lines.append(f"pack {x.get('name')}: {x.get('why')}")
                for x in packs.get("pending") or []:
                    bad = True
                    lines.append(f"pack {x.get('name')}: commit {str(x.get('commit'))[:12]} waits for its approval (an Ask in Needs you)")   # cap: id
        except Refused as e:
            bad = True
            lines.append(f"the app: {e}")
    return (1 if bad else 0), "\n".join(lines)


def cmd_doctor(args):
    code, text = doctor()
    return {"healthy": code == 0, "text": text}, text.splitlines() + ([] if code == 0 else ["", "Not healthy: see above."])


def install(target=None):
    """~/.local/bin/stack: a small script that runs this file. -> its path. Idempotent."""
    p = Path(target or Path.home() / ".local/bin/stack")
    p.parent.mkdir(parents=True, exist_ok=True)
    text = ("#!/bin/sh\n# the stack command line (ops/stack_cli.py); written by the deploy: python3 ops/stack_cli.py install\n"
            f'exec python3 "{Path(__file__).resolve()}" "$@"\n')
    if not p.is_file() or p.read_text() != text:
        tmp = p.with_name(".stack.tmp")
        tmp.write_text(text)
        tmp.chmod(0o755)
        tmp.replace(p)
    return p


def cmd_install(args):
    p = install()
    return {"path": str(p)}, [f"stack is at {p}"]


def parser():
    ap = argparse.ArgumentParser(prog="stack", description="The way in to this site: workflows, runs, Asks, packs, the doctor.")
    ap.add_argument("--json", action="store_true", help="what the app answered, as JSON (for agents)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("workflows", help="every workflow: its trigger, on or off, its agents, its last run")
    sub.add_parser("agents", help="every agent and the workflows it is used in")
    p = sub.add_parser("runs", help="the newest runs, newest first")
    p.add_argument("--workflow", default="", help="one workflow, by its id or name")
    p.add_argument("--status", default="", help="running, waiting, done or failed")
    p = sub.add_parser("run", help="stack run <workflow> [--input k=v ...] starts a run; stack run show <id> shows one")
    p.add_argument("target", nargs="+", help="a workflow's id or name, or: show <run id>")
    p.add_argument("--input", action="append", metavar="NAME=VALUE", help="an input of the run (again for more)")
    p.add_argument("--no-wait", action="store_true", help="do not wait for the run's id")
    p = sub.add_parser("asks", help="the open Asks (Needs you)")
    p.add_argument("--all", action="store_true", help="the put-off ones too")
    p = sub.add_parser("answer", help='stack answer <ask> <choice|"words">: an Ask that is no gate')
    p.add_argument("ask", help="its id, or its first characters")
    p.add_argument("reply", nargs="+", help="one of its choices (id or label), or your words")
    p = sub.add_parser("pack", help="stack pack approve <pack> <commit>: ask for its approval (a gate a person taps in the app)")
    p.add_argument("what", choices=["approve"])
    p.add_argument("pack")
    p.add_argument("commit")
    sub.add_parser("doctor", help="what keeps this site from running as its deployment says")
    sub.add_parser("install", help="put the command at ~/.local/bin/stack")
    return ap


COMMANDS = {"workflows": cmd_workflows, "agents": cmd_agents, "runs": cmd_runs, "run": cmd_run, "asks": cmd_asks, "answer": cmd_answer,
            "pack": cmd_pack, "doctor": cmd_doctor, "install": cmd_install}


def main(argv=None, out=sys.stdout, err=sys.stderr):
    args = parser().parse_args(argv)
    try:
        data, lines = COMMANDS[args.cmd](args)
    except Refused as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), file=out)
        print(f"stack {args.cmd}: {e}", file=err)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=1) if args.json else "\n".join(lines), file=out)
    return 0 if args.cmd != "doctor" or data.get("healthy") else 1


if __name__ == "__main__":
    sys.exit(main())
