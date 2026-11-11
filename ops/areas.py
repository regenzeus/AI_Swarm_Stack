"""TSK-52: what a piece of the stack's work is for, its area. The Tasks list shows every task in one list (TSK-40's
yours/stack split is gone, the owner, 11 Nov 2026: "It just needlessly bisects and makes overview difficult"); the
area is a visible label and an optional filter, never a hidden pile.

Each crew job (ops/crew.py "area") and each workflow file (n8n/workflows/*.json "area", written by ops/n8n_gen.py)
declares its area; a task given in a sentence gets it from its kind (KIND). Upkeep is the stack's own frequent small
jobs: they fold into one row with their health on the list, and a failing one also shows on its own.
"""
AREAS = {"taxes": "Taxes", "mail": "Mail", "briefings": "Briefings", "shopping": "Shopping", "research": "Research",
         "errands": "Errands", "inbox": "Inbox", "phone": "Phone", "code": "Code", "memory": "Memory",
         "upkeep": "Upkeep"}
KIND = {"tax": "taxes", "briefing": "briefings", "shopping": "shopping", "research": "research", "analysis": "research",
        "watching": "research", "errand": "errands", "cleanup": "errands", "change": "code", "coding": "code",
        "code_question": "code"}
UPKEEP = "upkeep"


def of_kind(kind, default="research"):
    """A task's area from its kind (a briefing's is Briefings, a change's Code); one without a kind is research."""
    return KIND.get(str(kind or ""), default)


def check(area, where):
    """-> the area, or ValueError naming where it is missing or unknown."""
    if area not in AREAS:
        raise ValueError(f"{where}: area must be one of {', '.join(AREAS)}, not {area!r}")
    return area
