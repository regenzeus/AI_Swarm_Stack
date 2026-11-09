"""The Windows worker's rules (GEN-11, DEC-45, docs/PLATFORM.md §6), in one place: what a job kind is, when it is
approved, how a request's values and patch are checked, and how a step's arguments are filled in.

ops/fakeworker.py runs jobs by these rules over the worker's folders, so the stack's tests never need Windows;
ops/windows/worker.ps1 is the same rules on Windows, and both pass tests/test_winworker.py's protocol cases. Stdlib only.

A job kind (a JSON file of jobs.d, written by the owner on Windows; the stack can only name one):
  kind          its name, [a-z][a-z0-9.-]*
  about         one sentence
  params        {name: {type: enum|hex40|int|name|file|bool, ...}}: enum has values, int has min and max, name has
                from (the folder of the worker whose entries are the names), file has max_kb
  patch_paths   {allow: [glob], deny: [glob]} when a file parameter named patch is a patch
  steps         [[argument, ...], ...]: each argument a literal or holding {param}, {scratch}, {repos}, {patch}, {out}
  collect       [glob, ...] of files under the scratch folder that come back as artifacts
  minutes       its time limit; needs_gb the memory Windows must have free; lock one job at a time per lock name
  retry         true when a job lost with its worker may run again
A kind runs only when approved.json holds its name with the SHA-256 of its file's bytes."""
import fnmatch
import hashlib
import json
import re
from pathlib import Path

KIND = re.compile(r"[a-z][a-z0-9.-]{0,63}")
ID = re.compile(r"[a-f0-9]{12}")
PARAM = re.compile(r"[a-z][a-z0-9_]{0,31}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
TYPES = {"enum", "hex40", "int", "name", "file", "bool"}
BUILTINS = {"scratch", "repos", "patch", "out"}
FIELDS = {"kind", "about", "params", "patch_paths", "steps", "collect", "minutes", "needs_gb", "lock", "retry", "probe"}
# limit: refuses, a request's values are short scalars: a value past this is no commit, name or number (GEN-11)
VALUE_MAX = 200
# limit: refuses, a job kind's time limit: a day at most; its own minutes stop it sooner
MINUTES_MAX = 24 * 60


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def kind_problems(k):
    """-> what is wrong with one job kind's definition; [] when it is whole."""
    out = []
    odd = sorted(set(k) - FIELDS)
    if odd:
        out.append(f"fields nobody reads: {', '.join(odd)}")
    if not KIND.fullmatch(str(k.get("kind") or "")):
        out.append("kind: a name of a-z, 0-9, . and -")
    for name, p in (k.get("params") or {}).items():
        if not PARAM.fullmatch(name) or name in BUILTINS - {"patch"}:
            out.append(f"parameter {name!r}: a-z, 0-9 and _, and not {', '.join(sorted(BUILTINS - {'patch'}))}")
        t = (p or {}).get("type")
        if name == "patch" and t != "file":
            out.append("parameter patch: the patch is a file parameter ({patch} is its path on the worker)")
        if t not in TYPES:
            out.append(f"parameter {name}: type {t!r} is none of {', '.join(sorted(TYPES))}")
        elif t == "enum" and not (isinstance(p.get("values"), list) and p["values"] and all(NAME.fullmatch(str(v)) for v in p["values"])):
            out.append(f"parameter {name}: an enum needs values, each a plain name")
        elif t == "int" and not all(isinstance(p.get(x), int) for x in ("min", "max")):
            out.append(f"parameter {name}: an int needs min and max")
        elif t == "name" and not NAME.fullmatch(str(p.get("from") or "")):
            out.append(f"parameter {name}: a name needs from (the worker's folder whose entries are the names)")
        elif t == "file" and not isinstance(p.get("max_kb"), int):
            out.append(f"parameter {name}: a file needs max_kb")
    steps = k.get("steps")
    if not (isinstance(steps, list) and steps and all(isinstance(s, list) and s and all(isinstance(a, str) for a in s) for s in steps)):
        out.append("steps: a list of argument lists, each a list of strings")
    else:
        known = set(k.get("params") or {}) | BUILTINS
        for s in steps:
            for a in s:
                for ref in re.findall(r"\{([^{}]*)\}", a):
                    if ref not in known:
                        out.append(f"step {s[0]}: {{{ref}}} is no parameter of this kind")
    if "patch" in (k.get("params") or {}) and not isinstance(k.get("patch_paths"), dict):
        out.append("a kind with a patch says which paths it may change (patch_paths: allow, deny)")
    m = k.get("minutes")
    if not (isinstance(m, int) and 0 < m <= MINUTES_MAX):
        out.append(f"minutes: its time limit, 1 to {MINUTES_MAX}")
    return out


def load_kinds(jobs_dir):
    """-> {kind: (definition, sha256, problems)} of every JSON file in jobs.d (a file whose name is not its kind is a problem)."""
    out = {}
    for f in sorted(Path(jobs_dir).glob("*.json")) if Path(jobs_dir).is_dir() else []:
        try:
            k = json.loads(f.read_text(encoding="utf-8-sig"))
            probs = kind_problems(k) + ([] if k.get("kind") == f.stem else [f"the file is {f.name}, the kind {k.get('kind')!r}"])
        except ValueError as e:
            k, probs = {"kind": f.stem}, [f"not JSON: {e}"]
        out[f.stem] = (k, digest(f), probs)
    return out


def approved(kind, kinds, approvals):
    """-> None when the kind may run, else why not (unknown, wrong, not approved, changed since its approval)."""
    if kind not in kinds:
        return f"no job kind {kind!r} is declared on Windows"
    k, sha, probs = kinds[kind]
    if probs:
        return f"the job kind {kind} is not valid: {'; '.join(probs)}"
    if kind not in approvals:
        return f"the job kind {kind} is not approved: the owner runs worker-approve.ps1 {kind} on Windows"
    if approvals[kind] != sha:
        return f"the job kind {kind} changed since its approval: the owner approves it again (worker-approve.ps1 {kind})"
    return None


def check_values(k, values, request_dir, names):
    """-> (values ready to fill in, None) or (None, why): each value by its parameter's type. names: {from: set of names}."""
    params = k.get("params") or {}
    odd = sorted(set(values) - set(params))
    if odd:
        return None, f"values for no parameter: {', '.join(odd)}"
    out = {}
    for name, p in params.items():
        if name not in values:
            return None, f"no value for {name}"
        v, t = values[name], p["type"]
        if isinstance(v, str) and len(v) > VALUE_MAX:
            return None, f"{name} is {len(v)} characters; {VALUE_MAX} at most"
        if t == "enum":
            if v not in p["values"]:
                return None, f"{name} is {v!r}: one of {', '.join(map(str, p['values']))}"
        elif t == "hex40":
            if not (isinstance(v, str) and re.fullmatch(r"[0-9a-f]{40}", v)):
                return None, f"{name}: a commit, 40 lowercase hex characters"
        elif t == "int":
            if not (isinstance(v, int) and not isinstance(v, bool) and p["min"] <= v <= p["max"]):
                return None, f"{name}: a whole number from {p['min']} to {p['max']}"
            v = str(v)
        elif t == "bool":
            if not isinstance(v, bool):
                return None, f"{name}: true or false"
            v = "true" if v else "false"
        elif t == "name":
            if not (isinstance(v, str) and NAME.fullmatch(v) and v in names.get(p["from"], set())):
                return None, f"{name} is {v!r}: one of the names in the worker's {p['from']} ({', '.join(sorted(names.get(p['from'], set()))) or 'none'})"
        elif t == "file":
            if not (isinstance(v, str) and NAME.fullmatch(v)):
                return None, f"{name}: a file name of the request's own folder"
            f = Path(request_dir) / v
            if not f.is_file() or f.is_symlink():
                return None, f"{name}: {v} is not a file of the request"
            if f.stat().st_size > p["max_kb"] * 1024:
                return None, f"{name}: {v} is {f.stat().st_size // 1024} KB; {p['max_kb']} KB at most"
        out[name] = v
    return out, None


def _glob(pattern):
    """A path glob: ** any depth (also none), * one name's characters, ? one character."""
    rx, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            rx, i = rx + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            rx, i = rx + ".*", i + 2
        elif pattern[i] == "*":
            rx, i = rx + "[^/]*", i + 1
        elif pattern[i] == "?":
            rx, i = rx + "[^/]", i + 1
        else:
            rx, i = rx + re.escape(pattern[i]), i + 1
    return re.compile(rx + r"\Z")


def patch_paths(text):
    """-> (every path a unified diff touches, None) or (None, why it is refused): a binary patch, a symbolic link, a
    submodule, a mode change to one, an absolute path, a backslash or .. refuse it."""
    paths = set()
    for ln in text.splitlines():
        if ln.startswith(("GIT binary patch", "Binary files ")):
            return None, "a binary patch"
        if re.match(r"^(?:new file mode|deleted file mode|old mode|new mode|index \S+) (?:120000|160000)\s*$", ln):
            return None, "a symbolic link or a submodule"
        if ln.startswith("Subproject commit"):
            return None, "a submodule"
        m = re.match(r"^diff --git a/(\S+) b/(\S+)$", ln) or re.match(r"^(?:---|\+\+\+) [ab]/(\S+)", ln) or \
            re.match(r"^(?:rename|copy) (?:from|to) (\S+)$", ln)
        if m:
            for p in m.groups():
                if p == "/dev/null":
                    continue
                if p.startswith("/") or "\\" in p or ".." in p.split("/") or re.match(r"^[A-Za-z]:", p) or not p:
                    return None, f"the path {p!r} leaves the repository"
                paths.add(p)
        elif ln.startswith(("--- /", "+++ /")) and not ln.startswith(("--- /dev/null", "+++ /dev/null")):
            return None, "a path outside the repository"
    if not paths:
        return None, "no file in the patch"
    return sorted(paths), None


def check_patch(k, text):
    """-> None when the patch may be applied under the kind's patch_paths, else why not."""
    paths, why = patch_paths(text)
    if why:
        return f"the patch is refused: {why}"
    rule = k.get("patch_paths") or {}
    allow = [_glob(g) for g in rule.get("allow") or []]
    deny = [_glob(g) for g in rule.get("deny") or []]
    for p in paths:
        if any(d.match(p) for d in deny):
            return f"the patch changes {p}, which this job kind does not let a patch change"
        if not any(a.match(p) for a in allow):
            return f"the patch changes {p}, outside the paths this job kind allows ({', '.join(rule.get('allow') or [])})"
    return None


def fill(step, values, builtins):
    """One step's arguments with the values in; each value goes into its own argument, never through a shell."""
    allv = {**values, **builtins}
    return [re.sub(r"\{([a-z_]+)\}", lambda m: str(allv[m.group(1)]), a) for a in step]


def collect_matches(scratch, patterns):
    """The files under scratch that the kind's collect patterns name (no link, nothing outside)."""
    out = []
    root = Path(scratch).resolve()
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root).as_posix()
        if f.is_file() and not f.is_symlink() and any(fnmatch.fnmatch(rel, g.replace("\\", "/")) or _glob(g.replace("\\", "/")).match(rel) for g in patterns):
            out.append(f)
    return out
