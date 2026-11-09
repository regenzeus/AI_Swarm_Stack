"""Convert mail (mbox/.eml) and chat exports (ChatGPT, Claude) into one markdown file per item.

Runs offline in the tools container:
  docker run --rm --network none -v /srv/win-exports:/in:ro -v /srv/ai/bulk:/out aistack/tools:1 \
    python /app/bulk_convert.py
Idempotent: an item whose output file exists is skipped. Bulk items are search-only (qmd), never compiled
into the wiki. Each file starts with a heading line carrying sender/date/subject so chunks stay self-describing.
"""
import email, email.policy, hashlib, html, json, mailbox, re, sys, tempfile, zipfile
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

IN, OUT = Path("/in"), Path("/out")
MAX_BODY = 20000       # limit: drops, a bulk file's body past this (search chunks); its marker says so, the whole stays in the export
counts = {"mail": 0, "mail_skipped": 0, "chatgpt": 0, "claude": 0}


def slug(s, n=50):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "untitled").lower()).strip("-")
    return (s or "untitled")[:n]


def yml(v):
    return json.dumps(str(v), ensure_ascii=False)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []
    def handle_data(self, d): self.parts.append(d)
    def handle_starttag(self, tag, a):
        if tag in ("br", "p", "div", "li", "tr"): self.parts.append("\n")


def html_to_text(h):
    p = _Text(); p.feed(h); return html.unescape("".join(p.parts))


QUOTE_START = re.compile(r"^(On .+ wrote:|Am .+ schrieb .+:|-----Original Message-----|-----Ursprüngliche Nachricht-----)\s*$")
QUOTE_FROM = re.compile(r"^(Von|From): .+$")
QUOTE_NEXT = re.compile(r"^(Sent|Gesendet|Date|Datum|To|An|Subject|Betreff|Cc): ", re.I)


def quote_header(lines, i):
    """A quoted reply starts here: a reply line, or a From:/Von: line followed by the quote's own header lines (Sent:,
    To:, ...). A "From: ..." line in the mail's own text is text (review IMG-R9: the rest of a mail was dropped there)."""
    line = lines[i].strip()
    if QUOTE_START.match(line):
        return True
    return bool(QUOTE_FROM.match(line)) and any(QUOTE_NEXT.match(n.strip()) for n in lines[i + 1:i + 4])


def cut(text, n, where):
    """The first n characters and a marker saying how much is missing and where the whole text is (DEC-27)."""
    return text if len(text) <= n else text[:n] + f"\n\n[… {len(text) - n:,} more characters cut: the whole is in {where}]"


def clean_body(text, where="the export"):
    out, lines = [], text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "--":            # signature delimiter
            break
        if quote_header(lines, i):          # start of quoted reply
            break
        if line.startswith(">"):
            continue
        out.append(line.rstrip())
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return cut(body, MAX_BODY, where)  # cap: store


def body_of(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:
        content = part.get_payload(decode=True) or b""
        content = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
    return html_to_text(content) if part.get_content_type() == "text/html" else content


def write_mail(msg, origin):
    mid = (msg.get("Message-ID") or "").strip()
    key = hashlib.sha1((mid or msg.as_string()[:4000]).encode("utf-8", "replace")).hexdigest()[:16]  # cap: id (a key; the mail is whole)
    try:
        dt = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc)
    except Exception:
        dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
    dest = OUT / "mail" / f"{dt:%Y}" / f"{dt:%m}" / f"{dt:%Y-%m-%d}-{slug(msg.get('Subject'), 40)}-{key}.md"
    if dest.exists():
        counts["mail_skipped"] += 1; return
    refs = (msg.get("References") or msg.get("In-Reply-To") or mid).split()
    thread = refs[0] if refs else mid
    sender = ", ".join(f"{n} <{a}>" if n else a for n, a in getaddresses([msg.get("From", "")]))
    to = ", ".join(a for _, a in getaddresses(msg.get_all("To", []) + msg.get_all("Cc", [])))
    subject = msg.get("Subject", "(no subject)")
    body = clean_body(body_of(msg), origin)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        f"---\ntype: mail\nsource: {yml(origin)}\nmessage_id: {yml(mid)}\nthread_id: {yml(thread)}\n"
        f"from: {yml(sender)}\nto: {yml(to)}\ndate: {dt:%Y-%m-%dT%H:%M:%SZ}\nsubject: {yml(subject)}\n"
        f"qmd:\n  metadata:\n    type: mail\n    tier: t1\n    date: {dt:%Y-%m-%d}\n---\n\n"
        f"# {subject}\n\nFrom {sender} · {dt:%Y-%m-%d %H:%M} UTC · to {to}\n\n{body}\n",
        encoding="utf-8")
    counts["mail"] += 1


def convert_mail():
    for f in sorted((IN / "mail").rglob("*")):
        if f.suffix.lower() == ".mbox" or f.name.lower().endswith(".mbox"):
            for msg in mailbox.mbox(str(f), factory=lambda fp: email.message_from_binary_file(fp, policy=email.policy.default)):
                try: write_mail(msg, f"mail/{f.name}")
                except Exception as e: print(f"mail skipped ({e.__class__.__name__}) in {f.name}", file=sys.stderr)
        elif f.suffix.lower() == ".eml":
            with f.open("rb") as fp:
                write_mail(email.message_from_binary_file(fp, policy=email.policy.default), f"mail/{f.name}")


def write_chat(source, cid, title, created, turns):
    dt = datetime.fromtimestamp(created or 0, tz=timezone.utc)
    dest = OUT / "chats" / source / f"{dt:%Y-%m-%d}-{slug(title, 40)}-{str(cid)[:8]}.md"
    if dest.exists() or not turns:
        return
    lines = [f"---\ntype: chat\nsource: {source}\nconversation_id: {yml(cid)}\ntitle: {yml(title)}\ndate: {dt:%Y-%m-%d}\n"
             f"qmd:\n  metadata:\n    type: chat\n    tier: t1\n    source: {source}\n    date: {dt:%Y-%m-%d}\n---\n",
             f"# {title}\n", f"{source} conversation · {dt:%Y-%m-%d}\n"]
    n = 0
    for role, text in turns:
        if role == "user":
            n += 1; lines.append(f"\n## Exchange {n} · {title}\n")
        lines.append(f"**{'You' if role == 'user' else 'Assistant'}:** {cut(text.strip(), MAX_BODY, source + ' export')}\n")  # cap: store
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    counts[source] += 1


def convert_chatgpt():
    for f in (IN / "chatgpt").rglob("conversations.json"):
        for conv in json.loads(f.read_text(encoding="utf-8")):
            mapping, node, chain = conv.get("mapping", {}), conv.get("current_node"), []
            while node and node in mapping:              # walk the active branch back to the root
                m = mapping[node].get("message")
                if m and m.get("author", {}).get("role") in ("user", "assistant"):
                    parts = (m.get("content") or {}).get("parts") or []
                    text = "\n".join(p for p in parts if isinstance(p, str)).strip()
                    if text: chain.append((m["author"]["role"], text))
                node = mapping[node].get("parent")
            write_chat("chatgpt", conv.get("id") or conv.get("conversation_id"), conv.get("title") or "Untitled",
                       conv.get("create_time"), list(reversed(chain)))


def convert_claude():
    for f in (IN / "claude").rglob("conversations.json"):
        for conv in json.loads(f.read_text(encoding="utf-8")):
            turns = [("user" if m.get("sender") == "human" else "assistant", m.get("text") or "")
                     for m in conv.get("chat_messages", []) if (m.get("text") or "").strip()]
            ts = conv.get("created_at")
            created = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else 0
            write_chat("claude", conv.get("uuid"), conv.get("name") or "Untitled", created, turns)


def unzip_exports():
    """Exports may arrive as zips. Extract only the files we read (mbox, eml, conversations.json) to a temp
    tree, since /in is read-only, and return it as an extra input root."""
    tmp = Path(tempfile.mkdtemp(prefix="exports-"))
    for z in IN.rglob("*.zip"):
        kind = z.relative_to(IN).parts[0]
        with zipfile.ZipFile(z) as zf:
            for m in zf.namelist():
                low = m.lower()
                if low.endswith((".mbox", ".eml")) or low.endswith("conversations.json"):
                    target = tmp / kind / z.stem / Path(m).name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(m) as src, target.open("wb") as dst:
                        while chunk := src.read(1 << 20):
                            dst.write(chunk)
    return tmp


if __name__ == "__main__":
    roots = [IN, unzip_exports()]
    for root in roots:
        IN = root
        for fn in (convert_mail, convert_chatgpt, convert_claude):
            if (IN / fn.__name__.split("_")[1]).exists(): fn()
    print(json.dumps(counts))
