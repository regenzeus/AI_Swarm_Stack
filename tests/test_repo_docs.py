"""The repo stays navigable for coding agents: every directory with files has an AGENTS.md (vault-template: README.md),
and the root AGENTS.md map links every one of them."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# data or sub-parts covered by the parent directory's AGENTS.md
COVERED_BY_PARENT = {"eval/results", "eval/qrels", "eval/fixtures", "spec/pilot", "images/mission-control/web/static", "nas/forgejo", "tests/semgrep",
                     "config/hermes/claude-hooks", "config/hermes/plugins/aistack-runtime"}   # config/hermes/AGENTS.md
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache"}


def tracked_dirs():
    try:
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    except Exception:
        files = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and not SKIP_PARTS & set(p.parts)]
    return {str(Path(f).parent).replace("\\", "/") for f in files if "/" in f.replace("\\", "/")}


def test_every_directory_has_a_guide():
    missing = [d for d in sorted(tracked_dirs() - COVERED_BY_PARENT)
               if not (ROOT / d / "AGENTS.md").exists() and not (d == "vault-template" and (ROOT / d / "README.md").exists())]
    assert not missing, f"directories without an AGENTS.md: {missing}"


def test_root_map_links_every_guide():
    root = (ROOT / "AGENTS.md").read_text()
    guides = [str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.rglob("AGENTS.md")
              if p.parent != ROOT and "vault-template" not in p.parts and not SKIP_PARTS & set(p.parts)]
    unlisted = [g for g in guides if f"({g})" not in root]
    assert not unlisted, f"AGENTS.md files missing from the root map: {unlisted}"


def test_claude_entry_point_imports_agents_md():
    assert "@AGENTS.md" in (ROOT / "CLAUDE.md").read_text()


def test_every_shell_script_is_executable():
    """systemd units, make and the runner start scripts directly; a lost executable bit fails silently (203/EXEC)."""
    scripts = [p for p in ROOT.rglob("*.sh") if not SKIP_PARTS & set(p.parts)]
    assert scripts and not [str(p.relative_to(ROOT)) for p in scripts if not os.access(p, os.X_OK)]
