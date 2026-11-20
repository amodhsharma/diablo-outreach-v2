"""Replies not AUTO-OUTREACH (Need Amodh's input), in the daily summary email (agreed 21 Nov 2026, Ariel).

Some replies arrive in our eight sending mailboxes from people the automation does not look after: a company
added to HubSpot by hand, an older campaign, or someone not in HubSpot at all (Vegan Grocery Store, 20 Nov 2026).
The automation never acts on them, so until now they showed up nowhere. The daily email lists each one once, on
the UK day it arrived, for Amodh to handle:

    Company (or the email domain)   Arrived in                 In HubSpot                          Their reply
    Vegan Grocery Store, Australia  sales@diablosnosugar.com   Yes, not AUTO-OUTREACH (owner: ...)  "Thanks ..."

Left out: automatic replies (out of office), bounce notices, requests not to be emailed, our own emails, and
anyone who is an AUTO-OUTREACH contact (their replies are under Positive or Negative replies, or the referrals).
Read only: nothing is changed in HubSpot or Instantly, and no company is ever moved into AUTO-OUTREACH (that is
Ariel's manual step).
"""

from .common import from_us
from .countries import uniform
from .next_in_line import parse_time
from .schema import TAG, TAG_PROPERTY

EXCERPT = 200


def _domain(address):
    return address.lower().rsplit("@", 1)[-1] if "@" in address else ""


def read(hs, emails_api, start, end, log=print):
    """[{"company", "country", "mailbox", "hubspot", "reply"}] for the real replies from people who are not
    AUTO-OUTREACH contacts, received from start to end, or None when Instantly's emails could not be read."""
    from .corrupt import _is_notice
    from .sync import _with_body, is_auto_reply, is_opt_out_reply, reply_text
    if emails_api is None:
        return None
    try:
        emails = emails_api.emails_since(start.isoformat())
    except Exception as err:
        log(f"Could not read the replies from outside the automation: {str(err)[:150]}")
        return None
    if emails is None:
        return None
    first = {}
    for e in emails:
        when = parse_time(e.get("timestamp_created") or e.get("timestamp_email"))
        sender = str(e.get("from_address_email") or "").strip().lower()
        if e.get("ue_type") != 2 or not when or not (start <= when < end) or not sender or sender in first:
            continue
        if from_us(e) or _is_notice(e):
            continue
        try:
            e = _with_body(emails_api, e)
        except Exception:
            pass
        if is_auto_reply(e) or is_opt_out_reply(e):
            continue
        first[sender] = e
    if not first:
        return []
    ours = {str((r.get("properties") or {}).get("email") or "").lower()
            for r in hs.tagged_read("contacts", list(first), ["email"], id_property="email")}
    rest = {a: e for a, e in first.items() if a not in ours}
    if not rest:
        return []
    contacts = {str((r.get("properties") or {}).get("email") or "").lower(): r
                for r in hs.batch_read("contacts", list(rest), ["email", "hubspot_owner_id", TAG_PROPERTY],
                                       id_property="email")}
    links = hs.associated_ids("contacts", "companies", [str(r["id"]) for r in contacts.values()]) if contacts else {}
    company_ids = sorted({c for cs in links.values() for c in cs})
    companies = {str(r["id"]): r for r in hs.batch_read("companies", company_ids,
                                                         ["name", "country", "hubspot_owner_id", TAG_PROPERTY])} \
        if company_ids else {}
    try:
        owners = hs.owner_names()
    except Exception:
        owners = {}
    out = []
    for address, e in sorted(rest.items()):
        contact = contacts.get(address)
        company = None
        if contact:
            company = next((companies[c] for c in links.get(str(contact["id"])) or [] if c in companies), None)
        if company is None:  # not a contact: is the company itself in HubSpot?
            try:
                found = hs.search("companies", [{"propertyName": "domain", "operator": "EQ", "value": _domain(address)}],
                                  ["name", "country", "hubspot_owner_id", TAG_PROPERTY], max_results=1)
            except Exception:
                found = []
            company = found[0] if found else None
        cp = (company or {}).get("properties") or {}
        owner_id = ((contact or {}).get("properties") or {}).get("hubspot_owner_id") or cp.get("hubspot_owner_id")
        owner = owners.get(str(owner_id)) if owner_id else None
        if contact:
            where = "Yes, not AUTO-OUTREACH" + (f" (owner: {owner})" if owner else "")
        elif company and cp.get(TAG_PROPERTY) == TAG:
            where = "Company is AUTO-OUTREACH, this person is not a contact"
        elif company:
            where = "Company only, not AUTO-OUTREACH" + (f" (owner: {owner})" if owner else "")
        else:
            where = "Not in HubSpot"
        text = " ".join(reply_text(e).split())
        out.append({"company": cp.get("name") or _domain(address), "country": uniform(cp.get("country")) or "",
                    "mailbox": str(e.get("eaccount") or "").lower(), "hubspot": where,
                    "reply": text[:EXCERPT] + ("..." if len(text) > EXCERPT else "")})
    return out
