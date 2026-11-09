"""Which pinned components have a newer release? Read-only: changes nothing, just reports.
  python3 ops/upgrade_check.py [--notify]     (monthly timer sends the list to Telegram)
How to upgrade one: see UPGRADE.md."""
import json, re, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env = dict(l.split("=", 1) for l in (ROOT / "versions.env").read_text().splitlines() if "=" in l and not l.startswith("#"))


def grab(path, pattern):
    """The pinned version in a file, or "?" when the file or the pattern is gone (a row says so; the check goes on)."""
    try:
        return re.search(pattern, (ROOT / path).read_text(), re.M).group(1)
    except (OSError, AttributeError):
        return f"? (not in {path})"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ai-stack-upgrade-check", "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def gh(repo):
    return get(f"https://api.github.com/repos/{repo}/releases/latest")["tag_name"]


PINNED = [  # name, pinned, latest()
    ("LiteLLM", env["LITELLM_IMAGE"].split(":")[1], lambda: gh("BerriAI/litellm")),
    ("Hermes Agent", grab("images/hermes/Dockerfile", r"hermes-agent:(v[\d.]+)"), lambda: gh("NousResearch/hermes-agent")),
    ("Open WebUI", env["OPENWEBUI_IMAGE"].split(":")[1], lambda: gh("open-webui/open-webui")),
    ("Ollama", env["OLLAMA_IMAGE"].split(":")[1], lambda: gh("ollama/ollama")),
    ("Phoenix", env["PHOENIX_IMAGE"].split("version-")[1],   # monorepo: skip the evals/otel package releases
     lambda: next(r["tag_name"].removeprefix("arize-phoenix-") for r in
                  get("https://api.github.com/repos/Arize-ai/phoenix/releases?per_page=50")
                  if r["tag_name"].startswith("arize-phoenix-v"))),
    ("sops", env["SOPS_VERSION"], lambda: gh("getsops/sops")),
    ("Forgejo", env["FORGEJO_IMAGE"].split(":")[1].split("-")[0],
     lambda: get("https://codeberg.org/api/v1/repos/forgejo/forgejo/releases/latest")["tag_name"]),
    ("OpenCode", grab("images/opencode/Dockerfile", r"opencode-ai@([\d.]+)"),
     lambda: get("https://registry.npmjs.org/opencode-ai/latest")["version"]),
    ("qmd", grab("images/qmd/Dockerfile", r"QMD_VERSION=([\d.]+)"),
     lambda: get("https://registry.npmjs.org/@tobilu/qmd/latest")["version"]),
    ("Graphify", grab("images/graphify/Dockerfile", r"graphifyy\[[^\]]*\]==([\d.]+)"),
     lambda: get("https://pypi.org/pypi/graphifyy/json")["info"]["version"]),
    ("Understand Anything", grab("images/opencode/Dockerfile", r"UA_REF=(\w+)"),
     lambda: get("https://api.github.com/repos/Lum1104/Understand-Anything/commits/main")["sha"][:7]),
    ("repowise", grab("images/repointel/requirements.lock", r"^repowise==([\d.]+)"),
     lambda: get("https://pypi.org/pypi/repowise/json")["info"]["version"]),
    ("CodeLore", grab("images/repointel/Dockerfile", r"CODELORE=v([\d.]+)"), lambda: gh("emrecdr/codelore")),
    # review OPS-R10: these were pinned and never checked
    ("Home Assistant", grab("nas/homeassistant/compose.yaml", r"home-assistant:([\w.]+)@"), lambda: gh("home-assistant/core")),
    ("Claude Code", grab("images/builder/Dockerfile", r"@anthropic-ai/claude-code@([\d.]+)"),
     lambda: get("https://registry.npmjs.org/@anthropic-ai/claude-code/latest")["version"]),
    ("Hindsight", grab("compose/apps.yaml", r"hindsight-api:([\d.]+)"), lambda: gh("vectorize-io/hindsight")),
    ("price watch", grab("versions.env", r"^PRICEWATCH_IMAGE=\S+:([\d.]+)@"), lambda: gh("dgtlmoon/changedetection.io")),
    ("Caddy (the gate)", grab("versions.env", r"^GATE_IMAGE=caddy:([\d.]+)"), lambda: gh("caddyserver/caddy")),
    ("Forgejo runner", grab("images/ci-runner/Dockerfile", r"forgejo/runner:([\d.]+)"),
     lambda: get("https://code.forgejo.org/api/v1/repos/forgejo/runner/releases/latest")["tag_name"]),
]


def norm(v):
    return v.lstrip("v").replace("version-", "")


def check(pinned_list=None):
    """-> (rows, newer, unknown): every component's row; the ones with a newer release; the ones that could not be checked."""
    rows, newer, unknown = [], [], []
    for name, pinned, latest in (PINNED if pinned_list is None else pinned_list):
        try:
            l = latest()
        except Exception as e:
            l = f"? ({type(e).__name__})"
        if pinned.startswith("?") or l.startswith("?"):  # a failed lookup is said, never taken for "no news" (QA-26)
            rows.append(f"? {name:20} {pinned:14} -> {l}")
            unknown.append(name)
            continue
        same = norm(l) == norm(pinned) or norm(l).startswith(norm(pinned))
        rows.append(f"{'  ' if same else '* '}{name:20} {pinned:14} -> {l}")
        if not same:
            newer.append(f"{name} {pinned} -> {l}")
    try:                                          # TSK-27: the list prices come from the pinned gateway's own table
        pv = json.loads((ROOT / "config/prices.json").read_text()).get("litellm") or "?"
        lite = norm(env["LITELLM_IMAGE"].split(":")[1]).split("-")[0]
        if not lite.startswith(norm(pv)):
            rows.append(f"* {'list prices':20} {pv:14} -> {lite} (run python3 ops/prices.py refresh)")
            newer.append(f"the list prices (from LiteLLM {pv}; the gateway runs {lite}: python3 ops/prices.py refresh)")
    except (OSError, ValueError, KeyError):
        rows.append("? list prices: config/prices.json not read")
        unknown.append("the list prices")
    return rows, newer, unknown


def message(newer, unknown):
    """The month's Telegram message, or None when there is nothing to say."""
    parts = []
    if newer:
        parts.append("newer releases for " + "; ".join(newer))
    if unknown:
        parts.append("could not check " + ", ".join(unknown))
    if not parts:
        return None
    return ("Monthly upgrade check: " + ". And: ".join(parts)
            + ". Nothing was changed. To upgrade one: ask Claude, or follow UPGRADE.md in ai-stack.")


if __name__ == "__main__":
    rows, newer, unknown = check()
    print("\n".join(rows))
    if "--notify" in sys.argv and (msg := message(newer, unknown)):
        sys.path.insert(0, str(ROOT / "ops"))
        import notify as N                        # the one notification path (OBS-16)
        N.send(msg, "system", by="stack")
