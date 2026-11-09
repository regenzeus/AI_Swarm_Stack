"""The scout's web search (RES-02, FND-10). Once Hermes has its own dependency environment (/opt/data/installs/...),
a launch uses only that environment and drops the image's .venv, so ddgs installed by the Dockerfile alone is not
seen: configure-scout.sh installs Hermes' own ddgs extra into the environment Hermes runs from."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_scout_s_search_package_is_in_the_environment_hermes_runs_from():
    sh = (ROOT / "config/hermes/configure-scout.sh").read_text()
    assert "c web.search_backend ddgs" in sh
    assert "hermes pm install --extra ddgs" in sh                                         # into Hermes' own environment
    assert sh.index("hermes pm install --extra ddgs") < sh.index("platforms.api_server.enabled")
    assert "ddgs==9.16.0" in (ROOT / "images/hermes/Dockerfile").read_text()             # before Hermes has one
    deploy = (ROOT / "ops/deploy.py").read_text()
    assert 'f == "config/hermes/configure-scout.sh"' in deploy and '"restart", "aistack-hermes-1"' in deploy
