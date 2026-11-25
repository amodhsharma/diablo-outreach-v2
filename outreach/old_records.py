"""Old records checked with Apollo before their first email (agreed and switched on 25 Nov 2026, Ariel).

An old record is a contact the automation did not find itself: created before 1 October 2026
(send.address_checks.old_before; address_checks.is_old). Last week about 12 to 15% of them bounced, against about
1 to 3% for the contacts the automation finds, and on 25 Nov 2026 one of them (an old company inbox) tipped
"Diablo | NOV2026 | Company inboxes" over Instantly's Bounce Protect.

At every run of button 3, every AUTO-OUTREACH old record still waiting for its first email (New, New with its
line filled or GATE2: Approved to send, and never introduced before) is checked once:

  - an old company inbox (a website address, job title "Company inbox (from website)") cannot be checked on
    Apollo: it becomes "Unqualified: Contact possibly corrupt" and is never emailed;
  - a person is looked up on Apollo by their email address (about 1 credit for each address Apollo holds):
      Apollo confirms the address as verified            -> kept, emailed as usual;
      Apollo holds the person with another verified address -> the contact's email is switched to it, then kept;
      anything else (unknown, not verified, a duplicate) -> "Unqualified: Contact possibly corrupt".

A contact closed this way is never emailed and the next approved person at the company moves up, exactly like
"Unqualified: Contact corrupt" (stages.LEFT_OUT). A company not emailed yet with nobody usable left goes back to
GATE1 (find_contacts.settle), where button 3 imports new people from Apollo with verified emails, who go
through the usual lines and GATE2. Old records already emailed are left alone (their addresses work).

Button 4 holds an old record's first email until it has been checked (send.py). Each contact is checked once:
the result is kept in data/old_record_checks.json (IDs, results and dates only), so no address is paid for twice.
"Outreach stopped because" says why a contact was closed.
"""

import datetime as dt
import json
from pathlib import Path

from .address_checks import is_old, settings_of
from .daily_log import UK
from .schema import INBOX_TITLE, LEAD_STATUS, ORDER, STOP_REASON

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "old_record_checks.json"
WAITING = ("found", "copy_ready", "approved")  # not emailed yet in this round
KEPT, SWITCHED, CLOSED = "kept", "switched", "possibly_corrupt"
PROPS = ["email", "firstname", "lastname", "jobtitle", "createdate", LEAD_STATUS, STOP_REASON]
DEFAULTS = {"enabled": True, "per_run": 200}


def load(path=None):
    p = Path(path or FILE)
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save(data, path=None):
    p = Path(path or FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def cleared(contact_id, data=None):
    """True when an old record has passed its Apollo check (kept or switched): button 4 may send its first email."""
    entry = (load() if data is None else data).get(str(contact_id)) or {}
    return entry.get("result") in (KEPT, SWITCHED)


def _today(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(UK).strftime("%Y-%m-%d")


def _date_words(now=None):
    d = (now or dt.datetime.now(dt.timezone.utc)).astimezone(UK)
    return f"{d.day} {d.strftime('%b %Y')}"


def old_by_date(contact, cfg=None):
    """True for a contact HubSpot says was created before old_before (1 Oct 2026). Unlike address_checks.is_old,
    a record whose creation date is not known is not counted: HubSpot always gives it, so this only matters for
    records made up in tests."""
    p = contact.get("properties", contact) or {}
    created = str(p.get("createdate") or "").strip()
    return bool(created) and is_old(contact, cfg)


def is_inbox(contact):
    p = contact.get("properties", contact) or {}
    return str(p.get("jobtitle") or "").strip().lower() == INBOX_TITLE.lower()


UNCLEAR, RETRY_DAYS = "unclear", 7


def _settled(entry, today=None):
    """True for a contact already checked; one Apollo gave no status for is asked again after RETRY_DAYS days."""
    if not entry:
        return False
    if entry.get("result") != UNCLEAR:
        return True
    try:
        then = dt.date.fromisoformat(entry.get("on") or "")
    except ValueError:
        return False
    return ((today or dt.date.today()) - then).days < RETRY_DAYS


def to_check(hs, statuses, settings, data, memory=None):
    """The AUTO-OUTREACH old records waiting for their first email that have not been checked yet."""
    from . import send_memory
    cfg = settings_of(settings)
    memory = send_memory.load() if memory is None else memory
    out, seen = [], set()
    for stage in WAITING:
        if not statuses.has("contacts", stage):
            continue
        for c in hs.tagged_search("contacts", [statuses.filter("contacts", stage)], PROPS, max_results=5000):
            cid = str(c["id"])
            if cid in seen or not old_by_date(c, cfg) or _settled(data.get(cid)):
                continue
            seen.add(cid)
            if (send_memory.entry(memory, cid) or {}).get("introduced"):
                continue  # emailed in an earlier round: its address works, left alone
            out.append(c)
    return out


def _close(hs, statuses, contact, why, now):
    hs.update_tagged("contacts", [(contact["id"], {**statuses.props("contacts", CLOSED), ORDER: "0",
                                                   STOP_REASON: f"Possibly corrupt: {why} ({_date_words(now)})"})])


def check(hs, apollo, statuses, settings, log=print, now=None, path=None, keep_statuses=None):
    """Checks the old records waiting for their first email (see the top of this file). Returns
    {"kept": n, "switched": n, "closed": n, "inboxes": n, "credits": n, "left": n}."""
    out = {"kept": 0, "switched": 0, "closed": 0, "inboxes": 0, "credits": 0, "left": 0, "unclear": 0}
    cfg = dict(DEFAULTS, **(((settings or {}).get("contacts") or {}).get("old_records") or {}))
    if not cfg["enabled"]:
        return out
    if not statuses.has("contacts", CLOSED):
        log('Old records not checked: the contact Lead Status "Unqualified: Contact possibly corrupt" is missing; '
            "run button 1 to add it")
        return out
    keep_statuses = keep_statuses or (settings.get("contacts") or {}).get("keep_email_statuses") or ["verified"]
    now = now or dt.datetime.now(dt.timezone.utc)
    data = load(path)
    waiting = to_check(hs, statuses, settings, data)
    todo, out["left"] = waiting[:int(cfg["per_run"])], max(0, len(waiting) - int(cfg["per_run"]))
    day = _today(now)

    def remember(contact, result):
        data[str(contact["id"])] = {"result": result, "on": day}

    try:
        people = []
        for c in todo:
            if is_inbox(c):
                _close(hs, statuses, c, "old company inbox from before October 2026, not confirmed", now)
                remember(c, CLOSED)
                out["inboxes"] += 1
                out["closed"] += 1
            elif not str((c.get("properties") or {}).get("email") or "").strip():
                _close(hs, statuses, c, "old record with no email address", now)
                remember(c, CLOSED)
                out["closed"] += 1
            else:
                people.append(c)
        shown = False
        for i in range(0, len(people), 10):
            batch = people[i:i + 10]
            emails = [str(c["properties"]["email"]).strip().lower() for c in batch]
            matches = apollo.match_emails(emails)
            out["credits"] += sum(1 for m in matches if m)
            # 25 Nov 2026: Apollo's match by address came back without "email_status" (and 88 people were closed by
            # mistake, then put back). A match without it is now looked up again by Apollo's own person ID, the way
            # button 3 has always revealed emails (find_contacts), which gives the address and its status.
            missing = [m["id"] for m in matches if m and m.get("id") and not m.get("email_status")]
            if missing and not shown:
                shown = True
                log("Apollo's match by address gave no email status; asking again by person ID. Fields it gave: "
                    + ", ".join(sorted(k for k in next(m for m in matches if m and m.get("id") in missing))))
            revealed = {}
            for j in range(0, len(missing), 10):
                for r in apollo.reveal_emails(missing[j:j + 10]):
                    if r and r.get("id"):
                        revealed[r["id"]] = r
            out["credits"] += len(revealed)
            for c, email, m in zip(batch, emails, matches):
                if m and not m.get("email_status") and m.get("id") in revealed:
                    m = dict(m, **{k: v for k, v in revealed[m["id"]].items() if v})
                if m and not m.get("email_status"):  # never closed without Apollo's word on the address
                    out["unclear"] += 1
                    remember(c, UNCLEAR)
                    log(f"Contact {c['id']}: Apollo gave no status for its address; left as it is (held), asked "
                        f"again in {RETRY_DAYS} days")
                    continue
                found = str((m or {}).get("email") or "").strip().lower()
                good = (m or {}).get("email_status") in keep_statuses
                if m and good and found == email:
                    remember(c, KEPT)
                    out["kept"] += 1
                    continue
                if m and good and found:
                    try:
                        hs.update_tagged("contacts", [(c["id"], {"email": found})])
                    except Exception as err:  # another contact already has that address: this one is a duplicate
                        log(f"Contact {c['id']}: could not switch to Apollo's address ({str(err)[:120]})")
                        _close(hs, statuses, c, "Apollo's verified address for this person belongs to another "
                                                "contact", now)
                        remember(c, CLOSED)
                        out["closed"] += 1
                        continue
                    remember(c, SWITCHED)
                    out["switched"] += 1
                    continue
                why = ("Apollo does not hold this address" if not m else
                       f"Apollo does not confirm this address ({(m or {}).get('email_status') or 'no status'})")
                _close(hs, statuses, c, why, now)
                remember(c, CLOSED)
                out["closed"] += 1
    finally:  # whatever happens, never pay twice for an address already checked
        save(data, path)
    if any(out[k] for k in ("kept", "switched", "closed")) or out["left"]:
        log(f"Old records checked with Apollo: {out['kept']} kept, {out['switched']} switched to Apollo's verified "
            f"address, {out['closed']} closed as possibly corrupt ({out['inboxes']} of them old company inboxes); "
            f"about {out['credits']} Apollo credits" + (f"; {out['left']} checked at the next run" if out["left"] else ""))
    return out


def on_day(day, path=None):
    """{"kept": n, "switched": n, "closed": n} of the checks made on a UK day (YYYY-MM-DD), for the daily email."""
    out = {KEPT: 0, SWITCHED: 0, CLOSED: 0}
    for entry in load(path).values():
        if entry.get("on") == day and entry.get("result") in out:
            out[entry["result"]] += 1
    return {"kept": out[KEPT], "switched": out[SWITCHED], "closed": out[CLOSED]}
