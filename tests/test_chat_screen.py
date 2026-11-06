"""The chat screen (APP-42 to APP-45): back where you left it, new chat in a drawer of chats, a screenshot a tap away, reading first."""
import json
import re
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "images/mission-control/web/static"
JS, CSS = (STATIC / "app.js").read_text(), (STATIC / "app.css").read_text()
V = re.search(r"^async function vChat\(\) \{.*?^\}$", JS, re.M | re.S)[0]


def test_the_chat_tab_reopens_the_chat_you_left_with_its_draft_and_place():
    start = V[:V.index("view.innerHTML")]
    assert '!route.q.get("new") && !route.q.get("prompt") && !route.q.get("share") && (cid = pref(LAST_CHAT, ""))' in start   # only when you asked for nothing else
    assert 'history.replaceState(history.state, "", `#/chat?c=${cid}`)' in start and "if (cur?.id) setPref(LAST_CHAT, cur.id);" in start
    assert "if (cur?.error) {" in start and 'setPref(LAST_CHAT, "")' in start           # a deleted chat: a new one; a lost connection (no answer) keeps it for next time
    assert "setPref(LAST_CHAT, r.chat)" in JS                                           # a chat you just started counts too
    assert "pending = draft.pending || [];" in start and "ta.value = draft.text" in V and "saveDraft(); canSend(); };" in V
    assert "localStorage.removeItem(draftKey())" in V                                   # sent: the draft is gone
    assert "chatScroll[scrollKey] = pane.scrollTop" in V and "pane.scrollTop = chatScroll[scrollKey]" in V
    assert 'location.replace("#/chat?new=1")' in JS                                     # the chat you are in, deleted


def test_new_chat_lives_in_a_drawer_of_chats_and_back_closes_it():
    head = re.search(r'<div class="chathead">.*?\n      </div>', V, re.S)[0]
    assert "New chat" not in head.replace('"New chat"', "") and "data-newchat" not in head and "${ic.compose}" not in head
    aside = re.search(r'<aside class="chatlist".*?</aside>', V, re.S)[0]
    assert aside.index("data-newchat") < aside.index('id="cq"') < aside.index('id="citems"')   # first thing in it
    assert 'history.pushState({ ...(history.state || {}), drawer: 1 }, "")' in JS and '$("#histbtn").onclick = openChatDrawer;' in V
    assert 'window.addEventListener("popstate", () => { if (!history.state?.drawer) chatDrawer(false); });' in JS
    assert "location.replace(to)" in JS                                                 # picking a chat takes the drawer's step, so Back returns to the chat you came from
    phone = CSS[CSS.index("/* the list: a drawer on a phone"):]
    assert "translateX(-104%)" in phone and "body.cdrawer .tabbar { display: none; }" in phone
    assert 'confirm("Delete this chat?")' not in JS and 'prompt("Rename chat"' not in JS and "Tap again to delete" in JS
    assert "delete b.dataset.sure; label.textContent = was; }, 4000);" in JS            # a stray tap later deletes nothing


def test_the_list_groups_chats_by_day_and_gives_each_a_line():
    fn = re.search(r"^function chatGroup\(.*?^\}$", JS, re.M | re.S)[0]
    now = "new Date(2026, 10, 6, 17, 30)"
    js = fn + f"""
const at = (...a) => ({{ updated: new Date(...a).getTime() / 1000 }}), now = {now};
process.stdout.write(JSON.stringify([chatGroup(at(2026, 10, 6, 0, 1), now), chatGroup(at(2026, 10, 5, 23, 59), now), chatGroup(at(2026, 10, 5, 0, 0), now),
  chatGroup(at(2026, 10, 4, 23, 0), now), chatGroup(at(2026, 9, 31, 0, 0), now), chatGroup(at(2026, 9, 30, 23, 0), now), chatGroup({{ ...at(2026, 1, 1), pinned: true }}, now)]));"""
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out == ["Today", "Yesterday", "Yesterday", "Last 7 days", "Last 7 days", "Earlier", "Pinned"]
    assert '${c.last ? ` · ${esc(c.last)}` : ""}' in JS and '"From tests and agents' not in JS.replace("From tests and agents", "", 1)


def test_a_chat_s_last_line_is_plain_and_short():
    import server as S
    msgs = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "**Done:**\n\n# " + "word " * 60}, {"role": "assistant", "note": True, "content": "a note"}]
    last = S.chat_summary({"id": "a", "messages": msgs})["last"]
    assert last.startswith("Done: word word") and last.endswith("word…") and len(last) <= 73 and "*" not in last and "\n" not in last   # the note is not the last thing said
    assert S.chat_summary({"id": "b", "messages": [{"role": "user", "content": "(see attachment)"}]})["last"] == "A picture or a file"
    assert S.chat_summary({"id": "c"})["last"] == ""


def test_a_swipe_opens_and_closes_the_drawer():
    fn = re.search(r"^function chatSwipe\(.*?^\}$", JS, re.M | re.S)[0]
    js = fn + """
process.stdout.write(JSON.stringify([chatSwipe(120, 10, false, 322), chatSwipe(-120, 10, true, 322), chatSwipe(120, 10, true, 322), chatSwipe(-120, 10, false, 322),
  chatSwipe(40, 0, false, 322), chatSwipe(90, 200, false, 322), chatSwipe(-90, -200, true, 322)]));"""
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out == ["open", "close", None, None, None, None, None]                       # right opens, left closes; the other way, a short move and a scroll do nothing
    assert 'e.target.closest("pre, table, .cquick, textarea, input, select, .chatmenu, .madesheet")' in JS   # a code block and the box keep their own swipes
    assert 'if (matchMedia("(max-width: 959px)").matches) bindChatSwipe(' in V and "body.chatmode .chatwrap, .msgs, .citems { touch-action: pan-y; }" in CSS


def test_a_screenshot_is_one_tap_from_the_keyboard():
    row = re.search(r'<div class="cquick" id="cquick">.*?\n      </div>', V, re.S)[0]
    assert 'accept="image/*" multiple' in row and 'capture="environment"' in row and "Screenshot or photo" in row and "navigator.clipboard?.read" in row
    assert V.index('id="cquick"') < V.index('<form class="composer2"')                  # above the box, so above the keyboard
    assert '$("#cquick").onpointerdown = (e) => e.preventDefault();' in V               # the keyboard stays up
    assert '["cfile", "cphoto", "ccam"]' in V and "ta.onpaste =" in V and "cpane.ondrop =" in V
    assert ".chatpane.cfocus .cquick, .chatpane.cempty .cquick { display: flex; }" in CSS
    named = re.search(r"const named = .*$", V, re.M)[0].strip()
    js = "class File { constructor(p, n, o) { this.name = n; this.type = o.type; } }\n" + named + """
process.stdout.write(JSON.stringify([named({ type: "image/png" }).name, named({ type: "image/svg+xml" }, 1).name, named({ name: "a.jpg", type: "image/jpeg" }).name]));"""
    assert json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout) == ["screenshot.png", "screenshot-2.svg", "a.jpg"]


def test_the_chat_puts_reading_first():
    head = re.search(r'<div class="chathead">.*?\n      </div>', V, re.S)[0]
    assert 'id="cmenubtn"' in head and "#/live/" not in head and 'class="chatmenu card"' in V   # Activity, rename, pin and delete are in the menu
    assert 'cd.hidden = !updateReady && liveState() !== "off";' in JS                   # the state, only while something is off
    assert "Working on it" not in JS and "This is Hermes, your assistant" not in V and "What can I do for you?" in V
    assert ".macts { display: none;" in CSS and ".mrow:last-child .macts, .mrow.show .macts { display: flex; }" in CSS and 'row.classList.toggle("show", !was);' in V
    assert '${live ? "Working" : "Worked"} through' in JS
    assert 'id="tobottom"' in V and '$("#tobottom").hidden = atEnd;' in V
    assert "font-size: 16px" in CSS[CSS.index(".composer2 textarea { font-size"):][:60]  # a phone browser zooms into anything smaller
