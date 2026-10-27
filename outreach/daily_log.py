"""What happened each day in Instantly, for the daily summary email (agreed 27 Oct 2026, Ariel).

Button 4 reads every lead in the Diablo campaigns from Instantly. Each time it sees something new
about a contact (a real reply, an automatic answer, a bounce, an opt-out), it is written here once,
under the day it happened (India time). Only HubSpot contact IDs are kept, never names or addresses.

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

from .common import ROOT
from .next_in_line import parse_time

LOG_FILE = ROOT / "data" / "daily_log.json"
KINDS = ("positive", "negative", "neutral", "auto", "bounced", "opted_out")
RESPONSE = {"marked interested": "positive", "marked not interested": "negative", "replied": "neutral"}
OPT_OUT = ("unsubscribed", "blocklisted", "opted out by reply", "opted out earlier")
INDIA = dt.timezone(dt.timedelta(hours=5, minutes=30))


def india_day(when=None):
    """The India date of a time (a datetime or an Instantly timestamp), or of now."""
    if when is not None and not isinstance(when, dt.datetime):
        when = parse_time(when)
    when = when or dt.datetime.now(dt.timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(INDIA).date().isoformat()


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
    added = 0
    for record_, lead, event in events:
        cid = str(record_["id"])
        if event in RESPONSE:
            group, kind = "response", RESPONSE[event]
            when = lead.get("timestamp_last_reply") or now
        elif event == "out of office":
            group = kind = "auto"
            when = lead.get("timestamp_last_reply") or now
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
        added += 1
    if added or not (path or LOG_FILE).exists():
        data["seen"] = {k: sorted(v) for k, v in seen.items()}
        save(data, path)
    return added


def day(data, date):
    """{kind: [contact IDs]} for one India date."""
    entry = (data.get("days") or {}).get(date) or {}
    return {k: list(entry.get(k) or []) for k in KINDS}


def month_counts(data, first, last):
    """{kind: n} from first to last (India dates, inclusive), with what came before the log."""
    out = {k: 0 for k in KINDS}
    for date, entry in (data.get("days") or {}).items():
        if first <= date <= last:
            for k in KINDS:
                out[k] += len(entry.get(k) or [])
    for k, n in ((data.get("before") or {}).get(first[:7]) or {}).items():
        if k in out:
            out[k] += int(n)
    return out
