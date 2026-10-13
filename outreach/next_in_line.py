"""One person per company at a time, in turn (agreed 13 Oct 2026).

Up to 4 approved contacts per company, most senior first. Every email to a company is at
least 3 days after the previous one (send.next_contact_after_days):

    Person 1, Person 2, Person 3, Person 4 (first emails), then back to Person 1 for a
    reminder in the same thread, Person 2, ... and so on for send.rotation.rounds rounds.

Nobody gets a second or third email less than 7 days after their previous one
(send.rotation.min_days_same_person): if the company has fewer people, the next email simply
waits until the 7 days are up. The moment anyone at the company replies or opts out, everyone
there stops. After the last round with no reply the company is marked "No reply".

First emails go through Instantly (4b adds the lead; Sync adds the next person). The 2nd and
3rd emails are sent by Sync as replies in the person's own thread (Instantly's reply feature,
key INSTANTLY_EMAILS_KEY).
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


def touch_times(contact, touches=None):
    """When this contact was emailed: the sent times from Instantly if known, else the time of
    their first email recorded in HubSpot."""
    if touches is not None and touches.get(contact["id"]):
        return sorted(touches[contact["id"]])
    first = parse_time(contact["properties"].get("diablo_last_event_at"))
    return [first] if first else []


def decide(contacts, company_status, gap_days, now=None, touches=None, rounds=1, min_same_days=7):
    """(the contact to email next or None, why). why is one of:
    next (their first email), follow_up (their next email, a reply in their thread), stopped,
    waiting, waiting_for_gate_2, waiting_same_person, waiting_for_emails_key, no_reply, nothing.

    touches: {contact id: [times they were emailed]} from Instantly, or None when unknown."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if (company_status or "") in STOPPED:
        return None, "stopped"
    statuses = [c["properties"].get("diablo_contact_status") or "" for c in contacts]
    if any(s in ("replied", "interested", "not_interested", "opted_out") for s in statuses):
        return None, "stopped"
    if "queued" in statuses:
        return None, "waiting"
    emailed = sorted((c for c in contacts if (c["properties"].get("diablo_contact_status") or "") == "sent"),
                     key=rank_of)
    times = [t for c in emailed for t in touch_times(c, touches)]
    if emailed and (not times or now - max(times) < dt.timedelta(days=gap_days)):
        return None, "waiting"
    approved = sorted((c for c in contacts if c["properties"].get("diablo_contact_status") == "approved_to_send"),
                      key=rank_of)
    if approved:
        return approved[0], "next"
    if any(s in NOT_YET_APPROVED for s in statuses):
        return None, "waiting_for_gate_2"
    if not emailed:
        return (None, "no_reply") if any(s in TRIED for s in statuses) else (None, "nothing")
    if rounds <= 1:
        return None, "no_reply"
    if touches is None:
        return None, "waiting_for_emails_key"
    counts = {c["id"]: max(len(touch_times(c, touches)), 1) for c in emailed}
    lowest = min(counts.values())
    if lowest >= rounds:
        return None, "no_reply"
    person = next(c for c in emailed if counts[c["id"]] == lowest)
    if now - touch_times(person, touches)[-1] < dt.timedelta(days=min_same_days):
        return None, "waiting_same_person"
    return person, "follow_up"


def last_campaign(contacts):
    """The Instantly campaign the company's earlier contacts went to, if any."""
    for c in sorted(contacts, key=rank_of, reverse=True):
        campaign = c["properties"].get("diablo_instantly_campaign_id")
        if campaign:
            return campaign
    return None


PARTNER_TYPES = {"distributors": "distributor", "wholesalers": "wholesaler", "retailers": "retailer",
                 "marketplace sellers": "online seller", "importers": "importer"}


def partner_type(channel):
    """The Channel as one word for the email ("your reputation as a premier distributor")."""
    channel = (channel or "").strip().lower()
    if channel in PARTNER_TYPES:
        return PARTNER_TYPES[channel]
    if channel.endswith("s") and len(channel) > 3:
        return channel[:-1]
    return channel or "partner"


def market_short(market):
    """The first part of the Location for the subject line: "Dublin, Ireland" gives "Dublin"."""
    return (market or "").split(",")[0].strip() or market or ""


WITH_THE = ("United ", "Netherlands", "Czech Republic", "Philippines", "Dominican Republic", "Bahamas",
            "Gambia", "Maldives", "Republic of", "Democratic Republic", "Central African Republic",
            "Solomon Islands", "Marshall Islands", "Cayman Islands", "Faroe Islands", "British Virgin Islands")


def market_country(market):
    """The country of the Location for the email, with "the" where English needs it:
    "Amsterdam, Netherlands" gives "the Netherlands", "Dublin, Ireland" gives "Ireland"."""
    country = (market or "").split(",")[-1].strip()
    if country in ("UK", "USA", "US", "UAE"):
        return "the " + country
    return "the " + country if country.startswith(WITH_THE) else country


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
            "market_short": market_short(market),
            "market_country": market_country(market),
            "partner_type": partner_type(company.get("diablo_channel_category")),
        },
    }
