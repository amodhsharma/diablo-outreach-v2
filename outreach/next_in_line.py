"""One person per company at a time, most senior first.

The most senior approved contact at a company gets the first email and the reminder
3 days later. If nobody at the company has replied 4 days after that first email
(send.next_contact_after_days), the next approved contact gets their own email. The
moment anyone replies, everyone else at the company stops. When everyone found has been
emailed without a reply, the company is marked "No reply"; set it back to Approved and
run "Find contacts" to go deeper.

"4b - Send approved contacts: HubSpot to Instantly (timer)" starts each company with its first person; "5. Sync" (every
3 hours) moves companies on to the next person by itself.
"""

import datetime as dt

CONTACT_PROPS = [
    "email", "firstname", "lastname", "jobtitle", "diablo_subject_line", "diablo_personal_line",
    "diablo_contact_status", "diablo_hierarchy_rank", "diablo_last_event_at",
    "diablo_instantly_campaign_id",
]
# The company has answered or must not be contacted: nobody else is emailed.
STOPPED = {"replied", "interested", "not_interested", "suppressed", "no_reply"}
# A contact who has been emailed and did not reply (or whose email bounced).
TRIED = {"sent", "bounced"}
# A contact still on the way to gate 2.
NOT_YET_APPROVED = {"contact_found", "copy_ready", ""}


def parse_time(value):
    if not value:
        return None
    text = str(value).strip()
    if text.isdigit():  # HubSpot can return milliseconds since 1970
        return dt.datetime.fromtimestamp(int(text) / 1000, dt.timezone.utc)
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def rank_of(contact):
    value = str(contact["properties"].get("diablo_hierarchy_rank") or "")
    return int(value) if value.isdigit() else 999


def contacts_by_company(hs, company_ids):
    """{company id: [contact records]} for every contact linked to these companies."""
    links = hs.associated_ids("companies", "contacts", company_ids)
    ids = sorted({c for cs in links.values() for c in cs})
    records = {r["id"]: r for r in hs.batch_read("contacts", ids, CONTACT_PROPS)} if ids else {}
    return {cid: [records[c] for c in cs if c in records] for cid, cs in links.items()}


def decide(contacts, company_status, gap_days, now=None):
    """(the contact to email next or None, why). why is one of:
    next, stopped, waiting, waiting_for_gate_2, no_reply, nothing."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if (company_status or "") in STOPPED:
        return None, "stopped"
    statuses = [c["properties"].get("diablo_contact_status") or "" for c in contacts]
    if any(s in ("replied", "interested", "not_interested", "opted_out") for s in statuses):
        return None, "stopped"
    if "queued" in statuses:
        return None, "waiting"
    for c in contacts:
        if (c["properties"].get("diablo_contact_status") or "") == "sent":
            first = parse_time(c["properties"].get("diablo_last_event_at"))
            if first is None or now - first < dt.timedelta(days=gap_days):
                return None, "waiting"
    approved = sorted((c for c in contacts if c["properties"].get("diablo_contact_status") == "approved_to_send"),
                      key=rank_of)
    if approved:
        return approved[0], "next"
    if any(s in NOT_YET_APPROVED for s in statuses):
        return None, "waiting_for_gate_2"
    if any(s in TRIED for s in statuses):
        return None, "no_reply"
    return None, "nothing"


def last_campaign(contacts):
    """The Instantly campaign the company's earlier contacts went to, if any."""
    for c in sorted(contacts, key=rank_of, reverse=True):
        campaign = c["properties"].get("diablo_instantly_campaign_id")
        if campaign:
            return campaign
    return None


def lead_for(contact, company, market):
    p = contact["properties"]
    return {
        "email": p["email"],
        "first_name": p.get("firstname") or "",
        "last_name": p.get("lastname") or "",
        "company_name": company.get("name") or "",
        "job_title": p.get("jobtitle") or "",
        "website": company.get("domain") or "",
        "custom_variables": {
            "subject_line": p.get("diablo_subject_line") or "",
            "personal_line": p.get("diablo_personal_line") or "",
            "market": market,
        },
    }
