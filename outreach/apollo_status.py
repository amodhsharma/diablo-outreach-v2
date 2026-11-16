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


EXISTING_PROPS = ["email", "hubspot_owner_id", LEAD_STATUS, "hs_email_optout", "hs_email_hard_bounce_reason_enum",
                  "lead_source"]


def existing_contacts(hs, company_id, emails=()):
    """The contacts already in HubSpot for a company button 3 could add nobody to: everyone linked to
    the company, plus any address it found (in Apollo or on the website) that HubSpot already holds.
    Read only; none of them is ever changed. [contact records with hubspot_owner_id]."""
    linked = (hs.associated_ids("companies", "contacts", [str(company_id)]) or {}).get(str(company_id)) or []
    found = hs.batch_read("contacts", linked, EXISTING_PROPS) if linked else []
    known = {str(r["id"]) for r in found}
    extra = [e for e in dict.fromkeys(emails) if e]
    for r in hs.batch_read("contacts", extra, EXISTING_PROPS, id_property="email") if extra else []:
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


# ---- No usable contact (agreed 16 Nov 2026, Ariel) -----------------------------------------------------
# "Contact exists, not AUTO-OUTREACH" only means there is a person you can tag. When none of the contacts
# already in HubSpot can be used (no email address, a Won customer's contact, opted out, a bounced address,
# or already AUTO-OUTREACH under another company record), the company becomes "Missing Info" and
# "Outreach stopped because" gives the real reason. Button 3 does this for new cases and, at the start of
# every run, for the companies already on "Contact exists". Tagging a contact by hand still sends the
# company back to GATE1 (back_to_gate1).
UNUSABLE = "No usable contact"
ELSEWHERE = "already AUTO-OUTREACH elsewhere"
_ONE = {"no email": "the only contact has no email address",
        "Won": "the only contact belongs to a Won customer",
        "opted out": "the only contact opted out",
        "dead address": "the only contact's address bounced",
        ELSEWHERE: "the only contact is already AUTO-OUTREACH under another company record (this may be a duplicate)"}
_MANY = {"no email": "{n} have no email address",
         "Won": "{n} belong to a Won customer",
         "opted out": "{n} opted out",
         "dead address": "{n} bounced",
         ELSEWHERE: "{n} are already AUTO-OUTREACH under another company record"}


def unusable_reasons(hs, statuses, company_id, contacts, blocked=None):
    """{reason: n} when none of the contacts can be tagged, or None when at least one can.
    blocked: Instantly's blocklist, or None when it could not be read (then only HubSpot's own opt-out
    counts, so a doubtful contact still counts as one you can tag)."""
    from .hubspot_client import tagged
    from .takeover import why_not, _is_won
    if not contacts:
        return None
    ids = [str(c["id"]) for c in contacts]
    theirs = hs.associated_ids("contacts", "companies", ids) or {}
    others = sorted({str(x) for xs in theirs.values() for x in xs or [] if str(x) != str(company_id)})
    rows = hs.batch_read("companies", others, [LEAD_STATUS]) if others else []
    won = {str(r["id"]) for r in rows if _is_won(statuses, "companies", r.get("properties"))}
    auto = {str(r["id"]) for r in rows if tagged(r.get("properties"))}
    reasons = {}
    for c in contacts:
        links = [str(x) for x in theirs.get(str(c["id"])) or []]
        if tagged(c.get("properties")):
            if not any(x in auto for x in links):
                return None  # in the loop at this company already
            reason = ELSEWHERE
        else:
            reason = why_not(c, statuses, blocked, [x for x in links if x in won])
            if reason is None:
                return None
        reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def unusable_reason(reasons, day=None):
    """e.g. "No usable contact (16 Nov 2026): the only contact has no email address; fix it or add a
    person, tag them AUTO-OUTREACH and button 3 sets the company back to GATE1"."""
    n = sum(reasons.values())
    if n == 1:
        text = _ONE.get(next(iter(reasons)), "the only contact cannot be used")
    else:
        parts = [_MANY.get(k, "{n} cannot be used").format(n=v) for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])]
        text = f"none of its {n} contacts can be used: " + ", ".join(parts)
        if set(reasons) == {ELSEWHERE}:
            text += " (this may be a duplicate)"
    return (f"{UNUSABLE} ({(day or _today()).strftime('%d %b %Y').lstrip('0')}): {text}; fix it or add a person, "
            "tag them AUTO-OUTREACH and button 3 sets the company back to GATE1")


def unusable_props(hs, statuses, reasons, day=None):
    props = dict(statuses.props("companies", "missing_info"))
    if has_reason_field(hs):
        props[STOP_REASON] = unusable_reason(reasons, day)[:250]
    return props


def recheck_exists(hs, statuses, blocked=None, log=print, skip_contacts=()):
    """The companies already on "Contact exists, not AUTO-OUTREACH" whose contacts can none of them be
    used become "Missing Info" with the reason. Companies linked to a contact in skip_contacts (just
    taken over in this run) are left alone. Returns how many changed."""
    if not statuses.has("companies", "contact_exists"):
        return 0
    found = hs.tagged_search("companies", [statuses.filter("companies", "contact_exists")], ["name"],
                             max_results=2000)
    if not found:
        return 0
    links = hs.associated_ids("companies", "contacts", [str(c["id"]) for c in found]) or {}
    skip = {str(x) for x in skip_contacts}
    # Read again by ID: a company sent back to GATE1 earlier in this run may still show here in a search.
    now = {str(r["id"]): r for r in hs.tagged_read("companies", [str(c["id"]) for c in found], ["name", LEAD_STATUS])}
    updates = []
    for c in found:
        cid = str(c["id"])
        linked = [str(x) for x in links.get(cid) or []]
        row = now.get(cid)
        if not linked or skip & set(linked) or not row or statuses.of("companies", row) != "contact_exists":
            continue
        reasons = unusable_reasons(hs, statuses, cid, hs.batch_read("contacts", linked, EXISTING_PROPS), blocked)
        if reasons:
            updates.append((cid, unusable_props(hs, statuses, reasons)))
            log(f'{(row.get("properties") or {}).get("name") or "A company"}: none of its contacts can be used, so it '
                'is now "Missing Info" (' + unusable_reason(reasons).split(": ", 1)[1].split(";")[0] + ")")
    if updates:
        hs.update_tagged("companies", updates)
    return len(updates)


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


# ---- Websites read again for hidden addresses (agreed 1 Nov 2026, Ariel) -----------------------------
# Until 1 Nov 2026 button 3 could not read addresses hidden by Cloudflare's email protection (Cycle Fitness
# Nutrition shows info@ to people, "[email protected]" to programs). Each "Missing Info" company whose note
# says "No contact found anywhere" has its website read once more; when an address is found now, the
# company goes back to "GATE1: Approved for outreach" and button 3 adds that address as its company inbox
# in the same run. data/website_rechecked.json remembers which companies were read again (company IDs and
# the day only), so each is read once; at most WEBSITE_RECHECK_LIMIT a run, so the run stays short.
WEBSITE_FOUND = "Its website address was found after all"
WEBSITE_RECHECK_LIMIT = 60


def _rechecked_file():
    from .common import ROOT
    return ROOT / "data" / "website_rechecked.json"


def load_rechecked(path=None):
    import json
    try:
        data = json.loads((path or _rechecked_file()).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_rechecked(data, path=None):
    import json
    path = path or _rechecked_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(data.items())), indent=1) + "\n", encoding="utf-8")


def recheck_websites(hs, statuses, log=print, limit=WEBSITE_RECHECK_LIMIT, path=None, find=None):
    """Read again the websites of "No contact found anywhere" companies (once each). Returns
    {"read": n, "back_to_gate1": [names], "left": n}."""
    from . import company_inbox
    find = find or company_inbox.find_inbox
    done = load_rechecked(path)
    companies = hs.tagged_search("companies", [statuses.filter("companies", "missing_info")], PROPS, max_results=5000)
    due = [c for c in companies if is_nowhere(c) and str(c["id"]) not in done
           and (c["properties"].get("domain") or "").strip()]
    back, read = [], 0
    try:
        for c in due[:limit]:
            p = c["properties"]
            email = find(p.get("domain"), name=p.get("name"))
            read += 1
            done[str(c["id"])] = _today().isoformat()
            if email:
                back.append(c)
    finally:  # whatever happens, the companies already read are not read again
        if read:
            save_rechecked(done, path)
    if back:
        props = dict(statuses.props("companies", "approved"))
        if has_reason_field(hs):
            props[STOP_REASON] = f"{WEBSITE_FOUND} ({_today().isoformat()}): back to GATE1"
        hs.update_tagged("companies", [(c["id"], props) for c in back])
        for c in back:
            log(f'{c["properties"].get("name") or "A company"}: its website shows a contact address after all; the '
                "company is back on GATE1 and gets it as its company inbox in this run (or the next)")
    left = max(0, len(due) - read)
    if read:
        log(f"Missing Info: {read} websites read again for hidden addresses, {len(back)} back on GATE1"
            + (f", {left} left for the next runs" if left else ""))
    return {"read": read, "back_to_gate1": [c["properties"].get("name") or "" for c in back], "left": left}
