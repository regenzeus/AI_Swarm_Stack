"""Deterministic vault lint: the mechanical checks from AGENTS.md, without an LLM.

  python3 ops/vault_check.py [--fix] [--json]
Checks: broken [[links]], orphan pages, index.md entries missing or dangling, frontmatter keys, type vs folder,
non-.md files in wiki/, stale pages (last_validated > 180 days), untrusted-source-only pages, product pages
filed under projects/ (projects/ is for the owner's own projects only).
--fix repairs only what is unambiguous: adds missing index entries, drops dangling ones, renames files without
.md. Everything else is reported; the curator's weekly LLM pass handles the judgement calls.
Exit status 1 when errors remain.
"""
import datetime as dt, json, os, re, sys
from pathlib import Path

V = Path(os.environ.get("VAULT", "/srv/vault"))  # /vault inside the hermes container
WIKI = V / "wiki"
FOLDER_TYPE = {"concepts": "concept", "entities": "entity", "projects": "project", "howto": "howto",
               "comparisons": "comparison", "answers": "answer", "sources": "source", "hubs": "hub"}   # hubs: the Librarian's (MEM-08)
REQUIRED = ("title", "type", "sources", "created", "last_validated", "trust")
LINK = re.compile(r"\[\[([^\]|#§]+)(?:[#§][^\]|]*)?(?:\|[^\]]*)?\]\]")
OWN_PROJECT_HINT = re.compile(r"\b(the owner|owner|my|mein)\b", re.I)


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        if re.match(r"^[a-z_]+:", line):
            k, _, v = line.partition(":")
            fm[k] = v.strip()
    return fm


def dedent_keys(path, text):
    """Fix top-level frontmatter keys indented by one space (' type: source'); True if the file changed."""
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return False
    head = re.sub(r"^ (%s):" % "|".join(REQUIRED), lambda k: k.group(1) + ":", m.group(1), flags=re.M)
    if head == m.group(1):
        return False
    path.write_text(f"---\n{head}\n---\n" + text[m.end():], encoding="utf-8")
    return True


def resolve(target):
    t = target.strip().removesuffix(".md")
    for cand in (V / f"{t}.md", V / t, WIKI / f"{t}.md"):
        if cand.exists():
            return cand
    return None


def main():
    fix, as_json = "--fix" in sys.argv, "--json" in sys.argv
    issues, fixed = [], []

    def issue(kind, page, detail, severity="error"):
        issues.append({"kind": kind, "page": page, "detail": detail, "severity": severity})

    for f in WIKI.rglob("*"):
        if f.is_file() and f.suffix != ".md" and f.name != ".gitkeep":
            if fix:
                f.rename(f.with_name(f.name + ".md")); fixed.append(f"renamed {f.relative_to(V)} -> .md")
            else:
                issue("not-markdown", str(f.relative_to(V)), "file without .md extension")

    pages = {str(p.relative_to(V).with_suffix("")): p for p in WIKI.rglob("*.md")}
    inbound = {k: 0 for k in pages}
    today = dt.date.today()
    for key, p in pages.items():
        text = p.read_text(encoding="utf-8")
        if fix and dedent_keys(p, text):
            text = p.read_text(encoding="utf-8"); fixed.append(f"frontmatter indent fixed in {key}")
        fm = frontmatter(text)
        folder = p.relative_to(WIKI).parts[0]
        if fm is None:
            issue("frontmatter", key, "no frontmatter block"); fm = {}
        else:
            for k in REQUIRED:
                if k not in fm:
                    issue("frontmatter", key, f"missing '{k}'")
            want = FOLDER_TYPE.get(folder)
            if want and fm.get("type") and fm["type"] != want:
                issue("wrong-folder", key, f"type '{fm['type']}' in {folder}/ (expects '{want}')")
            try:
                if (today - dt.date.fromisoformat(fm.get("last_validated", ""))).days > 180:
                    issue("stale", key, f"last_validated {fm['last_validated']}", "warning")
            except ValueError:
                if "last_validated" in fm:
                    issue("frontmatter", key, f"bad date last_validated '{fm['last_validated']}'")
            if fm.get("trust") == "untrusted-source":
                issue("untrusted-only", key, "claims rest on web/third-party sources only", "info")
        if folder == "projects" and (WIKI / "entities" / p.name).exists() and not OWN_PROJECT_HINT.search(fm.get("title", "")):
            issue("product-as-project", key, f"same name as entities/{p.stem}; products belong in entities/ only")
        for target in LINK.findall(text):
            r = resolve(target)
            if r is None:
                issue("broken-link", key, f"[[{target}]]")
            else:
                rk = str(r.relative_to(V).with_suffix(""))
                if rk in inbound and rk != key:
                    inbound[rk] += 1

    index = V / "index.md"
    itext = index.read_text(encoding="utf-8")
    listed = {t.strip().removesuffix(".md") for t in LINK.findall(itext)}
    for t in sorted(listed):
        if t.startswith("wiki/") and t not in pages:
            if fix:
                itext = re.sub(rf"^- \[\[{re.escape(t)}\]\].*\n", "", itext, flags=re.M); fixed.append(f"index: dropped {t}")
            else:
                issue("index-dangling", "index.md", f"[[{t}]] has no page")
        elif t in inbound:
            inbound[t] += 1
    heading = {"concepts": "## Concepts", "entities": "## Entities", "projects": "## Projects",
               "sources": "## Sources", "howto": "## How-tos", "comparisons": "## Comparisons", "answers": "## Answers", "hubs": "## Hubs"}
    for key, p in sorted(pages.items()):
        if key not in listed:
            if fix:
                fm = frontmatter(p.read_text(encoding="utf-8")) or {}
                h = heading.get(p.relative_to(WIKI).parts[0], "## Other")
                entry = f"- [[{key}]] — {fm.get('title', p.stem)}\n"
                if h not in itext:
                    itext = itext.rstrip("\n") + f"\n\n{h}\n"
                itext = re.sub(rf"({re.escape(h)}\n)", rf"\1{entry}", itext, count=1)
                fixed.append(f"index: added {key}"); inbound[key] += 1
            else:
                issue("index-missing", key, "not listed in index.md")
    if fix:
        index.write_text(itext, encoding="utf-8")
    for key, n in inbound.items():
        if n == 0:
            issue("orphan", key, "no page links here", "warning")

    errors = [i for i in issues if i["severity"] == "error"]
    if as_json:
        print(json.dumps({"pages": len(pages), "fixed": fixed, "issues": issues}, indent=1))
    else:
        print(f"vault check: {len(pages)} pages, {len(errors)} errors, "
              f"{sum(i['severity'] == 'warning' for i in issues)} warnings, {len(fixed)} fixed")
        for i in issues:
            if i["severity"] != "info":
                print(f"  {i['severity']:7} {i['kind']:18} {i['page']}: {i['detail']}")
        info = [i for i in issues if i["severity"] == "info"]
        if info:
            print(f"  info    {len(info)} pages rest on web/third-party sources only (trust: untrusted-source)")
        for f in fixed:
            print(f"  fixed   {f}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
