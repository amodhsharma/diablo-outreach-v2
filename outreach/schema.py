"""The data contract: every HubSpot field the outreach pipeline reads or writes (agreed 13 Oct 2026).

The pipeline uses the live account's own fields wherever one fits, and adds only two:

    Contacts: Outreach personal line, Outreach order.

Everything else is an existing field:

    Lead Source     "AUTO-OUTREACH" on every company and contact the pipeline creates. The
                    pipeline never changes a record without it (see hubspot_client.TagGuard).
    Lead Status     where the record is in the pipeline (see stages.py). Three choices are added:
                    companies "GATE1: Approved for outreach" (gate 1); contacts "New, Personal line filled" and
                    "GATE2: Approved to send" (gate 2). The existing choices are never changed.
    Industry Type   the company's Channel, using its existing choices.
    Ideal Customer Profile Tier, Company name, Domain, City, Country, Company owner,
    First name, Last name, Email, Job title.

In the live account Lead Source and Industry Type already exist. In a test account they are
created to match live exactly, so tests behave as live will.
"""

GROUP_NAME = "diablo_outreach"
GROUP_LABEL = "Diablo outreach"

# The tag. Every record the pipeline creates carries it; nothing without it is ever changed.
TAG_PROPERTY = "lead_source"
TAG = "AUTO-OUTREACH"

LEAD_STATUS = "hs_lead_status"
INDUSTRY_TYPE = "industry_type"
TIER = "hs_ideal_customer_profile"
PERSONAL_LINE = "diablo_personal_line"
COMPANY_NOTE = "diablo_company_note"
ORDER = "diablo_outreach_order"
CONTACT_SOURCE = "diablo_contact_source"
# Why the pipeline stopped emailing a contact or company (19 Oct 2026), e.g. "Opted out: on
# Instantly's blocklist (19 Oct 2026)". Written only where button 1 has created the field.
STOP_REASON = "diablo_stop_reason"
# Where a contact came from (19 Oct 2026): a person found in Apollo, or the company's own contact
# address from its website when Apollo held nobody. Company inboxes also carry this job title, so
# they are recognised even before the field exists in an account.
SOURCE_APOLLO, SOURCE_WEBSITE = "Apollo", "Company website"
INBOX_TITLE = "Company inbox (from website)"


def text(name, label, description, group=GROUP_NAME):
    return {"name": name, "label": label, "type": "string", "fieldType": "text",
            "description": description, "groupName": group}


def long_text(name, label, description):
    return {"name": name, "label": label, "type": "string", "fieldType": "textarea",
            "description": description, "groupName": GROUP_NAME}


def number(name, label, description):
    return {"name": name, "label": label, "type": "number", "fieldType": "number",
            "description": description, "groupName": GROUP_NAME}


def dropdown(name, label, description, options, group):
    return {"name": name, "label": label, "type": "enumeration", "fieldType": "select",
            "description": description, "groupName": group,
            "options": [{"label": lab, "value": val, "displayOrder": i} for i, (val, lab) in enumerate(options)]}


# Industry Type exactly as in the live account (value, label).
INDUSTRY_TYPES = (
    ("Grocery Retail", "Grocery Retail (e.g. Tesco/Aldi)"),
    ("Convenience Impulse", "Convenience & Impulse (E.g. BP, Spar)"),
    ("Specialist retail", "Specialist retail (E.g Pharmacy, health shop)"),
    ("Distributor Wholesaler", "Distributor / Wholesaler"),
    ("Foodservice Catering", "Foodservice & Catering (E.g Café, Airline, Hotel)"),
    ("Online Retailer", "Online Retailer"),
    ("Other", "Other"),
)

# The new fields (contacts only; the company note was added on 15 Oct 2026 and the contact source on
# 19 Oct 2026), created in the "Diablo outreach" group.
NEW_PROPERTIES = {
    "companies": [
        text(STOP_REASON, "Outreach stopped because",
             "Why the pipeline stopped emailing this company, e.g. \"A contact opted out (19 Oct 2026)\" "
             "(added 19 Oct 2026)."),
    ],
    "contacts": [
        long_text(PERSONAL_LINE, "Outreach personal line",
                  "The tailored opening line for this person's first email. Read it before setting "
                  "Lead Status to GATE2: Approved to send (gate 2)."),
        long_text(COMPANY_NOTE, "Outreach company note",
                  "What we noticed about the company, finishing the first email's sentence \"I thought "
                  "I'd reach out as we noticed <company> ...\" (added 15 Oct 2026). Read it before "
                  "setting Lead Status to GATE2: Approved to send (gate 2)."),
        number(ORDER, "Outreach order",
               "Who at the company is emailed first: 1 = most senior found, then 2, 3 and 4."),
        dropdown(CONTACT_SOURCE, "Outreach contact source",
                 "Apollo (a person) or Company website (the company's own contact address, used when "
                 "Apollo held nobody; added 19 Oct 2026).",
                 ((SOURCE_APOLLO, SOURCE_APOLLO), (SOURCE_WEBSITE, SOURCE_WEBSITE)), group=GROUP_NAME),
        text(STOP_REASON, "Outreach stopped because",
             "Why the pipeline stopped emailing this person, e.g. \"Opted out: on Instantly's blocklist "
             "(19 Oct 2026)\" or \"A colleague opted out (19 Oct 2026)\" (added 19 Oct 2026)."),
    ],
}

# Fields the live account already has. In a test account they are created to match live;
# where they exist they are only checked, never changed (missing dropdown choices are added).
MIRRORED_PROPERTIES = {
    "companies": [
        text(TAG_PROPERTY, "Lead Source", "", group="companyinformation"),
        dropdown(INDUSTRY_TYPE, "Industry Type", "", INDUSTRY_TYPES, group="companyinformation"),
    ],
    "contacts": [
        text(TAG_PROPERTY, "Lead source", "", group="contactinformation"),
    ],
}

# Every field created or checked, per object (used by the setup and its dry run).
PROPERTIES = {obj: MIRRORED_PROPERTIES[obj] + NEW_PROPERTIES[obj] for obj in ("companies", "contacts")}
