# A part of ledger.py (PLT-25): the Ledger's task graph, flow, run contract, replays, agent changes, requirements,
# the team, autonomy rules, refusals and scorecards, as a mixin the Ledger inherits. It runs in ledger.py's namespace
# (_part); not a module of its own.
class _LedgerWork:
    # ------------------------------------------------------------ the task graph (SWM-91) and file leases (SWM-92)
    def plan(self, actor, idem, idea_id, tasks):
        """Split an approved idea into tasks: one artifact of kind task each (key idea:<id>:<n>), part_of the idea and
        depends_on earlier tasks only (so the graph has no cycle). Tasks without dependencies are ready at once."""
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        if actor["cls"] not in (A, S):
            raise Refused("a plan is the planner's (or the runner's)")
        idea = self._get_row(idea_id)
        if idea["kind"] != "idea" or idea["state"] != "active":
            raise Refused(f"only an approved idea (active) is planned; #{idea_id} is {idea['kind']} {idea['state']}")
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= TASKS_MAX:
            raise Refused(f"a plan has 1 to {TASKS_MAX} tasks")
        if self.db.execute("select 1 from artifacts where kind='task' and key like ?", (f"idea:{idea_id}:%",)).fetchone():
            raise Refused(f"idea #{idea_id} is planned already: change its tasks instead")
        for n, t in enumerate(tasks):
            deps = t.get("depends_on") or []
            if not str(t.get("title") or "").strip() or not str(t.get("body") or "").strip():
                raise Refused(f"task {n + 1} needs a title and a body")
            if not isinstance(t.get("files") or [], list) or any(not isinstance(d, int) or not 0 <= d < n for d in deps):
                raise Refused(f"task {n + 1}: files is a list and depends_on names earlier tasks by their index (0 = the first)")
        ids = []
        with self.tx():
            for n, t in enumerate(tasks):
                plan = {"idea": idea_id, "files": TC.first([str(f) for f in t.get("files") or []], 40, "files of a planned task"), "depends_on": [ids[d] for d in t.get("depends_on") or []],  # cap: untrusted
                        "requirements": TC.first([str(x) for x in t.get("requirements") or []], 20, "requirements of a planned task"), "repo": t.get("repo") or "ai-stack"}  # cap: untrusted
                aid = self.db.execute("insert into artifacts(kind, key, state, version, label, created) values('task',?,?,?,?,?)",
                                      (f"idea:{idea_id}:{n + 1}", "draft", 0, idea["label"], self.now())).lastrowid
                self._event(aid, actor, "create", {"kind": "task", "key": f"idea:{idea_id}:{n + 1}", "title": TC.cut(redact(t["title"]), 120),  # cap: untrusted
                                                   "body": cut(redact(t["body"]), 4000), "plan": plan, "label": idea["label"],  # cap: untrusted
                                                   "origin": f"agent:{actor['id']}" if actor["cls"] == A else "system", "owner": actor["id"]})
                self._link(actor, aid, idea_id, "part_of", f"task {n + 1} of {len(tasks)}")
                for d in plan["depends_on"]:
                    self._link(actor, aid, d, "depends_on", "")
                self._event(aid, actor, "transition", {"from": "draft", "to": "open"}, "planned")
                if not plan["depends_on"]:
                    self._event(aid, {"id": "system", "cls": S}, "transition", {"from": "open", "to": "ready"}, "no dependencies")
                ids.append(aid)
            self._event(idea_id, actor, "evidence", {"text": f"planned as {len(ids)} task{'s' if len(ids) != 1 else ''}: "
                                                     + ", ".join(f"#{i}" for i in ids), "ref": "plan", "origin": "system", "label": "internal"})
            return self._done(idem, actor, {"idea": idea_id, "tasks": ids})

    def tasks(self, idea_id=None, states=None):
        """The task graph: tasks with their state, files, dependencies and builds (all, one idea's, or in some states)."""
        q, args = "select * from artifacts where kind='task'", []
        if idea_id:
            q += " and key like ?"
            args.append(f"idea:{int(idea_id)}:%")
        if states:
            q += " and state in (%s)" % ",".join("?" * len(states))
            args += list(states)
        out = []
        for r in self.db.execute(q + " order by id", args).fetchall():
            plan = json.loads(r["plan"]) if r["plan"] else {}
            refs = [x[0] for x in self.db.execute("select ref from refs where artifact_id=? and system='build'", (r["id"],))]
            out.append({**self.summary(r), "body": r["body"], "idea": plan.get("idea"), "files": plan.get("files") or [],
                        "depends_on": plan.get("depends_on") or [], "requirements": plan.get("requirements") or [],
                        "repo": plan.get("repo") or "ai-stack", "builds": refs, "updated": r["updated"]})
        return out

    def offer(self, actor):
        """Tasks whose dependencies are all done become ready (offered to builders together). -> the ready tasks."""
        if actor["cls"] != S:
            raise Refused("the runner offers tasks")
        state = {r[0]: r[1] for r in self.db.execute("select id, state from artifacts where kind='task'")}
        for t in self.tasks(states=("open",)):
            if all(state.get(d) == "done" for d in t["depends_on"]):
                with self.tx():
                    self._event(t["id"], actor, "transition", {"from": "open", "to": "ready"}, "its dependencies are done")
        return self.tasks(states=("ready",))

    @staticmethod
    def overlaps(a, b):
        a, b = a.strip("/"), b.strip("/")
        return a in ("*", "") or b in ("*", "") or a == b or a.startswith(b + "/") or b.startswith(a + "/")

    def lease(self, actor, repo, paths, holder, task=None, hours=LEASE_H):
        """Hold files for a build (SWM-92). A path is a file or a folder ("*" = the whole repo). -> {granted, held_by}:
        not granted while another holder's unexpired lease overlaps; the same holder's call refreshes its lease."""
        if actor["cls"] != S:
            raise Refused("leases are the runner's")
        paths = sorted({str(p) for p in paths or ["*"]}) or ["*"]
        now = self.now()
        held = self.db.execute("select holder, path, task from leases where repo=? and released is null and expires>? and holder<>?",
                               (repo, now, holder)).fetchall()
        clash = sorted({(h["holder"], h["path"]) for h in held for p in paths if self.overlaps(p, h["path"])})
        if clash:
            return {"granted": False, "held_by": [{"holder": h, "path": p} for h, p in clash]}
        with self.tx():
            fresh = not self.db.execute("select 1 from leases where holder=? and released is null and expires>?", (holder, now)).fetchone()
            self.db.execute("update leases set released=? where holder=? and released is null", (now, holder))
            for p in paths:
                self.db.execute("insert into leases(repo, path, holder, task, ts, expires) values(?,?,?,?,?,?)",
                                (repo, p, holder, task, now, now + float(hours) * 3600))
            if task and fresh:
                self._event(int(task), actor, "lease", {"holder": holder, "paths": paths, "hours": hours}, f"{holder} holds {len(paths)} paths")
        return {"granted": True, "expires": now + float(hours) * 3600}

    def release(self, actor, holder):
        if actor["cls"] != S:
            raise Refused("leases are the runner's")
        with self.tx():
            rows = self.db.execute("select distinct task from leases where holder=? and released is null", (holder,)).fetchall()
            self.db.execute("update leases set released=? where holder=? and released is null", (self.now(), holder))
            for (task,) in rows:
                if task:
                    self._event(int(task), actor, "lease", {"holder": holder, "released": True}, f"{holder} released its files")
        return {"released": len(rows)}

    def leases(self):
        now = self.now()
        return [dict(r) for r in self.db.execute("select repo, path, holder, task, ts, expires from leases where released is null and expires>? "
                                                 "order by holder, path", (now,))]

    # ------------------------------------------------------------ flow metrics (SWM-99)
    def flow(self, weeks=8):
        """Per ISO week: ideas proposed, accepted, proved and reopened, the median days from proposal to proved, the work in
        progress at the week's end (active or checking), and which ideas were proved (the runner adds their tokens)."""
        now = self.now()
        day0 = time.gmtime(now)
        start = now - (day0.tm_wday * 86400 + day0.tm_hour * 3600 + day0.tm_min * 60 + day0.tm_sec) - (int(weeks) - 1) * 7 * 86400
        bounds = [start + i * 7 * 86400 for i in range(int(weeks) + 1)]
        ideas = {r[0]: r[1] for r in self.db.execute("select id, created from artifacts where kind='idea'")}
        trans = self.db.execute("select e.artifact_id, e.ts, json_extract(e.payload, '$.to') t, json_extract(e.payload, '$.reopen') ro from events e "
                                "join artifacts a on a.id=e.artifact_id where a.kind='idea' and e.kind='transition' order by e.seq").fetchall()
        out = []
        for i in range(int(weeks)):
            lo, hi = bounds[i], bounds[i + 1]
            inw = [t for t in trans if lo <= t["ts"] < hi]
            proved = sorted({t["artifact_id"] for t in inw if t["t"] == "done"})
            leads = sorted((max(t["ts"] for t in inw if t["artifact_id"] == a and t["t"] == "done") - ideas.get(a, lo)) / 86400 for a in proved)
            state = {}
            for t in trans:
                if t["ts"] < hi:
                    state[t["artifact_id"]] = t["t"]
            out.append({"week": time.strftime("%G-W%V", time.gmtime(lo + 3 * 86400)), "start": lo,
                        "proposed": sum(lo <= c < hi for c in ideas.values()),
                        "accepted": len({t["artifact_id"] for t in inw if t["t"] == "active"}), "proved": len(proved),
                        "reopened": len({t["artifact_id"] for t in inw if t["ro"]}),
                        "median_days": round(leads[len(leads) // 2] if len(leads) % 2 else (leads[len(leads) // 2 - 1] + leads[len(leads) // 2]) / 2, 1) if leads else None,
                        "wip": sum(s in ("active", "checking") for s in state.values()), "proved_ids": proved})
        return out

    # ------------------------------------------------------------ the run contract (SWM-16, SWM-64)
    def run_start(self, actor, agent, run):
        """A run starts with its card's hash and its context pack as its replay input (SWM-25, SWM-82); a pack the
        agent reads during the run replaces it."""
        if actor["cls"] != S:
            raise Refused("the runner registers runs")
        card = self.cards.get(agent)
        inputs = {"pack": self.context(agent, advance=False), "tools": card.get("tools") or [], "harness": card.get("harness"),
                  "model": card.get("model")} if card else {}
        self.db.execute("insert or ignore into runs(run, agent, started, state, card, inputs) values(?,?,?,'running',?,?)",
                        (str(run)[:80], agent, self.now(), card_hash(card) if card else None,  # cap: id
                         bounded_json(inputs, 40000)))  # cap: prompt
        return {"run": run}

    def finish(self, actor, idem, summary, ops=(), run=None, inputs=None):
        """End a run: its operations are checked first (a new artifact needs evidence, every op names a known kind), then
        applied in order; a refused one names the operation and the field so the agent can fix it. The runner may add
        what a host agent worked from (inputs.signal) to its replay input. -> {run, applied}."""
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        me = actor["id"] if actor["cls"] == A else actor.get("agent") or actor["id"]
        if not str(summary or "").strip():
            raise Refused("finish needs a run summary (one or two sentences: what you did and found)")
        ops = TC.limit_items(ops or [], 20, "operations in one finish")   # limit: refuses (more is a plan for several runs; review SWM-R6)
        for n, o in enumerate(ops, 1):
            if not isinstance(o, dict) or o.get("op") not in ("upsert", "evidence", "transition", "link", "send", "rate"):
                raise Refused(f"op {n}: op must be upsert, evidence, transition, link, send or rate")
            if o["op"] == "upsert":
                new = not self.db.execute("select 1 from artifacts where kind=? and key=?", (o.get("kind"), o.get("key"))).fetchone()
                if new and not o.get("evidence"):
                    raise Refused(f"op {n} (upsert {o.get('kind')} {o.get('key')}): evidence is empty; a new artifact needs at least one evidence entry")
        if not run:
            r = self.db.execute("select run from runs where agent=? and finished is null order by started desc limit 1", (me,)).fetchone()
            run = r[0] if r else f"{me}:{self.now():.0f}"
        actor = {**actor, "run": actor.get("run") or run}            # its writes carry the run (its replay label follows them)
        with self.tx():                                              # whole or not at all (review SWM-R6)
            return self._finish(actor, idem, summary, ops, run, inputs, me)

    def _finish(self, actor, idem, summary, ops, run, inputs, me):
        done = []
        for n, o in enumerate(ops, 1):
            try:
                done.append(self._finish_op(actor, f"{idem}:{n}", o))
            except Refused as e:                                     # the finish rolls back whole and names the operation
                raise Refused(f"op {n} ({o['op']}): {e}; nothing of this finish was applied") from None
        self.db.execute("insert into runs(run, agent, started, state) values(?,?,?,'running') on conflict(run) do nothing", (run, me, self.now()))
        row = self.db.execute("select inputs, card from runs where run=?", (run,)).fetchone()
        inp = json.loads(row["inputs"] or "{}")
        if isinstance(inputs, dict) and inputs.get("signal"):
            inp["signal"] = cut(redact(str(inputs["signal"])), 8000)  # cap: prompt
        card = self.cards.get(me)
        out = json.loads(redact(json.dumps({"summary": summary, "ops": ops}, ensure_ascii=False, default=str)))
        self.db.execute("update runs set finished=?, summary=?, ops=?, state='finished', output=?, inputs=?, card=coalesce(card, ?), "
                        "label=? where run=?", (self.now(), cut(redact(summary), 4000), len(ops), bounded_json(out, 20000),  # cap: untrusted
                                                bounded_json(inp, 40000), card_hash(card) if card else None,  # cap: prompt
                                                "failed" if str(summary).lower().startswith("failed") else "pending", run))
        return self._done(idem, actor, {"run": run, "applied": len(done)})

    def _finish_op(self, actor, tag, o):
        """One operation of a finish, with every field its own tool takes (review SWM-R6: different_from, refs, evidence,
        proposal, expires_h and label were dropped)."""
        a = {k: v for k, v in o.items() if k != "op"}
        if o["op"] == "upsert":
            return self.upsert(actor, tag, a.get("kind"), a.get("key"), a.get("title"), a.get("body", ""), plan=a.get("plan"),
                               evidence=a.get("evidence") or (), impact=a.get("impact"), confidence=a.get("confidence"),
                               effort=a.get("effort"), check=a.get("check"), label=a.get("label", "internal"), base_version=a.get("base_version"),
                               unseen=a.get("unseen"), different_from=a.get("different_from") or (), refs=a.get("refs") or ())
        if o["op"] == "evidence":
            return self.add_evidence(actor, tag, int(a["id"]), a.get("text", ""), a.get("ref", ""), a.get("origin"), a.get("label", "internal"),
                                     unseen=a.get("unseen"))
        if o["op"] == "rate":
            return self.help_verdict(actor, tag, int(a["seq"]), bool(a.get("useful")), a.get("reason", ""))
        if o["op"] == "transition":
            return self.transition(actor, tag, int(a["id"]), a.get("to"), a.get("reason", ""), evidence=a.get("evidence") or (),
                                   target=a.get("target"))
        if o["op"] == "link":
            return self.link(actor, tag, int(a["src"]), int(a["dst"]), a.get("rel"), a.get("reason", ""))
        return self.send(actor, tag, a.get("to") or [], a.get("act", "inform"), a.get("text", ""), a.get("artifact_id"), a.get("reply_to"),
                         expires_h=a.get("expires_h"), label=a.get("label", "internal"), proposal=a.get("proposal"))

    def unfinished(self, older_h=1.0, days=7):
        """Runs that started over older_h hours ago and never finished (SWM-64): the health note's source."""
        now = self.now()
        return [dict(r) for r in self.db.execute("select run, agent, started from runs where finished is null and started<? and started>? "
                                                 "order by started", (now - older_h * 3600, now - days * 86400))]

    def runs_of(self, limit=40):
        return [dict(r) for r in self.db.execute("select run, agent, started, finished, summary, ops, state, card, label, label_reason, "
                                                 "failure from runs order by started desc limit ?", (int(limit),))]  # cap: list (the caller's limit)

    # ------------------------------------------------------------ replay sets and failure classes (SWM-82, SWM-84)
    def fate(self, aid):
        """What became of one artifact, as a replay label: proven, declined, duplicate, failed (reopened after it
        shipped), gone (the problem went away) or pending. -> (label, reason)."""
        a = self._get_row(aid)
        last = self.db.execute("select reason from events where artifact_id=? and kind='transition' order by seq desc limit 1", (aid,)).fetchone()
        why = (last[0] if last else "") or ""
        reopen = self.db.execute("select reason from events where artifact_id=? and kind='transition' and json_extract(payload, '$.from')='done' "
                                 "and json_extract(payload, '$.to')='open' order by seq desc limit 1", (aid,)).fetchone()
        if a["state"] == "done":
            return "proven", why
        if a["state"] == "declined":
            return "declined", why
        if a["state"] == "merged" or (a["state"] == "gone" and DUP_RE.search(why)):
            return "duplicate", why
        if reopen:
            return "failed", f"reopened after it shipped: {reopen[0]}"
        if a["state"] == "gone":
            return "gone", why
        return "pending", a["state"]

    def _outcome(self, r):
        """One run's label from the artifacts it wrote (worst first), its refusals, its finish and the requests it left."""
        now = self.now()
        lo, hi = r["started"], (r["finished"] or now) + 5
        refusals = [x[0] for x in self.db.execute("select reason from refusals where actor=? and ts>=? and ts<=? order by id", (r["agent"], lo, hi))]
        if r["finished"] is None:
            if r["started"] > now - 2 * 3600:
                return "pending", "running", []
            return "failed", "never finished (no swarm_finish)" + (f"; refused: {refusals[-1]}" if refusals else ""), []
        if str(r["summary"] or "").lower().startswith("failed"):
            return "failed", str(r["summary"]), []
        arts = [x[0] for x in self.db.execute(
            "select distinct e.artifact_id from events e join artifacts a on a.id=e.artifact_id where e.actor=? and e.cls='agent' and "
            "e.kind in ('create','update','evidence') and a.kind not in ('task','requirement') and (e.run=? or (e.ts>=? and e.ts<=?))",
            (r["agent"], r["run"], lo, hi))]
        fates = {aid: self.fate(aid) for aid in arts}
        fates.update({-n: ("duplicate", f"refused as a copy: {x}") for n, x in enumerate(refusals, 1) if x.startswith("similar open artifacts")})
        left = self.db.execute("select text from messages where recipients like ? and state='canceled' and state_reason='expired' and ts<? "
                               "and updated>?", (f'%"{r["agent"]}"%', r["finished"], lo)).fetchone()
        if left:
            fates[0] = ("failed", f"left a request unanswered until it expired: {cut(left[0], 300, 'the whole request is in its thread')}")  # cap: preview
        for label in RUN_LABELS:
            hit = [why for lb, why in fates.values() if lb == label]
            if hit:
                return label, hit[0], arts
        if CLAIM_OUT.search(r["summary"] or "") and not NONE_RE.search(r["summary"] or "") and not r["ops"]:
            return "failed", f"said it {CLAIM_OUT.search(r['summary']).group(1)} something but wrote nothing", []
        return "no_output", "", []

    def label_runs(self, days=90):
        """SWM-82, SWM-84: (re)label every run of the last days from what became of its artifacts, and classify the
        failed, declined and duplicate ones; a later decision changes the label. -> the runs whose label changed."""
        changed = []
        for r in self.db.execute("select * from runs where started>?", (self.now() - days * 86400,)).fetchall():
            label, why, arts = self._outcome(r)
            fail = classify(label, why)
            vals = (label, cut(str(why), 2000), json.dumps(fail) if fail else None, json.dumps(arts))  # cap: untrusted
            if vals != (r["label"], r["label_reason"], r["failure"], r["artifacts"]):
                self.db.execute("update runs set label=?, label_reason=?, failure=?, artifacts=?, labelled=? where run=?", (*vals, self.now(), r["run"]))
                changed.append(r["run"])
        return changed

    def replays(self, agent, days=180, limit=200):
        """SWM-82: an agent's replay set: its runs (inputs, card, output, label) and, for artifacts it wrote before runs
        were recorded, examples from history (the evidence it cited as input, the artifact as output, its fate)."""
        since = self.now() - days * 86400
        out, seen = [], set()
        for r in self.db.execute("select * from runs where agent=? and started>? order by started desc", (agent, since)).fetchall():
            arts = json.loads(r["artifacts"] or "[]")
            seen |= set(arts)
            out.append({"id": r["run"], "agent": agent, "source": "run", "ts": r["started"], "card": r["card"],
                        "inputs": json.loads(r["inputs"] or "{}"), "output": json.loads(r["output"] or "{}"), "artifacts": arts,
                        "label": r["label"] or "pending", "label_reason": r["label_reason"] or "",
                        "failure": json.loads(r["failure"]) if r["failure"] else None})
        for a in self.db.execute("select * from artifacts where owner=? and kind in ('idea','finding','report','wiki','agent_change') and created>? "
                                 "order by created desc", (agent, since)).fetchall():
            if a["id"] in seen:
                continue
            ev = [x[0] for x in self.db.execute("select text from evidence where artifact_id=? and ts<=? order by id limit 4", (a["id"], a["created"] + 60))]  # cap: parse (the evidence it was proposed with, for its scorecard)
            lessons = [dict(x) for x in self.db.execute(
                "select a.title, json_extract(e.payload, '$.to') as decision, e.reason from events e join artifacts a on a.id=e.artifact_id "
                "where a.owner=? and e.cls='owner' and e.kind='transition' and e.ts<? order by e.seq desc limit 10", (agent, a["created"]))]  # cap: parse (the scorecard's sample of decisions)
            own = [{"id": x["id"], "title": x["title"]} for x in self.db.execute(       # what its context pack listed then: its open work
                "select b.id, b.title from artifacts b where b.owner=? and b.kind=? and b.created<? and b.created>? and not exists "
                "(select 1 from events e where e.artifact_id=b.id and e.kind='transition' and e.ts<? and "
                "json_extract(e.payload, '$.to') in ('done','declined','merged','gone')) order by b.id desc limit 15",  # cap: parse (the scorecard's sample)
                (agent, a["kind"], a["created"], a["created"] - 30 * 86400, a["created"]))]
            label, why = self.fate(a["id"])
            fail = classify(label, why)
            out.append({"id": f"hist-{a['id']}", "agent": agent, "source": "history", "ts": a["created"], "card": None,
                        "inputs": {"signal": "\n".join(ev), "pack": {"own_artifacts": own, "lessons": lessons}},
                        "output": {"summary": "", "ops": [{"op": "upsert", "kind": a["kind"], "key": a["key"], "title": a["title"],
                                                           "body": a["body"], "evidence": [{"text": t} for t in ev[:2]]}]},
                        "artifacts": [a["id"]], "label": label, "label_reason": why, "failure": fail})
        out.sort(key=lambda x: -x["ts"])
        return out[:limit]

    def replay_counts(self, agent, days=90):
        """For the scorecard: the replay set's size by label and source, and the failure classes (SWM-82, SWM-84)."""
        ex = self.replays(agent, days)
        if not ex:
            return None, None
        labels = Counter(x["label"] for x in ex)
        fails = [x["failure"] for x in ex if x["failure"]]
        cats = Counter(f["category"] for f in fails)
        modes = Counter(f"{f['mode']} {f['name']}" for f in fails if f["mode"] not in ("harness", "unclassified"))
        refused = sum(1 for x in ex if x["label"] == "failed" and (x["failure"] or {}).get("mode") == "FM-1.1")   # its own writes refused
        return ({"examples": len(ex), "runs": sum(x["source"] == "run" for x in ex), "history": sum(x["source"] == "history" for x in ex),
                 "labels": dict(labels)},
                {"FC1": cats.get("FC1", 0), "FC2": cats.get("FC2", 0), "FC3": cats.get("FC3", 0), "harness": cats.get("harness", 0),
                 "unclassified": cats.get("unclassified", 0), "modes": modes.most_common(3), "refused_fc1": refused} if fails else None)

    # ------------------------------------------------------------ agent changes and their experiments (SWM-18, SWM-70)
    def experiment(self, actor, idem, artifact_id, result):
        """The runner records an agent change's replay experiment. The Ledger decides the gate itself (no score drops,
        the target rises, enough examples); a failed one sends the change back to open with the scores."""
        if actor["cls"] != S:
            raise Refused("experiments are the runner's (SWM-18)")
        if (r := self._idem(idem, actor)) is not None:
            return r
        row = self._get_row(artifact_id)
        if row["kind"] != "agent_change":
            raise Refused(f"#{artifact_id} is a {row['kind']}, not an agent change")
        plan = json.loads(row["plan"] or "{}")
        target = (plan.get("target") or {}).get("score")
        base, cand = result.get("baseline") or {}, result.get("candidate") or {}
        n = int(result.get("examples") or 0)
        if result.get("error"):
            passed, why = False, f"the experiment could not run: {result['error']}"
        elif n < MIN_EXAMPLES:
            passed, why = False, f"only {n} settled replay example{'s' if n != 1 else ''} (at least {MIN_EXAMPLES})"
        else:
            passed, why = gate(base, cand, target)
        table = "; ".join(f"{m} {base[m]:.2f} -> {cand[m]:.2f}" for m in METRICS if base.get(m) is not None and cand.get(m) is not None)
        with self.tx():
            eid = self.db.execute("insert into experiments(artifact_id, version, agent, target, examples, baseline, candidate, passed, why, detail, "
                                  "phoenix, ts) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (row["id"], int(result.get("version") or row["version"]), plan.get("agent"), target, n, json.dumps(base),
                                   json.dumps(cand), 1 if passed else 0, why, bounded_json(result.get("detail") or [], 60000),  # cap: store
                                   json.dumps(result.get("phoenix") or {}), self.now())).lastrowid
            self._event(row["id"], actor, "evidence", {"text": f"experiment {eid} on {n} replay examples: {'passed' if passed else 'not passed'}: "
                                                               f"{why}" + (f" ({table})" if table else ""), "ref": f"experiment:{eid}",
                                                       "origin": "system", "label": "internal", "alert": False})
            if not passed and row["state"] == "ready":
                self._event(row["id"], actor, "transition", {"from": "ready", "to": "open"}, f"experiment {eid}: {why}")
            return self._done(idem, actor, {"experiment": eid, "passed": passed, "why": why})

    def experiments_of(self, artifact_id):
        return [{**dict(r), "baseline": json.loads(r["baseline"] or "{}"), "candidate": json.loads(r["candidate"] or "{}"),
                 "phoenix": json.loads(r["phoenix"] or "{}"), "detail": None}
                for r in self.db.execute("select * from experiments where artifact_id=? order by id desc", (int(artifact_id),))]

    def agent_changes(self, states=None, limit=50):
        """The Improve list: every agent change with its plan, its latest experiment and, while it is watched, since when."""
        q, args = "select * from artifacts where kind='agent_change'", []
        if states:
            q += " and state in (%s)" % ",".join("?" * len(states))
            args += list(states)
        out = []
        for r in self.db.execute(q + " order by updated desc limit ?", (*args, int(limit))).fetchall():  # cap: list (the caller's limit)
            since = self.db.execute("select max(ts) from events where artifact_id=? and kind='transition' and json_extract(payload, '$.to')=?",
                                    (r["id"], r["state"])).fetchone()[0] or r["created"]
            exps = self.experiments_of(r["id"])
            out.append({**self.summary(r), "body": r["body"], "plan": json.loads(r["plan"] or "{}"), "state_since": since,
                        "experiment": exps[0] if exps else None, "experiments": len(exps),
                        "builds": [x[0] for x in self.db.execute("select ref from refs where artifact_id=? and system='build'", (r["id"],))],
                        "watch_left_days": round(max(0.0, WATCH_DAYS - (self.now() - since) / 86400), 1) if r["state"] == "checking" else None})
        return out

    # ------------------------------------------------------------ requirements in the Ledger (SWM-20)
    def requirements_sync(self, actor, items):
        """Mirror requirements/*.yaml: one artifact of kind requirement per id (key = the id), its state from its status
        (implemented = done, partial or violated = open, planned = ready, proposed = draft, deprecated = gone). An
        implemented requirement with an open finding is violated: open, with the finding as evidence. -> counts."""
        if actor["cls"] != S:
            raise Refused("requirements are synced by the runner (SWM-20)")
        made = changed = moved = 0
        for it in items:
            rid, status = str(it["id"]), it.get("status")
            violated = [str(f) for f in it.get("violated_by") or []]
            to = "open" if violated else REQ_STATE.get(status, "draft")
            body = str(it.get("statement") or it.get("title") or rid)
            plan = {k: it.get(k) for k in ("status", "priority", "phase", "group", "area", "parents", "trace", "findings") if it.get(k) is not None}
            plan["verify"] = (it.get("verify") or {}).get("by") if isinstance(it.get("verify"), dict) else None
            plan["violated_by"] = violated
            h = card_hash({"t": it.get("title"), "b": body, "p": plan, "to": to})
            known = self.db.execute("select 1 from artifacts where kind='requirement' and key=?", (rid,)).fetchone()
            fresh = self._seen(f"req:{rid}:{h}", actor) is None                  # unchanged: a replay
            res = self.upsert(actor, f"req:{rid}:{h}", "requirement", rid, f"{rid} {it.get('title') or ''}".strip(), body, plan=plan,
                              guard=False)
            made += fresh and not known
            changed += fresh and bool(known)
            row = self._get_row(res["id"])
            if row["state"] != to:
                why = (f"violated: {', '.join(violated)} open" if violated else f"status {status} in requirements/")
                self.transition(actor, f"req:{rid}:{h}:{to}:{row['updated']}", row["id"], to, why,   # per cycle (review SWM-R4)
                                evidence=[{"text": f"violated by {f} (open finding)", "ref": f} for f in violated] if violated else ())
                moved += 1
        return {"items": len(items), "created": made, "updated": changed, "moved": moved}

    # ------------------------------------------------------------ A2A agent cards (SWM-27)
    # ------------------------------------------------------------ the team (SWM-108): every agent knows the others
    def _ago(self, ts):
        if not ts:
            return "not yet"
        h = (self.now() - ts) / 3600
        return "just now" if h < 1 else f"{h:.0f} h ago" if h < 48 else f"{h / 24:.0f} days ago"

    def roster(self, agent=None):
        """SWM-108: one entry per agent of the swarm from its card and the Ledger: what it is for, what it owns, how much
        of its work is open and when it last wrote to the Ledger (agents that only answer tool calls never do). Every run's start pack has it, so no agent works as if alone."""
        n_open = dict(self.db.execute("select owner, count(*) from artifacts where kind<>'requirement' and state in (%s) group by owner"
                                      % ",".join("?" * len(OPEN_STATES)), OPEN_STATES).fetchall())
        last = dict(self.db.execute("select actor, max(ts) from events where cls='agent' group by actor").fetchall())
        return [{"id": cid, **({"you": True} if cid == agent else {}), "purpose": c.get("purpose") or "",
                 "owns": list((c.get("owns") or {}).keys()), "open": n_open.get(cid, 0), "last_ledger_write": self._ago(last.get(cid))}
                for cid, c in self.cards.items()]

    def team_who(self, me, agent):
        """SWM-108: one agent up close: its card (purpose, responsibilities, what it owns and when that is done, its roles,
        rooms and harness, when it runs and wakes, whom it may contact) and its open work by rank, as far as the asking
        agent may see it (SWM-67)."""
        c = self.cards.get(agent)
        if not c:
            raise Refused(f"no agent {agent!r}; the team is {', '.join(sorted(self.cards))}")
        work = [x for x in self.ranked(states=OPEN_STATES, agent=me, limit=10 ** 6) if x["owner"] == agent]
        return {"id": agent, **{k: c.get(k) for k in ("purpose", "responsibilities", "owns", "roles", "rooms", "harness", "schedule", "wake", "contact")},
                "open_work": work}

    def team_work(self, me, agent, days=14):
        """SWM-108: what one agent did in the last `days`: its runs with their summaries, the work of its that was settled
        (with the owner's reasons) and the evidence it gave to other agents' work, newest first, as far as the asking agent
        may see it (SWM-67). The window is the only bound."""
        if agent not in self.cards:
            raise Refused(f"no agent {agent!r}; the team is {', '.join(sorted(self.cards))}")
        since = self.now() - max(1, min(int(days), 90)) * 86400
        runs = [dict(r) for r in self.db.execute("select run, started, finished, state, summary from runs where agent=? and started>? "
                                                 "order by started desc", (agent, since))]
        if me != agent and not self.sees(me, {"label": "private" if PRIVATE_TOOLS & set((self.cards.get(agent) or {}).get("tools") or []) else ""}):
            for r in runs:                               # review SWM-R2: a run of an agent that reads private data is described
                r["summary"] = None                      # by its state only to an agent with a way out
                r["hidden"] = "its summary may hold private data"
        rows = {r["id"]: r for r in self.db.execute("select * from artifacts where owner=? or id in (select artifact_id from evidence "
                                                    "where actor=? and ts>?)", (agent, agent, since))}
        settled = [{"id": e["artifact_id"], "title": rows[e["artifact_id"]]["title"], "to": json.loads(e["payload"] or "{}").get("to"), "by": e["cls"],
                    "reason": e["reason"], "ts": e["ts"]}
                   for e in self.db.execute("select artifact_id, cls, payload, reason, ts from events where kind='transition' and ts>? and artifact_id in "
                                            "(select id from artifacts where owner=?) order by seq desc", (since, agent))
                   if e["artifact_id"] in rows and self.sees(me, rows[e["artifact_id"]])
                   and json.loads(e["payload"] or "{}").get("to") in ("done", "declined", "gone", "merged", "checking", "active")]
        helped = [{"id": e["artifact_id"], "title": rows[e["artifact_id"]]["title"], "owner": rows[e["artifact_id"]]["owner"], "text": e["text"], "ts": e["ts"]}
                  for e in self.db.execute("select artifact_id, text, ts from evidence where actor=? and ts>? order by id desc", (agent, since))
                  if e["artifact_id"] in rows and rows[e["artifact_id"]]["owner"] != agent and self.sees(me, rows[e["artifact_id"]])]
        return {"agent": agent, "days": days, "runs": runs, "settled": settled, "helped_others": helped}

    def agent_card(self, agent, base="http://swarm:8096"):
        """One agent as an A2A v1.0 AgentCard (served on the Docker network only)."""
        c = self.cards.get(agent)
        if not c:
            raise Refused(f"no agent {agent}")
        owns = c.get("owns") or {}
        skills = [{"id": f"{agent}-{k}", "name": f"{k}", "description": f"Owns {k} artifacts: done when {v}.", "tags": [k] + list(c.get("roles") or []),
                   "inputModes": ["text/plain", "application/json"], "outputModes": ["application/json"]} for k, v in owns.items()]
        skills += [{"id": f"{agent}-{n}", "name": str(r)[:60], "description": str(r), "tags": list(c.get("roles") or []) or ["agent"],  # cap: id
                    "inputModes": ["text/plain"], "outputModes": ["text/plain", "application/json"]}
                   for n, r in enumerate(c.get("responsibilities") or [])]
        return {"protocolVersion": "1.0", "name": agent, "description": c.get("purpose") or agent, "version": str(c.get("version") or "1"),
                "url": f"{base}/a2a/{agent}", "preferredTransport": "JSONRPC",
                "supportedInterfaces": [{"url": f"{base}/a2a/{agent}", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
                "provider": {"organization": "ai-stack (personal)", "url": base},
                "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
                "defaultInputModes": ["text/plain", "application/json"], "defaultOutputModes": ["application/json"],
                "skills": skills or [{"id": f"{agent}-work", "name": "work", "description": c.get("purpose") or agent, "tags": ["agent"]}],
                "securitySchemes": {}, "security": []}

    # ------------------------------------------------------------ autonomy rules (SWM-42, SWM-43)
    def set_rule(self, actor, kind, owner_agent, conditions, title):
        if actor["cls"] != O:
            raise Refused("only the owner enables an autonomy rule (SWM-42)")
        if kind not in RULE_KINDS:
            raise Refused(f"a rule may only start {', '.join(sorted(RULE_KINDS))}s; purchases, deletions, settings and deploys keep "
                          "their approvals (SWM-42, SWM-69)")
        if any(w in (str(title) + json.dumps(conditions)).lower() for w in RULE_FORBIDDEN):
            raise Refused("a rule cannot cover money, passwords, phone settings, deletion, NAS changes or deploys (SWM-42)")
        if owner_agent not in self.cards:
            raise Refused(f"no agent {owner_agent}")
        with self.tx():
            rid = self.db.execute("insert into rules(kind, owner_agent, conditions, title, created_by, ts) values(?,?,?,?,?,?)",
                                  (kind, owner_agent, json.dumps(conditions, sort_keys=True), title, actor["id"], self.now())).lastrowid
            self._event(None, actor, "rule", {"id": rid, "on": True, "kind": kind, "owner_agent": owner_agent, "conditions": conditions,
                                              "title": title}, "the owner enabled an autonomy rule")
        return {"rule": rid}

    def withdraw_rule(self, actor, rule_id, reason="withdrawn by the owner"):
        """SWM-43: what became active under the rule and has not shipped waits for the owner (blocked)."""
        if actor["cls"] != O:
            raise Refused("only the owner withdraws an autonomy rule")
        with self.tx():
            if not self.db.execute("select 1 from rules where id=? and withdrawn is null", (rule_id,)).fetchone():
                raise Refused(f"no enabled rule {rule_id}")
            self.db.execute("update rules set withdrawn=? where id=?", (self.now(), rule_id))
            self._event(None, actor, "rule", {"id": rule_id, "on": False}, reason)
            held = [r[0] for r in self.db.execute(
                "select distinct e.artifact_id from events e join artifacts a on a.id=e.artifact_id where e.actor=? and "
                "e.kind='transition' and json_extract(e.payload, '$.to')='active' and a.state='active'", (f"rule:{rule_id}",))]
            for aid in held:
                self._event(aid, actor, "transition", {"from": "active", "to": "blocked"}, f"autonomy rule {rule_id} withdrawn: waits for you")
        return {"rule": rule_id, "blocked": held}

    def rules(self, enabled_only=True):
        q = "select * from rules" + (" where withdrawn is null" if enabled_only else "") + " order by id"
        return [{**dict(r), "conditions": json.loads(r["conditions"] or "{}")} for r in self.db.execute(q)]

    def rule_covers(self, rule_id, row):
        r = self.db.execute("select * from rules where id=? and withdrawn is null", (rule_id,)).fetchone()
        if not r:
            raise Refused(f"autonomy rule {rule_id} is not enabled")
        cond = json.loads(r["conditions"] or "{}")
        check = json.loads(row["check"]) if row["check"] else {}
        why = [w for w, bad in (
            (f"kind {row['kind']}", row["kind"] != r["kind"]), (f"owner {row['owner']}", row["owner"] != r["owner_agent"]),
            (f"effort {row['effort']}", cond.get("effort") and row["effort"] not in cond["effort"]),
            (f"check {check.get('type')}", cond.get("check_types") and check.get("type") not in cond["check_types"])) if bad]
        if why:
            raise Refused(f"autonomy rule {rule_id} does not cover this artifact: " + ", ".join(why))
        per_day = int(cond.get("max_per_day") or 1)  # limit: refuses, a rule starts once a day unless its max_per_day says more
        today = self.db.execute("select count(*) from events where actor=? and kind='transition' and json_extract(payload, '$.to')='active' "
                                "and ts>?", (f"rule:{rule_id}", self.now() - 86400)).fetchone()[0]
        if today >= per_day:
            raise Refused(f"autonomy rule {rule_id} started {today} today already (at most {per_day})")

    # ------------------------------------------------------------ refusals and scorecards (SWM-80, SWM-17)
    def refused(self, actor, op, reason):
        try:
            self.db.execute("insert into refusals(ts, actor, op, reason) values(?,?,?,?)", (self.now(), actor, op, TC.cut(str(reason), 300)))  # cap: store
        except sqlite3.Error:
            pass

    def refusals_since(self, hours=24):
        return dict(self.db.execute("select actor, count(*) from refusals where ts>? group by actor", (self.now() - hours * 3600,)).fetchall())

    def refusal_causes(self, hours=24):
        """Per actor, its refused writes grouped by operation and reason, the most frequent first, each with its last time:
        the health signal names the cause and goes quiet once it stops."""
        out = {}
        for actor, op, reason, n, last in self.db.execute(
                "select actor, op, reason, count(*), max(ts) from refusals where ts>? group by actor, op, reason order by 4 desc",
                (self.now() - hours * 3600,)):
            out.setdefault(actor, []).append({"op": op, "reason": reason, "n": n, "last": last})
        return out

    def guard_trips(self, hours=24):
        """SWM-71, SWM-80: messages the Board's guards refused (loops, floods, repeats, contact policy), per agent."""
        return dict(self.db.execute("select actor, count(*) from refusals where op='send' and ts>? and (reason like '%SWM-14%' or "
                                    "reason like '%SWM-51%') group by actor", (self.now() - hours * 3600,)).fetchall())

    def expired_since(self, hours=24):
        """SWM-80: requests that expired unanswered, per receiver."""
        out = {}
        for r in self.db.execute("select recipients from messages where state='canceled' and state_reason='expired' and updated>?",
                                 (self.now() - hours * 3600,)):
            for a in json.loads(r[0] or "[]"):
                out[a] = out.get(a, 0) + 1
        return out

    def requests_of(self, agent, days=30):
        """SWM-17: how an agent handles the requests addressed to it: received, answered, declined, expired, median minutes."""
        rows = self.db.execute("select state, state_reason, ts, updated from messages where act in ('request','propose') and recipients like ? "
                               "and ts>?", (f'%"{agent}"%', self.now() - days * 86400)).fetchall()
        if not rows:
            return None
        done = [r for r in rows if r["state"] in ("completed", "rejected", "failed")]
        mins = sorted((r["updated"] - r["ts"]) / 60 for r in done)
        return {"received": len(rows), "answered": sum(r["state"] == "completed" for r in rows),
                "declined": sum(r["state"] in ("rejected", "failed") for r in rows),
                "expired": sum(r["state"] == "canceled" and r["state_reason"] == "expired" for r in rows),
                "open": sum(r["state"] in ("submitted", "working", "input-required") for r in rows),
                "median_minutes": round(mins[len(mins) // 2]) if mins else None}

    def scorecard(self, agent, days=30):
        """What an agent's ideas became: accepted share, proven share, reopen rate, refined sightings, decline reasons, refusals."""
        since = self.now() - days * 86400
        ids = [r[0] for r in self.db.execute("select id from artifacts where owner=? and kind='idea'", (agent,))]
        replays, failures = self.replay_counts(agent)
        hs = self.helps(days, helper=agent)                                   # SWM-109: its steps into other agents' lanes
        helps = {"given": len(hs), "useful": sum(h["useful"] is True for h in hs), "not_useful": sum(h["useful"] is False for h in hs),
                 "pending": sum(h["useful"] is None for h in hs)}
        if not ids:
            req = self.requests_of(agent, days)
            return {"ideas": 0, "requests": req, "replays": replays, "failures": failures, "helps": helps} if (req or replays or hs) else None
        q = ",".join("?" * len(ids))
        went = lambda to: {r[0] for r in self.db.execute(f"select distinct artifact_id from events where artifact_id in ({q}) and kind='transition' "
                                                          f"and json_extract(payload, '$.to')=?", (*ids, to))}
        active, done = went("active"), went("done")
        reopened = {r[0] for r in self.db.execute(f"select distinct artifact_id from events where artifact_id in ({q}) and kind='transition' "
                                                  f"and json_extract(payload, '$.from')='done' and json_extract(payload, '$.to')='open'", ids)}
        declines = [r[0] for r in self.db.execute(f"select reason from events where artifact_id in ({q}) and kind='transition' and cls='owner' "
                                                  f"and json_extract(payload, '$.to')='declined'", ids)]
        refined = (self.db.execute("select count(*) from evidence where text like ?", (f"seen again by {agent}:%",)).fetchone()[0]
                   + self.db.execute(f"select count(*) from events where artifact_id in ({q}) and kind='update' and actor=?", (*ids, agent)).fetchone()[0])
        made = len(ids)
        recent = self.db.execute(f"select count(*) from artifacts where id in ({q}) and created>?", (*ids, since)).fetchone()[0]
        reasons = {}
        for r in declines:
            reasons[r] = reasons.get(r, 0) + 1
        return {"ideas": made, "new_30d": recent, "accepted": len(active), "proven": len(done), "reopened": len(reopened),
                "declined": len(declines), "refined": refined,
                "accepted_share": round(len(active) / made, 2), "proven_share": round(len(done) / len(active), 2) if active else None,
                "reopen_rate": round(len(reopened) / len(done), 2) if done else None,
                "decline_reasons": sorted(reasons.items(), key=lambda x: -x[1])[:3], "refusals_24h": self.refusals_since().get(agent, 0),  # cap: top
                "requests": self.requests_of(agent, days), "replays": replays, "failures": failures, "helps": helps}
