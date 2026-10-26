"""What happened to each contact's emails, written on its HubSpot timeline (agreed 26 Oct 2026, Ariel).

Our emails go out through Instantly's mailboxes, which HubSpot does not see. So button 4 writes a note
on the contact's timeline, once for each of these:
  - the introduction is added to the Instantly campaign (it then goes out in the sending hours);
  - Instantly has sent it (with the time it was sent);
  - it bounced;
  - they replied (a real reply, marked interested or not interested), or sent only an automatic answer.
Opt-outs, "no reply in time" and an Unqualified company already get their note from "Outreach stopped
because". data/timeline_notes.json remembers which notes were written (contact IDs only), so none is
written twice.
"""

import json

from .common import ROOT, ist
from .next_in_line import parse_time

NOTES_FILE = ROOT / "data" / "timeline_notes.json"
PREFIX = "Diablo outreach: "
REPLY_TEXT = {"replied": "they replied", "marked interested": "they replied, marked interested in Instantly",
              "marked not interested": "they replied, marked not interested in Instantly",
              "out of office": "they sent only an automatic answer (out of office or similar), so the loop carries on"}


def load(path=None):
    try:
        data = json.loads((path or NOTES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {k: set(map(str, v)) for k, v in data.items()}


def save(done, path=None):
    path = path or NOTES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: sorted(v) for k, v in sorted(done.items())}, indent=1) + "\n", encoding="utf-8")


def _mailbox(lead):
    for key in ("last_step_from", "eaccount", "sending_account"):
        if lead.get(key):
            return f" from {lead[key]}"
    return ""


def write(hs, items, log=print):
    """items: [(contact id, text)]. Never stops the run."""
    items = [(cid, PREFIX + text) for cid, text in items if text]
    if not items:
        return 0
    try:
        hs.note_tagged("contacts", items)
    except Exception as err:
        log(f"Could not write {len(items)} timeline notes on contacts: {str(err)[:200]}")
        return 0
    return len(items)


def queued(hs, contacts, campaign, log=print, path=None):
    """Button 4 has added these introductions to an Instantly campaign: [(contact id)]."""
    done = load(path)
    seen = done.setdefault("queued", set())
    todo = [str(c) for c in contacts if str(c) not in seen]
    import datetime as dt
    day = dt.date.today().strftime("%d %b %Y").lstrip("0")
    n = write(hs, [(c, f"introduction added to the Instantly campaign \"{campaign}\" ({day}); it goes out "
                       "in the campaign's sending hours") for c in todo], log)
    if n:
        seen.update(todo)
        save(done, path)
    return n


def from_instantly(hs, events, log=print, path=None):
    """events: [(contact record, Instantly lead, event)] read by Sync. Writes the notes not written yet."""
    done = load(path)
    items, marks = [], []
    for record, lead, event in events:
        cid = str(record["id"])
        sent = parse_time(lead.get("timestamp_last_contact"))
        if sent and cid not in done.get("sent", set()):
            items.append((cid, f"introduction email sent {ist(sent)}{_mailbox(lead)}"))
            marks.append(("sent", cid))
        if event == "bounced" and cid not in done.get("bounced", set()):
            items.append((cid, "the email bounced (the address does not work)"))
            marks.append(("bounced", cid))
        key = f"reply:{event}"
        if event in REPLY_TEXT and cid not in done.get(key, set()):
            items.append((cid, REPLY_TEXT[event]))
            marks.append((key, cid))
    if write(hs, items, log):
        for key, cid in marks:
            done.setdefault(key, set()).add(cid)
        save(done, path)
    return len(items)
