"""Button 4's own memory of every person it emails (agreed 17 Nov 2026, Ariel).

Each person has their own record and timers, kept in data/send_memory.json (contact and company IDs,
Outreach order and times only; never a name or an email address):

    queued       their introduction was added to an Instantly campaign
    introduced   their introduction actually went (Instantly's send time)
    reminded     their one reminder went
    closed       no reply 48 hours after their reminder: "Unqualified: Contacted, but no response"
    approved     when button 4 first saw them on GATE2 (the order new companies are started in)

The timers that follow from it (send.next_contact_after_days, send.rotation.min_days_same_person and
send.chain.contact_close_after_hours): the next person at the company 48 hours after this person's
introduction, this person's reminder 96 hours after it, and this person closed 48 hours after the reminder.

HubSpot is read as well. A reply in HubSpot or Instantly always wins (the company stops). The memory wins
on sending: anyone it shows as already queued, introduced, reminded or closed is never given that email
again, whatever HubSpot says. On its first run it fills itself in for everyone already emailed, from the
times Instantly holds.
"""

import datetime as dt
import json

from .common import ROOT

FILE = ROOT / "data" / "send_memory.json"


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def _iso(when):
    return when.astimezone(dt.timezone.utc).isoformat(timespec="seconds") if when else None


def parse(value):
    if not value:
        return None
    try:
        when = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def load(path=None):
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("contacts", {})
    return data


def save(memory, path=None, now=None):
    path = path or FILE
    memory.setdefault("started", _iso(now or now_utc()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def entry(memory, contact_id):
    return (memory.get("contacts") or {}).get(str(contact_id)) or {}


def _set(memory, contact_id, field, when, **extra):
    """Write a time once: the first time is kept."""
    rec = memory.setdefault("contacts", {}).setdefault(str(contact_id), {})
    for k, v in extra.items():
        if v not in (None, ""):
            rec[k] = v
    if when is not None and not rec.get(field):
        rec[field] = _iso(when)
    return rec


def _about(contact, company_id):
    from .next_in_line import is_company_inbox, rank_of
    out = {"inbox": bool(is_company_inbox(contact))}
    if company_id:
        out["company"] = str(company_id)
    if rank_of(contact) < 999:
        out["order"] = rank_of(contact)
    return out


def queued(memory, contact, company_id, now=None):
    _set(memory, contact["id"], "queued", now or now_utc(), **_about(contact, company_id))


def reminded(memory, contact, company_id, now=None):
    _set(memory, contact["id"], "reminded", now or now_utc(), **_about(contact, company_id))


def closed(memory, contact, company_id, now=None):
    _set(memory, contact["id"], "closed", now or now_utc(), **_about(contact, company_id))


def reminded_at(memory, contact_id):
    return parse(entry(memory, contact_id).get("reminded"))


def observe(memory, contacts, company_id, statuses, touches=None, now=None, times=True):
    """Fill the memory in from what HubSpot and Instantly show now, for annotated contacts:
    when each person was first seen approved, introduced (their first email) and reminded (their second
    email, or now when HubSpot says Reminder sent and Instantly's emails were not read)."""
    from .next_in_line import touch_times
    now = now or now_utc()
    for c in contacts:
        about = _about(c, company_id)
        state = c.get("state")
        if state == "approved":
            _set(memory, c["id"], "approved", now, **about)
        if not times:  # only the approvals: the send times wait until Instantly's emails are read
            continue
        sent = [t for t in touch_times(c, touches) if t]
        if state == "sent" and sent:
            _set(memory, c["id"], "introduced", sent[0], **about)
        if statuses.of("contacts", c) == "reminded" or (touches is not None and len(sent) >= 2):
            _set(memory, c["id"], "reminded", sent[1] if len(sent) >= 2 else now, **about)


def apply(memory, contacts, log=print, name=""):
    """What the memory knows that HubSpot may not (in place, on annotated contacts):
    - someone it shows as queued or introduced is never a new introduction again: still waiting for their
      first email ("queued") or emailed ("sent"), whatever HubSpot says;
    - someone it shows as closed is left out;
    - its times fill in an introduction time Instantly did not give, and mark a reminder as done."""
    for c in contacts:
        rec = entry(memory, c["id"])
        if not rec:
            continue
        intro = parse(rec.get("introduced"))
        if intro and not c.get("sent_at"):
            c["sent_at"] = intro
        if rec.get("reminded"):
            c["mem_reminded"] = parse(rec.get("reminded"))
        if c.get("state") in ("approved", "pending"):
            if rec.get("closed"):
                c["state"] = "skipped"
                log(f"{name}: contact {c['id']} was closed earlier (button 4's memory); never emailed again")
            elif rec.get("queued") or intro:
                c["state"] = "sent" if c.get("sent_at") else "queued"
                log(f"{name}: contact {c['id']} was introduced earlier (button 4's memory), though HubSpot shows "
                    "them as waiting; they are not given a second introduction")
    return contacts


ROUND_FIELDS = ("approved", "queued", "introduced", "reminded", "closed")


def new_round(memory, contact_ids, round_no):
    """19 Nov 2026 (Ariel): a restarted company's people start a new round. Their earlier times move to "past" (kept
    for the counters), so the new round's introduction is not blocked; each person once per round. Returns how many
    people moved on."""
    moved = 0
    for cid in contact_ids:
        rec = (memory.get("contacts") or {}).get(str(cid))
        if not rec or int(rec.get("round") or 1) >= round_no:
            continue
        done = {k: rec.pop(k) for k in ROUND_FIELDS if rec.get(k)}
        if done:
            rec.setdefault("past", []).append(dict(done, round=int(rec.get("round") or 1)))
        rec["round"] = round_no
        moved += 1
    return moved


def blocks_intro(memory, contact_id):
    rec = entry(memory, contact_id)
    return bool(rec.get("queued") or rec.get("introduced") or rec.get("closed"))


def first_approved(memory, contact_ids):
    times = [parse(entry(memory, c).get("approved")) for c in contact_ids]
    times = [t for t in times if t]
    return min(times) if times else None


def day_counts(memory, day, india):
    """{"person": n, "inbox": n, "reminders": n} for an India date (YYYY-MM-DD), or None when the memory
    did not exist yet for the whole of that day (the summary then counts as before)."""
    started = parse(memory.get("started"))
    start = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(), india)
    if not started or started > start:
        return None
    out = {"person": 0, "inbox": 0, "reminders": 0}
    for rec in (memory.get("contacts") or {}).values():
        intro = parse(rec.get("introduced"))
        if intro and intro.astimezone(india).date().isoformat() == day:
            out["inbox" if rec.get("inbox") else "person"] += 1
        rem = parse(rec.get("reminded"))
        if rem and rem.astimezone(india).date().isoformat() == day:
            out["reminders"] += 1
    return out
