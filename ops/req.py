#!/usr/bin/env python3
"""The requirements of the stack (requirements/*.yaml): check them, render them, show one.

  python3 ops/req.py check        every rule of requirements/README.md; exit 1 with the problems (run by ops/check.sh)
  python3 ops/req.py render       rewrite requirements/REQUIREMENTS.md from the YAML files
  python3 ops/req.py show <id>    one record with everything that points at it
  python3 ops/req.py prove [--base REF] [--ids A,B]   a build's named requirements each have a test its change runs (SWM-96)

Reads only the repository and changes nothing but REQUIREMENTS.md (on render). Stdlib and PyYAML only.
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQ = "requirements"
OUT = "REQUIREMENTS.md"
BASELINE = "unmapped-tests.txt"
UNTRACED = "untraced-files.txt"                   # source files no requirement names, each with its reason; only shrinks
SRC_DIRS = ("ops", "images", "config", "compose", "nas", "converters", "smoke", "spec")
SRC_EXT = (".py", ".sh", ".js", ".mjs", ".ps1", ".yaml", ".yml", ".toml", ".json", ".conf", "Caddyfile", "Dockerfile")
SKIP = re.compile(r"/(vendor|__pycache__|node_modules|tests|fixtures)/")
IMAGE_CONFIG = re.compile(r"^images/[^/]+/(Dockerfile|[^/]+\.(conf|toml|json|ya?ml))$")   # traced with its image's code

TYPES = {"functional", "quality", "interface", "constraint", "process"}
PRIORITIES = {"must", "should", "could"}
STATUSES = ("implemented", "partial", "violated", "planned", "proposed", "deprecated")
METHODS = {"test", "inspection", "analysis", "demonstration"}
SEVERITIES = ("high", "medium", "low")
KINDS = {"contradiction", "drift", "defect", "incoherence", "risk"}
FSTATUS = {"open", "fixed", "accepted"}
# words that make a statement unverifiable (ISO/IEC/IEEE 29148 §5.2.7, "unbounded or ambiguous terms")
VAGUE = ("appropriate", "adequate", "as needed", "as required", "etc", "and/or", "user-friendly", "easy", "easily",
         "fast", "quickly", "robust", "efficient", "flexible", "if possible", "normally", "normal", "some", "several",
         "about", "approximately", "reasonable", "sufficient", "seamless", "intuitive", "best", "optimal")
VAGUE_RE = re.compile(r"(?<![\w-])(" + "|".join(re.escape(v) for v in VAGUE) + r")(?![\w-])", re.I)   # not inside gpt-sub-fast
ID_RE = re.compile(r"^[A-Z]{2,3}-\d{2,3}$")
PATHLIKE = re.compile(r"^[\w.][\w./+-]*$")
SPECIAL = {"stakeholder-needs.yaml": "SN", "constraints.yaml": "CST", "decisions.yaml": "DEC", "findings.yaml": "FND"}


def load(root=ROOT):
    """-> (areas: [{file, area, prefix, items}], records: {id: record with _file, _area, _prefix}, problems)."""
    areas, records, problems = [], {}, []
    for f in sorted((root / REQ).glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError as e:
            problems.append(f"{f.name}: not valid YAML: {str(e).splitlines()[0]}")
            continue
        if not isinstance(doc, dict) or not doc.get("prefix") or not doc.get("area") or not isinstance(doc.get("items"), list):
            problems.append(f"{f.name}: needs area, prefix and a list of items")
            continue
        phases = doc.get("phases") or {}
        areas.append({"file": f.name, "area": doc["area"], "prefix": doc["prefix"], "items": doc["items"], "phases": phases})
        for it in doc["items"]:
            if not isinstance(it, dict) or not it.get("id"):
                problems.append(f"{f.name}: an item without an id")
                continue
            rid = str(it["id"])
            if rid in records:
                problems.append(f"{rid}: duplicate id (also in {records[rid]['_file']})")
                continue
            records[rid] = {**it, "_file": f.name, "_area": doc["area"], "_prefix": doc["prefix"], "_phases": phases}
    return areas, records, problems


def kind_of(r):
    return {"SN": "need", "DEC": "decision", "FND": "finding"}.get(r["_prefix"], "requirement")


def tests_in(root=ROOT):
    """Every unit test as 'tests/<file>::<name>'."""
    out = set()
    for f in sorted((root / "tests").glob("test_*.py")):
        for m in re.finditer(r"^(?:async )?def (test_\w+)\(", f.read_text(), re.M):
            out.add(f"tests/{f.name}::{m[1]}")
    return out


def exists(root, ref):
    if "::" in ref:
        return ref in tests_in(root)
    return (root / ref).exists()


def claimed_tests(records):
    return {b for r in records.values() if isinstance(r.get("verify"), dict) for b in r["verify"].get("by") or [] if "::" in str(b)}


def baseline(root=ROOT):
    p = root / REQ / BASELINE
    return [x.strip() for x in p.read_text().splitlines() if x.strip() and not x.startswith("#")] if p.exists() else []


def source_files(root=ROOT):
    """The code and configuration that make the stack's behaviour (not docs, tests or vendored files)."""
    return sorted(p.relative_to(root).as_posix() for d in SRC_DIRS for p in (root / d).rglob("*")
                  if p.is_file() and p.name.endswith(SRC_EXT) and not SKIP.search("/" + p.relative_to(root).as_posix()))


def untraced(root=ROOT):
    """FND-69: source files that no requirement names (as a trace, source or verify path, or in its text), where a
    directory a requirement names covers what is under it and an image's Dockerfile and config go with its code."""
    named = set(re.findall(r"[\w./-]+", "\n".join(p.read_text() for p in sorted((root / REQ).glob("*.yaml")))))
    dirs = {n.rstrip("/") for n in named if "/" in n}
    images = {"/".join(n.split("/")[:2]) for n in named if n.startswith("images/") and n.count("/") >= 2}

    def traced(rel):
        parts = rel.split("/")
        return (rel in named or any("/".join(parts[:i]) in dirs for i in range(2, len(parts)))
                or (IMAGE_CONFIG.match(rel) and "/".join(parts[:2]) in images))
    return [f for f in source_files(root) if not traced(f)]


def untraced_list(root=ROOT):
    p = root / REQ / UNTRACED
    rows = [x for x in p.read_text().splitlines() if x.strip() and not x.startswith("#")] if p.exists() else []
    return {r.split("#", 1)[0].strip(): r.split("#", 1)[1].strip() if "#" in r else "" for r in rows}


def check(root=ROOT):
    """All problems as plain sentences; an empty list means the requirements are sound."""
    areas, records, problems = load(root)
    ids = set(records)
    tests = tests_in(root)
    for a in areas:
        want = SPECIAL.get(a["file"])
        if want and a["prefix"] != want:
            problems.append(f"{a['file']}: prefix must be {want}")
    for rid, r in records.items():
        where = f"{rid} ({r['_file']})"
        if not ID_RE.match(rid) or not rid.startswith(r["_prefix"] + "-"):
            problems.append(f"{where}: id must be {r['_prefix']}-<number>")
        k = kind_of(r)
        if not r.get("title"):
            problems.append(f"{where}: no title")
        if k == "need":
            for fld in ("need", "priority", "sources"):
                if not r.get(fld):
                    problems.append(f"{where}: no {fld}")
            if r.get("priority") and r["priority"] not in PRIORITIES:
                problems.append(f"{where}: priority must be one of {sorted(PRIORITIES)}")
            continue
        if k == "decision":
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(r.get("date", ""))):
                problems.append(f"{where}: date must be YYYY-MM-DD")
            if not r.get("decision"):
                problems.append(f"{where}: no decision")
            continue
        if k == "finding":
            if r.get("severity") not in SEVERITIES:
                problems.append(f"{where}: severity must be one of {list(SEVERITIES)}")
            if r.get("kind") not in KINDS:
                problems.append(f"{where}: kind must be one of {sorted(KINDS)}")
            if r.get("status") not in FSTATUS:
                problems.append(f"{where}: status must be one of {sorted(FSTATUS)}")
            for fld in ("finding", "evidence", "affects", "recommendation"):
                if not r.get(fld):
                    problems.append(f"{where}: no {fld}")
            if r.get("status") == "fixed" and not r.get("resolved"):
                problems.append(f"{where}: a fixed finding names the commit in resolved")
            for a in r.get("affects") or []:
                if a not in ids:
                    problems.append(f"{where}: affects unknown {a}")
                elif rid not in (records[a].get("findings") or []):
                    problems.append(f"{where}: affects {a}, but {a} does not list it in findings")
            continue
        # a requirement (constraints included)
        st = str(r.get("statement") or "")
        if " shall " not in f" {st} ":
            problems.append(f"{where}: the statement has no 'shall' (EARS)")
        v = VAGUE_RE.search(st)
        if v:
            problems.append(f"{where}: vague word '{v[1]}' in the statement")
        if r.get("type") not in TYPES:
            problems.append(f"{where}: type must be one of {sorted(TYPES)}")
        if r.get("priority") not in PRIORITIES:
            problems.append(f"{where}: priority must be one of {sorted(PRIORITIES)}")
        status = r.get("status")
        if status not in STATUSES:
            problems.append(f"{where}: status must be one of {list(STATUSES)}")
        if not r.get("parents"):
            problems.append(f"{where}: no parents (a need, constraint or requirement it refines)")
        for p in r.get("parents") or []:
            if p not in ids:
                problems.append(f"{where}: unknown parent {p}")
            elif kind_of(records[p]) in ("decision", "finding"):
                problems.append(f"{where}: parent {p} is a {kind_of(records[p])}; cite it in sources")
        if not r.get("sources"):
            problems.append(f"{where}: no sources")
        for s in r.get("sources") or []:
            s = str(s)
            if ID_RE.match(s):
                if s not in ids:
                    problems.append(f"{where}: unknown source {s}")
            elif PATHLIKE.match(s) and ("/" in s or s.endswith(".md")) and not (root / s).exists():
                problems.append(f"{where}: source {s} does not exist")
        ver = r.get("verify")
        if status in ("implemented", "partial", "violated", "deprecated") and not isinstance(ver, dict):
            problems.append(f"{where}: {status} needs verify")
        if isinstance(ver, dict):
            if ver.get("method") not in METHODS:
                problems.append(f"{where}: verify.method must be one of {sorted(METHODS)}")
            by = [str(b) for b in ver.get("by") or []]
            if not by:
                problems.append(f"{where}: verify.by is empty")
            if ver.get("method") == "test" and not any("::" in b for b in by):
                problems.append(f"{where}: method test names no test (tests/<file>::<test>)")
            for b in by:
                if "::" in b and b not in tests:
                    problems.append(f"{where}: verify.by {b} is not a test")
                elif "::" not in b and not (root / b).exists():
                    problems.append(f"{where}: verify.by {b} does not exist")
        for t in r.get("trace") or []:
            if not (root / str(t)).exists():
                problems.append(f"{where}: trace {t} does not exist")
        if status == "planned" and not r.get("acceptance"):
            problems.append(f"{where}: planned needs acceptance (how it will be verified)")
        if "phase" in r and r["phase"] not in r["_phases"]:
            problems.append(f"{where}: phase must be one of {sorted(r['_phases'])}" if r["_phases"] else f"{where}: phase given, but the area lists no phases")
        if status in ("partial", "violated") and not r.get("gap"):
            problems.append(f"{where}: {status} needs a gap")
        if status == "violated" and not r.get("findings"):
            problems.append(f"{where}: violated needs a finding")
        if status == "deprecated":
            sup = r.get("superseded_by")
            if not sup and not r.get("reason"):
                problems.append(f"{where}: deprecated needs superseded_by or reason")
            if sup and sup not in ids:
                problems.append(f"{where}: superseded_by unknown {sup}")
        for fnd in r.get("findings") or []:
            if fnd not in ids or kind_of(records[fnd]) != "finding":
                problems.append(f"{where}: unknown finding {fnd}")
            elif rid not in (records[fnd].get("affects") or []):
                problems.append(f"{where}: lists {fnd}, but {fnd} does not affect it")
    # every need is refined by a requirement
    refined = {p for r in records.values() if kind_of(r) == "requirement" for p in r.get("parents") or []}
    for rid, r in records.items():
        if kind_of(r) == "need" and rid not in refined:
            problems.append(f"{rid}: no requirement refines this need")
    # every test is claimed, and the baseline only shrinks
    claimed, base = claimed_tests(records), baseline(root)
    for t in sorted(tests - claimed - set(base)):
        problems.append(f"{t}: no requirement claims this test (add it to a requirement's verify.by)")
    for t in base:
        if t in claimed:
            problems.append(f"{BASELINE}: {t} is claimed now; remove it from the list")
        elif t not in tests:
            problems.append(f"{BASELINE}: {t} no longer exists; remove it from the list")
    # every source file is traced by a requirement or listed with its reason, and the list only shrinks (FND-69)
    listed, loose = untraced_list(root), set(untraced(root))
    for f in sorted(loose - set(listed)):
        problems.append(f"{f}: no requirement names this file (trace it, or list it in {UNTRACED} with a reason)")
    for f, why in sorted(listed.items()):
        if not (root / f).exists():
            problems.append(f"{UNTRACED}: {f} no longer exists; remove it from the list")
        elif f not in loose:
            problems.append(f"{UNTRACED}: {f} is traced now; remove it from the list")
        elif not why:
            problems.append(f"{UNTRACED}: {f} needs its reason after a #")
    # the rendering is current
    out = root / REQ / OUT
    if not out.exists() or out.read_text() != render(root):
        problems.append(f"{REQ}/{OUT} is stale: run python3 ops/req.py render")
    return problems


def one_line(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def cell(s):
    return one_line(s).replace("|", "\\|")


def links(xs):
    return ", ".join(f"[{x}](#{x.lower()})" if ID_RE.match(str(x)) else f"`{x}`" for x in xs) if xs else "-"


def render(root=ROOT):
    """REQUIREMENTS.md as text: deterministic (nothing time-dependent), so the checks can compare it."""
    areas, records, _ = load(root)
    reqs = [r for r in records.values() if kind_of(r) == "requirement"]
    tests = tests_in(root)
    L = ["# Requirements of the AI stack", "",
         "Generated by `python3 ops/req.py render` from `requirements/*.yaml`. Do not edit: change the YAML and render.",
         "Method, statuses and rules: [README.md](README.md). Names of the parts: [glossary.md](glossary.md).", ""]
    # summary
    L += ["## Summary", "", "| Area | Requirements | " + " | ".join(s.capitalize() for s in STATUSES) + " |",
          "|---|---|" + "---|" * len(STATUSES)]
    tot = {s: 0 for s in STATUSES}
    for a in areas:
        if a["file"] in SPECIAL and a["prefix"] != "CST":
            continue
        rs = [records[str(i["id"])] for i in a["items"] if str(i.get("id")) in records]
        c = {s: sum(r.get("status") == s for r in rs) for s in STATUSES}
        for s in STATUSES:
            tot[s] += c[s]
        L.append(f"| [{a['area']}](#{a['prefix'].lower()}-{a['area'].lower().replace(' ', '-')}) ({a['prefix']}) | {len(rs)} | "
                 + " | ".join(str(c[s]) for s in STATUSES) + " |")
    L.append(f"| **All** | **{len(reqs)}** | " + " | ".join(f"**{tot[s]}**" for s in STATUSES) + " |")
    claimed = claimed_tests(records)
    L += ["", f"Unit tests claimed by a requirement: {len(tests & claimed)} of {len(tests)}.", ""]
    # findings first: they are what needs attention
    fnds = sorted((r for r in records.values() if kind_of(r) == "finding"), key=lambda r: (r.get("status") != "open", SEVERITIES.index(r.get("severity", "low")) if r.get("severity") in SEVERITIES else 9, r["id"]))
    L += ["## Findings", "", "| Finding | Severity | Status | Owner decision | Affects |", "|---|---|---|---|---|"]
    for f in fnds:
        L.append(f"| [{f['id']}](#{f['id'].lower()}) {cell(f.get('title'))} | {f.get('severity')} | {f.get('status')} | "
                 f"{'yes' if f.get('decision') else '-'} | {links(f.get('affects'))} |")
    L.append("")
    for f in fnds:
        L += [f"### {f['id']}", "", f"**{one_line(f.get('title'))}** ({f.get('severity')} {f.get('kind')}, {f.get('status')})", "",
              one_line(f.get("finding")), "", "- Evidence: " + "; ".join(f"`{one_line(e)}`" for e in f.get("evidence") or []),
              f"- Affects: {links(f.get('affects'))}", f"- Recommendation: {one_line(f.get('recommendation'))}"]
        if f.get("resolved"):
            L.append(f"- Resolved: {one_line(f['resolved'])}")
        L.append("")
    # needs with what refines them
    by_parent = {}
    for r in reqs:
        for p in r.get("parents") or []:
            by_parent.setdefault(p, []).append(r["id"])
    L += ["## Stakeholder needs", "", "| Need | Priority | Refined by |", "|---|---|---|"]
    for r in records.values():
        if kind_of(r) == "need":
            L.append(f"| <a id=\"{r['id'].lower()}\"></a>**{r['id']}** {cell(r.get('title'))}: {cell(r.get('need'))} | {r.get('priority')} | "
                     f"{links(sorted(by_parent.get(r['id'], [])))} |")
    L.append("")
    # requirements per area
    for a in areas:
        if a["file"] in SPECIAL and a["prefix"] != "CST":
            continue
        L += [f"## {a['prefix']} {a['area']}", ""]
        if a["phases"]:
            L += ["| Phase | | Requirements |", "|---|---|---|"]
            for p, name in a["phases"].items():
                L.append(f"| {p} | {cell(name)} | {links([str(i['id']) for i in a['items'] if i.get('phase') == p])} |")
            L.append("")
        grouped, group = any(i.get("group") for i in a["items"]), None
        for i in a["items"]:
            r = records.get(str(i.get("id")))
            if not r:
                continue
            if grouped and r.get("group") != group:
                group = r.get("group")
                L += [f"### {group or 'Other'}", ""]
            ver = r.get("verify") or {}
            L += [f"{'####' if grouped else '###'} {r['id']}", "", f"**{one_line(r.get('title'))}** · {r.get('priority')} · {r.get('type')} · **{r.get('status')}**", "",
                  one_line(r.get("statement")), ""]
            rows = [("Parents", links(r.get("parents"))), ("Sources", links(r.get("sources"))),
                    ("Verified by", f"{ver.get('method')}: {links(ver.get('by'))}" if ver else "-")]
            if "phase" in r:
                rows.append(("Phase", f"{r['phase']} {one_line(a['phases'].get(r['phase'], ''))}".strip()))
            for key, label in (("acceptance", "Acceptance"), ("trace", "Trace"), ("gap", "Gap"), ("rationale", "Rationale"), ("reason", "Reason"),
                               ("superseded_by", "Superseded by"), ("findings", "Findings"), ("refined_by", None)):
                if label and r.get(key):
                    rows.append((label, links(r[key]) if isinstance(r[key], list) or key == "superseded_by" else one_line(r[key])))
            kids = sorted(by_parent.get(r["id"], []))
            if kids:
                rows.append(("Refined by", links(kids)))
            L += [f"- {k}: {v}" for k, v in rows] + [""]
    # decisions
    L += ["## Decisions", "", "| Decision | Date | What | Supersedes |", "|---|---|---|---|"]
    for r in records.values():
        if kind_of(r) == "decision":
            L.append(f"| <a id=\"{r['id'].lower()}\"></a>**{r['id']}** {cell(r.get('title'))} | {r.get('date')} | {cell(r.get('decision'))} | {cell(r.get('supersedes') or '-')} |")
    L.append("")
    # test index: which requirement each test proves
    by_test = {}
    for r in reqs:
        for b in (r.get("verify") or {}).get("by") or []:
            if "::" in str(b):
                by_test.setdefault(str(b), []).append(r["id"])
    L += ["## Test index", "", "| Test | Proves |", "|---|---|"]
    for t in sorted(tests):
        L.append(f"| `{t}` | {links(sorted(by_test.get(t, []))) if t in by_test else 'not claimed yet'} |")
    L.append("")
    return "\n".join(L)


def show(rid, root=ROOT):
    _, records, _ = load(root)
    r = records.get(rid)
    if not r:
        return f"{rid}: no such record"
    out = [yaml.safe_dump({k: v for k, v in r.items() if not k.startswith("_")}, sort_keys=False, allow_unicode=True, width=110).strip()]
    refs = sorted(x["id"] for x in records.values() if x["id"] != rid and rid in (
        (x.get("parents") or []) + (x.get("sources") or []) + (x.get("findings") or []) + (x.get("affects") or []) + [x.get("superseded_by")]))
    out.append(f"\npointed at by: {', '.join(refs) or 'nothing'}")
    return "\n".join(out)


NAMED_RE = re.compile(r"^Requirements?:\s*(.+)$", re.M | re.I)
DOC_ONLY = (".md", ".txt")


def git_out(root, *args):
    import subprocess
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    return p.stdout if p.returncode == 0 else ""


def prove(root=ROOT, base="origin/main", head="HEAD", ids=None):
    """SWM-96: a build names the requirements it implements or changes ("Requirements: SWM-12, ..." in a commit message,
    as AGENTS.md asks), and each named requirement has a test that the build's change runs: the test file is changed by
    the build or covers a file it changed (imports it or names its path). -> (ids, changed files, problems)."""
    files = [f for f in git_out(root, "diff", "--name-only", f"{base}..{head}").split() if f]
    if ids is None:
        ids = sorted({x for line in NAMED_RE.findall(git_out(root, "log", "--format=%B", f"{base}..{head}"))
                      for x in re.findall(r"\b[A-Z]{2,3}-\d{2,3}\b", line)})
    _, records, _ = load(root)
    code = [f for f in files if not f.endswith(DOC_ONLY) and not f.startswith(("docs/", f"{REQ}/"))]
    problems = []
    if code and not ids:
        problems.append("the build changes code but names no requirement: add a line 'Requirements: <IDs>' to its commit message")
    known = tests_in(root)
    sys.path.insert(0, str(Path(root) / "ops"))
    from codegraph import tests_for
    covering = {t for v in tests_for(root, code).values() for t in v}
    for rid in ids:
        r = records.get(rid)
        if not r:
            problems.append(f"{rid}: no such requirement")
            continue
        if kind_of(r) != "requirement":
            continue                                          # a decision or a finding named for context
        by = [str(b) for b in ((r.get("verify") or {}).get("by") or [])] if isinstance(r.get("verify"), dict) else []
        tests = [b for b in by if "::" in b]
        if not tests:
            if not set(by) & set(files):
                problems.append(f"{rid}: names no test in verify.by, and none of the files it is inspected by changed")
            continue
        real = [t for t in tests if t in known]
        if not real:
            problems.append(f"{rid}: none of its tests exists ({', '.join(tests[:3])})")
            continue
        if not [t for t in real if t.split("::")[0] in files or t.split("::")[0] in covering]:
            problems.append(f"{rid}: none of its tests ({', '.join(real[:3])}) is changed by this build or covers a file it changed")
    return ids, files, problems


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "prove":
        base = argv[argv.index("--base") + 1] if "--base" in argv else "origin/main"
        ids = argv[argv.index("--ids") + 1].split(",") if "--ids" in argv else None
        ids, files, problems = prove(ROOT, base, ids=ids)
        print(f"   requirements named: {', '.join(ids) or 'none'} ({len(files)} files changed)")
        for p in problems:
            print(f"   NOT PROVEN: {p}")
        print("   REQUIREMENTS PROVEN" if not problems else f"   {len(problems)} requirement problem{'s' if len(problems) != 1 else ''}")
        return 1 if problems else 0
    if cmd == "render":
        (ROOT / REQ / OUT).write_text(render())
        print(f"wrote {REQ}/{OUT}")
        return 0
    if cmd == "show" and len(argv) > 2:
        print(show(argv[2]))
        return 0
    if cmd == "check":
        problems = check()
        for p in problems:
            print(f"   {p}")
        _, records, _ = load()
        n = sum(kind_of(r) == "requirement" for r in records.values())
        print(f"   {n} requirements, {len(problems)} problem{'s' if len(problems) != 1 else ''}")
        return 1 if problems else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
