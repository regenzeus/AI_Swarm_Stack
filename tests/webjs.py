"""The app's script as one text: its parts joined in the order index.html loads them (PLT-25 split app.js)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "images/mission-control/web"
STATIC = WEB / "static"
APP_PARTS = tuple(s.split("/")[-1] for s in re.findall(r'<script src="/static/(app[^"]*\.js)"', (WEB / "index.html").read_text()))


def app_js():
    return "".join((STATIC / p).read_text() for p in APP_PARTS)
