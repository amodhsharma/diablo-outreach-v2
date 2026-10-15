"""One loop per company, one person at a time (agreed 14 Oct 2026).

Up to 4 approved contacts per company, most senior first, every email at least 3 days after the
company's previous one (send.next_contact_after_days):

    Person 1   the introduction (Instantly campaign)
    Person 2   a forward of the latest email in the chain, naming the colleague before them
    Person 3   the same, naming person 2 (and person 4, if there is one)
    Person 1   one reminder, as a reply in their own thread, at least 7 days after their
               introduction (send.rotation.min_days_same_person). This is the last email.

Persons 2 to 4 get one email each and nothing more. 3 days after the last email with no reply,
the company becomes Unqualified. The moment anyone at the company replies or opts out, everyone
there stops.

Where each person is comes from two places: their Lead Status in HubSpot (gate 2, replies, dead
ends) and Instantly itself (the campaign, and the emails sent and received in each thread), so
HubSpot needs no extra fields for it.
"""

import datetime as dt

from .common import INDUSTRY_PARTNER
from .schema import COMPANY_NOTE, LEAD_STATUS, ORDER, PERSONAL_LINE
from .stages import COMPANY_STOPPED, EMAILED

CONTACT_PROPS = ["email", "firstname", "lastname", "jobtitle", PERSONAL_LINE, COMPANY_NOTE, LEAD_STATUS, ORDER]
COMPANY_PROPS = ["name", "domain", "city", "country", "industry_type", LEAD_STATUS]

# Each contact's state, worked out from its Lead Status and what Instantly holds (instantly_view):
#   pending   New or "New, Personal line filled": not through gate 2 yet
#   approved  GATE2: Approved to send: waiting for its turn
#   queued    in Instantly, first email not sent yet
#   sent      emailed, no reply
#   bounced   the email bounced (the company carries on with the others)
#   skipped   set to Unqualified before being emailed (rejected at gate 2): left out
#   stop      replied, opted out, not interested, or taken over by a person: the company stops
STOP = "stop"


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
    value = str(contact["properties"].get(ORDER) or "")
    try:
        return int(float(value))
    except ValueError:
        return 999


def instantly_view(instantly, prefix):
    """{email: Instantly lead} for every lead in the Diablo campaigns, each with _campaign_id."""
    if instantly is None:
        return {}
    view = {}
    for c in instantly.list_campaigns():
        if not (c.get("name") or "").startswith(prefix):
            continue
        for lead in instantly.list_leads(c["id"]):
            if lead.get("email"):
                view[lead["email"].lower()] = dict(lead, _campaign_id=c["id"])
    return view


def contact_state(contact, statuses, leads):
    stage = statuses.of("contacts", contact)
    lead = leads.get((contact["properties"].get("email") or "").lower())
    if stage in ("", "found", "copy_ready"):
        return "pending"
    if stage == "approved":
        return "approved"
    if stage in EMAILED + ("closed",) and lead is not None and lead.get("status") == -1:
        return "bounced"
    if stage in EMAILED:
        return "sent" if lead and lead.get("timestamp_last_contact") else "queued"
    if stage == "closed" and lead is None:
        return "skipped"
    return STOP  # replied, closed (opted out or not interested) or a person's own Lead Status


def annotate(contacts, statuses, leads):
    """Add each contact's state, first email time and Instantly campaign (in place)."""
    for c in contacts:
        lead = leads.get((c["properties"].get("email") or "").lower()) or {}
        c["state"] = contact_state(c, statuses, leads)
        c["sent_at"] = parse_time(lead.get("timestamp_last_contact"))
        c["campaign"] = lead.get("_campaign_id")
    return contacts


def mark_sent(contacts, touches):
    """A person reached by a forward is not a campaign lead, so Instantly's lead list does not show
    them as emailed; their thread does. Mark them sent when it does (in place)."""
    for c in contacts:
        if c.get("state") == "queued" and (touches or {}).get(c["id"]):
            c["state"] = "sent"
    return contacts


def tagged_company_of(hs, contact_ids, properties):
    """({contact id: company id}, {company id: company record}) using, for each contact, the first
    linked company that carries the AUTO-OUTREACH tag. HubSpot may also link a contact to another
    company by itself (by email domain); that company is ignored and never changed."""
    links = hs.associated_ids("contacts", "companies", list(contact_ids)) if contact_ids else {}
    ids = sorted({c for cs in links.values() for c in cs})
    companies = {str(c["id"]): c for c in hs.tagged_read("companies", ids, properties)} if ids else {}
    chosen = {}
    for contact_id, cs in links.items():
        ours = [c for c in cs if c in companies]
        if ours:
            chosen[str(contact_id)] = ours[0]
    return chosen, companies


def contacts_by_company(hs, company_ids):
    """{company id: [AUTO-OUTREACH contact records]} for these companies."""
    links = hs.associated_ids("companies", "contacts", company_ids)
    ids = sorted({c for cs in links.values() for c in cs})
    records = {r["id"]: r for r in hs.tagged_read("contacts", ids, CONTACT_PROPS)} if ids else {}
    return {cid: [records[c] for c in cs if c in records] for cid, cs in links.items()}


TEST_GAP_MINUTES = 15


def apply_test_gaps(settings, target, typed):
    """Button 3's test box (agreed 14 Oct 2026): when "CONFIRM" is typed, the gaps between emails
    (3 days between people, 7 days for the same person) become 15 minutes for this one run.
    Refused for the live account. Returns True when the test gaps are on."""
    from .common import PipelineError
    typed = (typed or "").strip()
    if not typed:
        return False
    if typed != "CONFIRM":
        raise PipelineError(f'Test gaps: type CONFIRM exactly (in capitals) to use them; "{typed}" was typed. '
                            "Nothing was done.")
    if target != "test":
        raise PipelineError("Test gaps are refused for the live HubSpot account. Nothing was done.")
    gap = TEST_GAP_MINUTES / (24 * 60)
    send = settings["send"]
    send["next_contact_after_days"] = gap
    send.setdefault("rotation", {})["min_days_same_person"] = gap
    send["test_gaps"] = True
    return True


def touch_times(contact, touches=None):
    """When this contact was emailed: every sent time from Instantly's email history if known,
    else the time of their latest email from the campaign."""
    if touches is not None and touches.get(contact["id"]):
        return sorted(touches[contact["id"]])
    return [contact["sent_at"]] if contact.get("sent_at") else []


def decide(contacts, company_stage, gap_days, now=None, touches=None, min_same_days=7):
    """(the contact to email next or None, why). Contacts must be annotated (see annotate). why is
    one of: next (person 1's introduction, through the campaign), forward (the next person, a
    forward of the chain), reminder (person 1's one reminder, a reply in their thread), stopped,
    waiting, waiting_for_gate_2, waiting_same_person, waiting_for_emails_key, no_reply, nothing.

    touches: {contact id: [times they were emailed]} from Instantly, or None when unknown."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if company_stage in COMPANY_STOPPED:
        return None, "stopped"
    states = [c["state"] for c in contacts]
    if STOP in states:
        return None, "stopped"
    if "queued" in states:
        return None, "waiting"
    reached = [c for c in contacts if c["state"] in ("sent", "bounced") and touch_times(c, touches)]
    emailed = [c for c in contacts if c["state"] == "sent"]
    times = [t for c in reached for t in touch_times(c, touches)]
    if emailed and not times:
        return None, "waiting"
    if times and now - max(times) < dt.timedelta(days=gap_days):
        return None, "waiting"
    approved = sorted((c for c in contacts if c["state"] == "approved"), key=rank_of)
    if approved:
        if not emailed:  # nobody reached yet (or only a bounced address): the introduction
            return approved[0], "next"
        if touches is None:
            return None, "waiting_for_emails_key"
        return approved[0], "forward"
    if "pending" in states:
        return None, "waiting_for_gate_2"
    if not emailed:
        return (None, "no_reply") if "bounced" in states else (None, "nothing")
    if touches is None:
        return None, "waiting_for_emails_key"
    # The loop is done: one reminder to person 1 (the first person emailed), then the end.
    first = min((c for c in emailed if touch_times(c, touches)), key=lambda c: touch_times(c, touches)[0])
    if len(touch_times(first, touches)) < 2:
        if now - touch_times(first, touches)[0] < dt.timedelta(days=min_same_days):
            return None, "waiting_same_person"
        return first, "reminder"
    return None, "no_reply"


def last_campaign(contacts):
    """The Instantly campaign the company's earlier contacts went to, if any."""
    for c in sorted(contacts, key=rank_of, reverse=True):
        if c.get("campaign"):
            return c["campaign"]
    return None


PARTNER_TYPES = {"distributors": "distributor", "wholesalers": "wholesaler", "retailers": "retailer",
                 "marketplace sellers": "online seller", "importers": "importer"}


def partner_type(channel):
    """The Channel as one word for the email ("your reputation as a premier distributor")."""
    if channel in INDUSTRY_PARTNER:  # an Industry Type value, when the research Channel is unknown
        return INDUSTRY_PARTNER[channel]
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


def country_name(market):
    """The country of the Location as a plain name, for template 3's subject: "A sugar-free brand
    with no Netherlands partner yet" (no "the" in front)."""
    return (market or "").split(",")[-1].strip()


def lead_for(contact, company, notes=None):
    """The Instantly lead for a contact. company: the company's HubSpot properties."""
    from .common import channel_of, market_of
    p = contact["properties"]
    market = market_of(company) or "Unknown"
    return {
        "email": p["email"],
        "first_name": p.get("firstname") or "",
        "last_name": p.get("lastname") or "",
        "company_name": company.get("name") or "",
        "job_title": p.get("jobtitle") or "",
        "website": company.get("domain") or "",
        "custom_variables": {
            "personal_line": p.get(PERSONAL_LINE) or "",
            "company_note": (p.get(COMPANY_NOTE) or "").strip().rstrip("."),
            "country_name": country_name(market),
            "market": market,
            "market_short": market_short(market),
            "market_country": market_country(market),
            "partner_type": partner_type(channel_of(company, notes)),
        },
    }
