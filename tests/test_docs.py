"""The documentation stays true to the repository (QA-19, QA-20; review 2026-10-30, D1 to D5): the API reference is
drawn from the code and current, every route says what it does, and every path, make target, app screen and relative
link a document names exists."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ops"))
import api_doc  # noqa: E402

TOP = ("ops", "images", "config", "compose", "docs", "tests", "requirements", "prompts", "nas", "spec", "smoke", "eval",
       "converters", "vault-template")


def docs():
    skip = ("requirements/REQUIREMENTS.md", "vault-template/", "eval/")
    return sorted(p for p in ROOT.rglob("*.md") if ".git/" not in p.as_posix() and "node_modules" not in p.as_posix()
                  and not p.relative_to(ROOT).as_posix().startswith(skip))


def test_the_api_reference_is_drawn_from_the_code_and_every_route_says_what_it_does():
    text, problems = api_doc.build()
    assert problems == [], problems
    assert (ROOT / "docs/API.md").read_text() == text, "docs/API.md is stale: run python3 ops/api_doc.py"
    assert "| `/api/request` | POST | Drops an owner's action into the runner's inbox" in text and "## MCP tools" in text


def test_every_path_make_target_screen_and_link_a_document_names_exists():
    targets = set(re.findall(r"^([a-z0-9-]+):", (ROOT / "Makefile").read_text(), re.M))
    app = "".join((ROOT / "images/mission-control/web/static" / f).read_text() for f in ("app.js", "swarm.js", "shop.js", "guide.js"))
    screens = set(re.findall(r"#/([a-z-]+)", app))
    bad = []
    for d in docs():
        rel, t = d.relative_to(ROOT).as_posix(), d.read_text(errors="replace")
        for p in set(re.findall(r"`((?:" + "|".join(TOP) + r")/[A-Za-z0-9_./*-]+)`", t)):
            q = p.rstrip("/.")
            if "*" in q:
                if not list(ROOT.glob(q)):
                    bad.append(f"{rel}: `{p}` matches nothing")
            elif not (ROOT / q).exists():
                bad.append(f"{rel}: `{p}` does not exist")
        for m in set(re.findall(r"`make ([a-z][a-z0-9-]+)", t)):
            if m not in targets:
                bad.append(f"{rel}: `make {m}` is no Makefile target")
        for s in set(re.findall(r"(?:open: \"?|\]\()#/([a-z-]+)", t)):
            if s not in screens:
                bad.append(f"{rel}: #/{s} is no app screen")
        for link in set(re.findall(r"\]\(((?!https?:|#|mailto:)[^)\s]+)\)", t)):
            if not (d.parent / link.split("#")[0]).exists():
                bad.append(f"{rel}: link {link} does not resolve")
    assert bad == [], "\n".join(sorted(bad))


def test_the_readme_and_the_index_point_at_what_is_current():
    readme, index = (ROOT / "README.md").read_text(), (ROOT / "docs/README.md").read_text()
    assert "docs/REVIEW-2026-10-30.md" in readme and "requirements/README.md" in readme and "docs/API.md" in readme
    listed = set(re.findall(r"\]\(([A-Z0-9-]+\.md)\)", index))
    assert {p.name for p in (ROOT / "docs").glob("*.md")} - {"README.md", "AGENTS.md"} <= listed, "a document missing from docs/README.md"
    for f in ("AGENTS.md", "docs/MISSION-CONTROL.md"):
        assert "The only writes the app does itself are" in (ROOT / f).read_text()      # the invariant with SEC-12's exceptions
    assert "make forgejo-connect" not in (ROOT / "docs/DOGFOOD.md").read_text()
