"""The step-kind registry (TSK-36): what a domain module adds to the Conductor, declared in one place next to its functions.

ops/conductor.py loads a short tuple of modules (DOMAINS) with load() at import and builds its tables from them. A module
holds a STEP_KINDS dict and, when it has a kind of task of its own, a TASK_KINDS dict. Not a plugin system: plain dicts,
in the repository, under review like any other code.

A step kind, its name being the step's harness:
  run          the adapter, run(c, t, s, prompt, card) -> the step's answer; the one field a kind must have
  owners       the agents whose plan step may name this harness (the others run on their card's harness)
  gb           the memory it needs available on the PC, in GB (TSK-08)
  waits        True: its steps wait for work elsewhere and are looked at again
  even_spent   True: it runs even at a spent budget
  fixed_plan   True: a plan with this step is fixed, the Orchestrator's checkpoints never look at it
  held         True: a checkpoint may neither drop nor rewrite this step
  where        wsl (the default: here, as every step before) or windows (a job kind of the Windows worker, through
               ops/winworker.py; its memory is the job kind's needs_gb on Windows, so it has no gb here) (GEN-11)

A task kind's hooks, each optional; without one the Conductor does what it does for every task:
  brief(t, s, all_steps, agents)   a step's prompt, instead of the Conductor's prompt_of
  assign(t, s)                     what a build step adds to its build_assign request
  built(c, t, s, build)            a build came back for review -> the step's answer
  checkpoints(t)                   False: this task's plan gets no checkpoint
  lane                             False: a role's lane is not added to a build's brief
  routing                          False: its steps are not routed to another agent

Refuses at import, with what is wrong and whose it is: a step kind or a task kind two modules claim, a step kind without
its function, a field this file does not know. Imports nothing of the stack, starts nothing, never touches a task.
"""
import types

STEP_FIELDS = {"run", "owners", "gb", "waits", "even_spent", "fixed_plan", "held", "where"}
WHERE = ("wsl", "windows")
TASK_CALLS = {"brief", "assign", "built", "checkpoints"}
TASK_FLAGS = {"lane", "routing"}


def own(table, name, whose, what):
    """A table's entry is claimed by one module only."""
    if name in table:
        raise ValueError(f"{what} {name!r} is claimed by both {table[name]} and {whose}: one module owns it")
    table[name] = whose


def known(given, fields, where):
    """A field nobody reads would be a rule that silently does nothing."""
    odd = sorted(set(given) - set(fields))
    if odd:
        raise ValueError(f"{where} has a field the registry does not know: {', '.join(odd)} (known: {', '.join(sorted(fields))})")


def load(domains, own_kinds=None):
    """The merged tables of the Conductor's own step kinds and its domain modules', or ValueError saying what is wrong."""
    out = types.SimpleNamespace(adapters={}, own_steps={}, need_gb={}, waits=(), even_spent=(), fixed_plan=(), held=(), tasks={}, where={})
    claimed, tasks = {}, {}
    declared = [("the Conductor", own_kinds or {}, {})]
    declared += [(d.__name__, getattr(d, "STEP_KINDS", {}), getattr(d, "TASK_KINDS", {})) for d in domains]
    for whose, steps, kinds in declared:
        for name, k in steps.items():
            where = f"step kind {name!r} of {whose}"
            own(claimed, name, whose, "step kind")
            known(k, STEP_FIELDS, where)
            if not callable(k.get("run")):
                raise ValueError(f"{where} has no function: its \"run\" must be the adapter that does the step")
            where_ = k.get("where", "wsl")
            if where_ not in WHERE:
                raise ValueError(f"{where} runs at {where_!r}: one of {', '.join(WHERE)}")
            if where_ == "windows" and "gb" in k:
                raise ValueError(f"{where} runs on Windows: its memory is its job kind's needs_gb there, not a gb here")
            out.where[name] = where_
            out.adapters[name] = k["run"]
            for agent in k.get("owners") or ():
                out.own_steps[agent] = (*out.own_steps.get(agent, ()), name)
            if "gb" in k:
                out.need_gb[name] = k["gb"]
            for flag in ("waits", "even_spent", "fixed_plan", "held"):
                if k.get(flag):
                    setattr(out, flag, (*getattr(out, flag), name))
        for name, hooks in kinds.items():
            where = f"task kind {name!r} of {whose}"
            own(tasks, name, whose, "task kind")
            known(hooks, TASK_CALLS | TASK_FLAGS, where)
            for hook in TASK_CALLS & set(hooks):
                if not callable(hooks[hook]):
                    raise ValueError(f"{where}: its hook {hook!r} is no function")
            out.tasks[name] = hooks
    return out
