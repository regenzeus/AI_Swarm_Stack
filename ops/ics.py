"""A calendar in iCalendar form (RFC 5545), read only (TSK-33): its events and their repeats in a window of time.

What it reads: VEVENT with UID, SUMMARY, LOCATION, DESCRIPTION, DTSTART, DTEND or DURATION, RRULE (FREQ DAILY, WEEKLY,
MONTHLY or YEARLY, with INTERVAL, COUNT, UNTIL and, for WEEKLY, BYDAY), EXDATE, and a moved occurrence (RECURRENCE-ID)
in place of the one it moves. A time is UTC (…Z), in a named zone (TZID, from Python's zone database), floating (local
time) or a whole day. What it does not read is skipped, never guessed: other RRULE parts (BYSETPOS, BYMONTHDAY lists …),
VTODO, VJOURNAL.
"""
import datetime as dt
import re
from zoneinfo import ZoneInfo

DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
MAX_REPEATS = 2000                                # cap: list (occurrences looked at per event: years of a weekly meeting)


def unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def unescape(v):
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def when(value, params, local):
    """A DTSTART-like value -> an aware datetime (a whole day starts at local midnight)."""
    v = value.strip()
    if re.fullmatch(r"\d{8}", v) or params.get("VALUE") == "DATE":
        return dt.datetime.strptime(v[:8], "%Y%m%d").replace(tzinfo=local)
    t = dt.datetime.strptime(v.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if v.endswith("Z"):
        return t.replace(tzinfo=dt.timezone.utc)
    try:
        return t.replace(tzinfo=ZoneInfo(params["TZID"])) if params.get("TZID") else t.replace(tzinfo=local)
    except (KeyError, ValueError):                # a zone Python does not know (Outlook names): local time
        return t.replace(tzinfo=local)


def duration(v):
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return dt.timedelta(0)
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s) * (-1 if m.group(1) == "-" else 1)


def parse(text, local=None):
    """The calendar's events: [{uid, summary, location, description, start, end, rrule, exdates, recurrence_id}]."""
    local = local or dt.datetime.now().astimezone().tzinfo
    out, ev = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            ev = {"exdates": set()}
            continue
        if line == "END:VEVENT" and ev is not None:
            if ev.get("start"):
                ev.setdefault("end", ev["start"] + ev.pop("duration", dt.timedelta(0)))
                out.append(ev)
            ev = None
            continue
        if ev is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, *ps = head.split(";")
        params = dict(p.split("=", 1) for p in ps if "=" in p)
        name = name.upper()
        if name in ("UID", "SUMMARY", "LOCATION", "DESCRIPTION"):
            ev[name.lower()] = unescape(value)
        elif name == "DTSTART":
            ev["start"] = when(value, params, local)
        elif name == "DTEND":
            ev["end"] = when(value, params, local)
        elif name == "DURATION":
            ev["duration"] = duration(value)
        elif name == "RRULE":
            ev["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
        elif name == "EXDATE":
            ev["exdates"] |= {when(v, params, local) for v in value.split(",")}
        elif name == "RECURRENCE-ID":
            ev["recurrence_id"] = when(value, params, local)
    return out


def _add_months(t, n):
    y, m = divmod(t.month - 1 + n, 12)
    try:
        return t.replace(year=t.year + y, month=m + 1)
    except ValueError:                            # the 31st in a shorter month: that month has no such day
        return None


def starts(ev):
    """Every start of an event, in order (its repeats, at most MAX_REPEATS)."""
    s, r = ev["start"], ev.get("rrule")
    if not r:
        yield s
        return
    freq, step = r.get("FREQ"), int(r.get("INTERVAL") or 1)
    count = int(r["COUNT"]) if r.get("COUNT", "").isdigit() else None
    until = when(r["UNTIL"], {}, s.tzinfo) if r.get("UNTIL") else None
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY") or any(k in r for k in ("BYSETPOS", "BYMONTHDAY", "BYMONTH", "BYYEARDAY", "BYWEEKNO")):
        yield s                                   # a rule it does not read: the first time only, never a guess
        return
    days = sorted(DAYS[d[-2:]] for d in r.get("BYDAY", "").split(",") if d[-2:] in DAYS) if freq == "WEEKLY" else []
    n = made = 0
    while made < MAX_REPEATS:
        if freq == "DAILY":
            batch = [s + dt.timedelta(days=n * step)]
        elif freq == "WEEKLY":
            week = s - dt.timedelta(days=s.weekday()) + dt.timedelta(weeks=n * step)
            batch = [week + dt.timedelta(days=d) for d in days] if days else [s + dt.timedelta(weeks=n * step)]
        elif freq == "MONTHLY":
            batch = [x for x in [_add_months(s, n * step)] if x]
        else:
            batch = [x for x in [_add_months(s, 12 * n * step)] if x]
        n += 1
        for x in sorted(batch):
            if x < s:
                continue
            if until and x > until:
                return
            yield x
            made += 1
            if count and made >= count:
                return


def occurrences(events, start, end):
    """Each event's occurrences overlapping [start, end): [{uid, summary, location, description, start, end}], a moved
    occurrence in place of its repeat, excluded dates left out."""
    moved = {(e.get("uid"), e["recurrence_id"]): e for e in events if e.get("recurrence_id")}
    out = []
    for e in events:
        if e.get("recurrence_id"):
            continue
        length = e["end"] - e["start"]
        for s in starts(e):
            if s >= end:
                break
            if s in e["exdates"]:
                continue
            x = moved.get((e.get("uid"), s))
            occ = ({**x, "start": x["start"], "end": x["end"]} if x else {**e, "start": s, "end": s + length})
            if occ["end"] > start and occ["start"] < end:
                out.append({k: occ.get(k, "") for k in ("uid", "summary", "location", "description")} | {"start": occ["start"], "end": occ["end"]})
    return sorted(out, key=lambda o: o["start"])
