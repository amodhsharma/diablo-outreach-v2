"""The company Lead Status "Missing info on Apollo" (agreed 23 Oct 2026, Ariel).

- Research import: Apollo holds nobody with an email at the company and its website shows no usable
  address -> "Missing info on Apollo". (No website, or a dead one, stays "Missing Info".)
- A person may still set such a company to GATE1. Button 3 then searches everywhere (Apollo, then the
  website): with a contact found, the company moves on as usual; with nothing found anywhere it becomes
  "Missing Info", and "Outreach stopped because" says "No contact found anywhere (date)".
- That note is the memory: a company carrying it that is set to "Missing info on Apollo" again (by
  mistake) goes back to "Missing Info" at the next run of button 3.
- Every two weeks button 3 asks Apollo again about each "Missing info on Apollo" company (a free search,
  no credits). When Apollo now holds someone, the company goes back to "New", so it comes up at gate 1
  again; otherwise it stays as it is.

The date of the last Apollo check is kept in "Outreach stopped because", so no new field is needed.
"""

import datetime as dt
import re

from .import_checks import apollo_people
from .schema import LEAD_STATUS, STOP_REASON

APOLLO_NOBODY = "Apollo holds nobody with an email and the website shows no usable address"
NOWHERE = "No contact found anywhere"
APOLLO_NOW = "Apollo now holds"
RECHECK_DAYS = 14
RECHECK_LIMIT = 100  # most companies asked about again in one run of button 3
PROPS = ["name", "domain", STOP_REASON]


def _today():
    return dt.date.today()


def apollo_reason(day=None):
    return f"{APOLLO_NOBODY} ({(day or _today()).isoformat()}); set it to GATE1 and button 3 searches everywhere"


def nowhere_reason(day=None):
    return (f"{NOWHERE} ({(day or _today()).isoformat()}): nobody in Apollo and no usable address on its "
            "website")


def _reason(record):
    return str((record.get("properties", record) or {}).get(STOP_REASON) or "")


def is_nowhere(record):
    """True when button 3 already found no contact anywhere for this company."""
    return _reason(record).startswith(NOWHERE)


def checked_on(record):
    """The day Apollo was last asked about the company, or None when the note does not say."""
    text = _reason(record)
    if not text.startswith(APOLLO_NOBODY):
        return None
    m = re.search(r"\((\d{4}-\d{2}-\d{2})\)", text)
    try:
        return dt.date.fromisoformat(m.group(1)) if m else None
    except ValueError:
        return None


def has_reason_field(hs):
    try:
        return bool(hs.has_property("companies", STOP_REASON))
    except Exception:
        return False


def missing_apollo_props(hs, statuses, day=None):
    """The props for a company Apollo holds nobody at: the new choice once button 1 has added it,
    otherwise "Missing Info" as before."""
    stage = "missing_apollo" if statuses.has("companies", "missing_apollo") else "missing_info"
    props = dict(statuses.props("companies", stage))
    if has_reason_field(hs):
        props[STOP_REASON] = apollo_reason(day)
    return props


def nowhere_props(hs, statuses, day=None):
    """The props for a company button 3 found no contact for anywhere: "Missing Info" and the note."""
    props = dict(statuses.props("companies", "missing_info"))
    if has_reason_field(hs):
        props[STOP_REASON] = nowhere_reason(day)
    return props


def _missing_apollo(hs, statuses):
    if not statuses.has("companies", "missing_apollo"):
        return []
    return hs.tagged_search("companies", [statuses.filter("companies", "missing_apollo")], PROPS, max_results=5000)


def tidy(hs, statuses, log=print, companies=None):
    """A company button 3 already found nobody for, set to "Missing info on Apollo" again (by mistake),
    goes back to "Missing Info". Returns how many changed."""
    companies = _missing_apollo(hs, statuses) if companies is None else companies
    back = [c for c in companies if is_nowhere(c)]
    if back:
        hs.update_tagged("companies", [(c["id"], statuses.props("companies", "missing_info")) for c in back])
        for c in back:
            log(f'{c["properties"].get("name") or "A company"}: button 3 already found no contact anywhere, so '
                '"Missing info on Apollo" was set back to "Missing Info"')
    return len(back)


def recheck(hs, apollo, statuses, log=print, day=None, days=RECHECK_DAYS, limit=RECHECK_LIMIT, companies=None):
    """Ask Apollo again about each "Missing info on Apollo" company last asked two weeks ago or more (or
    never). Someone there now: back to "New" for gate 1. Nobody: the note gets today's date. Returns
    {"asked": n, "back_to_new": n}."""
    day = day or _today()
    companies = _missing_apollo(hs, statuses) if companies is None else companies
    due = [c for c in companies if not is_nowhere(c) and (checked_on(c) is None or (day - checked_on(c)).days >= days)]
    asked, back, still = 0, [], []
    for c in due[:limit]:
        domain = (c["properties"].get("domain") or "").strip().lower()
        if not domain:
            continue
        found = apollo_people(apollo, domain)
        asked += 1
        if found is None:  # Apollo could not be asked: try again next run
            continue
        (back if found else still).append((c, found))
    reason_field = has_reason_field(hs)
    updates = []
    for c, found in back:
        props = dict(statuses.props("companies", "found"))
        if reason_field:
            props[STOP_REASON] = f"{APOLLO_NOW} {found} people with an email ({day.isoformat()}): back to New for gate 1"
        updates.append((c["id"], props))
        log(f'{c["properties"].get("name") or "A company"}: Apollo now holds {found} people with an email, so it is '
            'back to "New" for gate 1')
    if reason_field:
        updates += [(c["id"], {STOP_REASON: apollo_reason(day)}) for c, _ in still]
    if updates:
        hs.update_tagged("companies", updates)
    if asked:
        log(f'Missing info on Apollo: {asked} companies asked about again in Apollo, {len(back)} back to "New"')
    return {"asked": asked, "back_to_new": len(back)}


# ---- "Contact exists, not AUTO-OUTREACH" (agreed 26 Oct 2026, Ariel) --------------------------------
EXISTS = "Contact already in HubSpot"


def existing_contacts(hs, company_id, emails=()):
    """The contacts already in HubSpot for a company button 3 could add nobody to: everyone linked to
    the company, plus any address it found (in Apollo or on the website) that HubSpot already holds.
    Read only; none of them is ever changed. [contact records with hubspot_owner_id]."""
    linked = (hs.associated_ids("companies", "contacts", [str(company_id)]) or {}).get(str(company_id)) or []
    found = hs.batch_read("contacts", linked, ["email", "hubspot_owner_id"]) if linked else []
    known = {str(r["id"]) for r in found}
    extra = [e for e in dict.fromkeys(emails) if e]
    for r in hs.batch_read("contacts", extra, ["email", "hubspot_owner_id"], id_property="email") if extra else []:
        if str(r["id"]) not in known:
            found.append(r)
            known.add(str(r["id"]))
    return found


def exists_reason(contacts, names=None, day=None):
    """e.g. "Contact already in HubSpot (26 Oct 2026): 3 contacts, 2 owned by Aastha, 1 by Junaid Khan;
    tag one AUTO-OUTREACH and button 3 sets the company back to GATE1"."""
    from collections import Counter
    names = names or {}
    owners = Counter(names.get(str((c.get("properties") or {}).get("hubspot_owner_id") or ""), "") or "nobody"
                     for c in contacts)
    parts = [f"{n} owned by {o}" if i == 0 else f"{n} by {o}" for i, (o, n) in enumerate(owners.most_common())]
    n = len(contacts)
    return (f"{EXISTS} ({(day or _today()).strftime('%d %b %Y').lstrip('0')}): {n} contact{'s' if n != 1 else ''}"
            + (f", {', '.join(parts)}" if parts else "") + "; tag one AUTO-OUTREACH and button 3 sets the company "
            "back to GATE1")


def exists_props(hs, statuses, contacts, names=None, day=None):
    """The props for a company whose only contacts are already in HubSpot: the new choice once button 1
    has added it (otherwise "Missing Info"), and the note saying who holds them."""
    stage = "contact_exists" if statuses.has("companies", "contact_exists") else "missing_info"
    props = dict(statuses.props("companies", stage))
    if has_reason_field(hs):
        props[STOP_REASON] = exists_reason(contacts, names, day)[:250]
    return props


BACK_TO_GATE1 = ("missing_info", "missing_apollo", "contact_exists")


def back_to_gate1(hs, statuses, company_ids, log=print):
    """Companies where a person has just tagged a contact AUTO-OUTREACH by hand go back to GATE1 (from
    Missing Info, Missing info on Apollo or Contact exists, not AUTO-OUTREACH), and their note is
    cleared. Returns how many changed."""
    ids = sorted({str(c) for c in company_ids})
    if not ids:
        return 0
    rows = hs.tagged_read("companies", ids, ["name", STOP_REASON, LEAD_STATUS])
    updates = []
    for r in rows:
        if statuses.of("companies", r) in BACK_TO_GATE1:
            props = dict(statuses.props("companies", "approved"))
            if has_reason_field(hs):
                props[STOP_REASON] = ""
            updates.append((r["id"], props))
            log(f'{(r.get("properties") or {}).get("name") or "A company"}: a contact was tagged AUTO-OUTREACH by '
                "hand, so the company is back on GATE1: Approved for outreach")
    if updates:
        hs.update_tagged("companies", updates)
    return len(updates)
