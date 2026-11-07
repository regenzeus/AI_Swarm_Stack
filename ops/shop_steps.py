"""A price watch's steps under the Conductor (TSK-21): its plan and the shopping agent's check, as a step kind (TSK-36).

Loaded by ops/conductor.py (DOMAINS), run by its worker in the runner; ops/tasks.py takes the plan from here. The agent
itself is ops/shopping.py. A check researches and proposes; it never buys: buying stays the agent's own run, after the
owner's approval in Mission Control.
"""

M = None                                          # ops/missions.py (set by its main)


def shop_plan(t):
    """The plan of each occurrence of a price watch (TSK-21): one check by its shopping agent."""
    return [{"step": "Check the offers and prices, propose within your limits", "agent": "mission", "harness": "shop", "after": [],
             "why": "the shopping agent reads the PC's facts, your limits and the price history, researches the offers and "
                    "proposes or keeps watching; it never buys without your approval"}]


def run_shop(c, t, s, prompt, card):
    """A price watch's check (TSK-21): its shopping agent researches the offers within the owner's limits and proposes
    or keeps watching. Buying stays the agent's own run, after the owner's approval in Mission Control."""
    import shopping as SH
    slug = t["spec"].get("shop") or ""
    m = M.load_missions().get(slug)
    if not m or m.get("status") != "active":
        raise RuntimeError(f"the shopping agent {slug!r} is not active")
    prev, ev = m.get("best_price_eur"), t.get("event")
    st, summary, rel = SH.research(m, str(M.RUNLOGS / f"task-{t['id']}.{s.get('occ') or 1}-{s['idx']}.log"), ev)
    if st != "ok":
        raise RuntimeError(f"shopping agent: {summary}")
    p = next((x for x in SH.proposals(slug) if x.get("status") in ("proposed", "watching", "over_limit")), None)
    said = (f"No price drop of {float(m['watch_pct']):g} % or more: kept in the app, not sent" if SH.is_quiet(m, prev, m.get("best_price_eur"), ev)
            else "Reported the ways the task asked")
    prop = (f"Proposal {p['id']}: {p['status']}, {p['item']} for {p['total_eur']:.2f} € at {p['shop']}" if p else "No proposal this run")
    return f"{said} ({rel}). {prop}.\n\n{(M.VAULT / rel).read_text()}"


STEP_KINDS = {"shop": {"run": run_shop, "owners": ("mission",), "gb": 0.5, "fixed_plan": True}}   # gb: a Hermes turn
