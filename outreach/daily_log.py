"""What happened each day in Instantly, for the daily summary email (agreed 27 Oct 2026, Ariel).

Button 4 reads every lead in the Diablo campaigns from Instantly. Each time it sees something new
about a contact (a real reply, an automatic answer, a bounce, an opt-out), it is written here once,
under the day it happened: India time in "days" (button 4's campaign guard reads those) and, from 20 Nov 2026,
UK time in "uk_days" (the daily summary email reports UK days, midnight to midnight; "uk_since" says from when).
Only HubSpot contact IDs are kept, never names or addresses.

data/daily_log.json:
  {"days": {"2026-10-27": {"positive": [ids], "negative": [...], "neutral": [...], "auto": [...],
                           "bounced": [...], "opted_out": [...]}},
   "seen": {"response": [ids], "auto": [...], "bounced": [...], "opted_out": [...]},
   "before": {"2026-10": {"positive": n, ...}}}

"before" holds what had already happened when the log started (26 Oct 2026, from the timeline notes),
so the month-to-date figures for October 2026 are complete.
"""

import datetime as dt
import json
from zoneinfo import ZoneInfo

from .common import ROOT
from .next_in_line import parse_time

LOG_FILE = ROOT / "data" / "daily_log.json"
KINDS = ("positive", "negative", "neutral", "auto", "bounced", "opted_out")
RESPONSE = {"marked interested": "positive", "marked not interested": "negative", "replied": "neutral"}
OPT_OUT = ("unsubscribed", "blocklisted", "opted out by reply", "opted out earlier")
INDIA = dt.timezone(dt.timedelta(hours=5, minutes=30))
UK = ZoneInfo("Europe/London")  # 20 Nov 2026 (Ariel): the daily summary follows the UK business team's days


def india_day(when=None):
    """The India date of a time (a datetime or an Instantly timestamp), or of now."""
    if when is not None and not isinstance(when, dt.datetime):
        when = parse_time(when)
    when = when or dt.datetime.now(dt.timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(INDIA).date().isoformat()


def uk_day(when=None):
    """The UK date of a time (a datetime or an Instantly timestamp), or of now (summer time included)."""
    if when is not None and not isinstance(when, dt.datetime):
        when = parse_time(when)
    when = when or dt.datetime.now(dt.timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(UK).date().isoformat()


def load(path=None):
    try:
        data = json.loads((path or LOG_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data, path=None):
    path = path or LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _seed(notes_path=None):
    """A new log starts from what the timeline notes already hold (26 Oct 2026): those contacts are
    never counted again, and they make up October 2026's figures before the log began."""
    from . import timeline
    notes = timeline.load(notes_path)
    seen = {"response": set(), "auto": set(), "bounced": set(), "opted_out": set()}
    before = {k: 0 for k in KINDS}
    for event, kind in RESPONSE.items():
        ids = notes.get(f"reply:{event}", set())
        seen["response"] |= ids
        before[kind] += len(ids)
    seen["auto"] |= notes.get("reply:out of office", set())
    before["auto"] = len(seen["auto"])
    seen["bounced"] |= notes.get("bounced", set())
    before["bounced"] = len(seen["bounced"])
    return {"days": {}, "seen": {k: sorted(v) for k, v in seen.items()}, "before": {"2026-10": before}}


def record(events, path=None, notes_path=None, now=None):
    """events: [(contact record, Instantly lead, event)] as button 4's Sync reads them. Returns how
    many new entries were written."""
    data = load(path) or _seed(notes_path)
    seen = {k: set(map(str, v)) for k, v in (data.get("seen") or {}).items()}
    days = data.setdefault("days", {})
    uk_days = data.setdefault("uk_days", {})
    data.setdefault("uk_since", (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds"))
    added = 0
    for record_, lead, event in events:
        cid = str(record_["id"])
        # 20 Nov 2026 (Ariel): every event is filed on the day button 4 notices it (replies too, as bounces and
        # opt-outs already were), the moment HubSpot's Lead Status changes, so the daily email's charts and Key numbers
        # count it on the same day. A reply sent at 23:00 UK and noticed at 01:30 is in the next day's email.
        if event in RESPONSE:
            group, kind = "response", RESPONSE[event]
            when = now
        elif event == "out of office":
            group = kind = "auto"
            when = now
        elif event == "bounced":
            group = kind = "bounced"
            when = now
        elif event in OPT_OUT:
            group = kind = "opted_out"
            when = now
        else:
            continue
        if cid in seen.setdefault(group, set()):
            continue
        seen[group].add(cid)
        days.setdefault(india_day(when), {}).setdefault(kind, []).append(cid)
        uk_days.setdefault(uk_day(when), {}).setdefault(kind, []).append(cid)
        added += 1
    if added or not (path or LOG_FILE).exists():
        data["seen"] = {k: sorted(v) for k, v in seen.items()}
        save(data, path)
    return added


def uk_covers(data, date):
    """True when the UK record holds the whole of this UK date (it began before the date's midnight)."""
    since = parse_time(data.get("uk_since"))
    start = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(), UK)
    return bool(since) and since <= start


def day(data, date, uk=False):
    """{kind: [contact IDs]} for one India date, or one UK date (uk=True; the India record when the UK one does not
    cover that date yet)."""
    key = "uk_days" if uk and uk_covers(data, date) else "days"
    entry = (data.get(key) or {}).get(date) or {}
    return {k: list(entry.get(k) or []) for k in KINDS}


def month_counts(data, first, last, uk=False, before=True):
    """{kind: n} from first to last (inclusive), with what came before the log (before=False: without it, as for a
    week). uk=True: UK dates where the UK record covers them, India dates before that."""
    out = {k: 0 for k in KINDS}
    for date, entry in (data.get("days") or {}).items():
        if first <= date <= last and not (uk and uk_covers(data, date)):
            for k in KINDS:
                out[k] += len(entry.get(k) or [])
    for date, entry in ((data.get("uk_days") or {}).items() if uk else ()):
        if first <= date <= last and uk_covers(data, date):
            for k in KINDS:
                out[k] += len(entry.get(k) or [])
    for k, n in (((data.get("before") or {}).get(first[:7]) or {}) if before else {}).items():
        if k in out:
            out[k] += int(n)
    return out
