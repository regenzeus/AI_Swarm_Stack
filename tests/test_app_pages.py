"""APP-82, the owner on the phone, 11 Nov 2026: Agents → Health and results while the app said "Connecting…" threw
"Cannot read properties of null (reading 'crew')". Every page of the app draws while it has no state yet: each route of
the router (and each part of the places) is drawn with the state null in a stand-in browser (tests/app_pages.cjs)."""
import re
import subprocess
from pathlib import Path

import webjs

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "images/mission-control/web/static"
ARGS = {"workflow": "request", "run": "request/t1", "task": "1", "mission": "m", "crew": "c", "agent": "main", "repo": "r", "build": "1",
        "live": "task:1:step:1", "swarm": "artifact/1", "tax": "2025/workbook", "measures": "t/r/K-1", "guide": "chat", "wiki": "", "file": ""}
PARTS = ["agents?v=team", "agents?v=team&p=measured", "agents?v=network", "agents?v=agents", "home?tab=activity",
         "home?tab=results", "home?tab=overview", "system?tab=costs", "system?tab=tools", "system?tab=connections", "workflows?new=1"]


def routes():
    names = [k.split(":")[0].strip() for k in re.search(r"const fn = \{(.*?)\}\[route\.name\]", webjs.app_js(), re.S)[1].split(",")]
    return [f"{n}/{ARGS[n]}" if ARGS.get(n) else n for n in names] + PARTS


def test_every_page_draws_while_the_app_is_still_connecting():
    files = ["guide.js", "shop.js", "swarm.js", "task.js", "tax.js", "measures.js", *webjs.APP_PARTS]
    rs = routes()
    out = subprocess.run(["node", str(Path(__file__).with_name("app_pages.cjs")), str(STATIC), *rs, "--", *files],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    errors = [x for x in out.stdout.splitlines() if ": error: " in x]
    assert not errors, "\n".join(errors)
    assert out.stdout.count(": drawn") == len(rs), out.stdout
