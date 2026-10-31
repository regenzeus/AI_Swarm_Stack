"""Which pinned components have a newer release? Read-only: changes nothing, just reports.
  python3 ops/upgrade_check.py [--notify]     (monthly timer sends the list to Telegram)
How to upgrade one: see UPGRADE.md."""
import json, re, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env = dict(l.split("=", 1) for l in (ROOT / "versions.env").read_text().splitlines() if "=" in l and not l.startswith("#"))


def grab(path, pattern):
    return re.search(pattern, (ROOT / path).read_text()).group(1)


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
]


def norm(v):
    return v.lstrip("v").replace("version-", "")


rows, newer = [], []
for name, pinned, latest in PINNED:
    try:
        l = latest()
    except Exception as e:
        l = f"? ({type(e).__name__})"
    same = norm(l) == norm(pinned) or norm(l).startswith(norm(pinned))
    rows.append(f"{'  ' if same or l.startswith('?') else '* '}{name:20} {pinned:14} -> {l}")
    if not same and not l.startswith("?"):
        newer.append(f"{name} {pinned} -> {l}")
print("\n".join(rows))
if "--notify" in sys.argv and newer:
    msg = ("Monthly upgrade check: newer releases for " + "; ".join(newer)
           + ". Nothing was changed. To upgrade one: ask Claude, or follow UPGRADE.md in ai-stack.")
    sys.path.insert(0, str(ROOT / "ops"))
    import notify as N                            # the one notification path (OBS-16)
    N.send(msg, "system")
