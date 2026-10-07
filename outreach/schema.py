"""The data contract: every HubSpot field the outreach pipeline reads or writes.

All fields live in one property group ("Diablo outreach") on companies and
contacts, and every internal name starts with "diablo_" so they never clash
with fields other people already use. HubSpot's own fields (Company name,
Domain, City, Country) are filled too. Research details used to write the
emails are kept in data/company_notes.json in the repository, not in HubSpot.
"""

GROUP_NAME = "diablo_outreach"
GROUP_LABEL = "Diablo outreach"


def _options(*labels):
    """Turn display labels into HubSpot enumeration options."""
    return [
        {
            "label": label,
            "value": label.lower().replace(" ", "_"),
            "displayOrder": i,
        }
        for i, label in enumerate(labels)
    ]


def text(name, label, description, unique=False):
    return {
        "name": name,
        "label": label,
        "type": "string",
        "fieldType": "text",
        "description": description,
        "hasUniqueValue": unique,
    }


def long_text(name, label, description):
    return {
        "name": name,
        "label": label,
        "type": "string",
        "fieldType": "textarea",
        "description": description,
    }


def number(name, label, description):
    return {
        "name": name,
        "label": label,
        "type": "number",
        "fieldType": "number",
        "description": description,
    }


def choice(name, label, description, *labels):
    return {
        "name": name,
        "label": label,
        "type": "enumeration",
        "fieldType": "select",
        "description": description,
        "options": _options(*labels),
    }


def yes_no(name, label, description):
    return {
        "name": name,
        "label": label,
        "type": "bool",
        "fieldType": "booleancheckbox",
        "description": description,
        "options": [
            {"label": "Yes", "value": "true", "displayOrder": 0},
            {"label": "No", "value": "false", "displayOrder": 1},
        ],
    }


def date_time(name, label, description):
    return {
        "name": name,
        "label": label,
        "type": "datetime",
        "fieldType": "date",
        "description": description,
    }


# Starting options for the dropdown. Research accepts any typed category and adds it.
CHANNEL_CATEGORIES = (
    "Health food distributor",
    "Convenience and impulse distributor",
    "Grocery wholesaler",
    "Pharmacy distributor",
)

# Gate 1 happens on the company status: research sets "Awaiting review",
# a person changes it to "Approved" or "Rejected".
COMPANY_STATUSES = (
    "Awaiting review",
    "Approved",
    "Rejected",
    "No domain",
    "Suppressed",
    "Contacts found",
    "No contacts found",
    "In outreach",
    "Replied",
    "Interested",
    "Not interested",
)

# Gate 2 happens on the contact status: personalisation sets "Copy ready",
# a person changes it to "Approved to send".
CONTACT_STATUSES = (
    "Contact found",
    "Copy ready",
    "Approved to send",
    "Queued",
    "Sent",
    "Replied",
    "Interested",
    "Not interested",
    "Bounced",
    "Opted out",
)

SUPPRESS_REASONS = (
    "Existing partner",
    "In negotiation",
    "Customer",
    "Opted out",
    "Competitor",
    "Other",
)

COMPANY_PROPERTIES = [
    text("diablo_market", "Outreach market", "Market the company was researched for: a country, region or city, e.g. India or Mumbai, India."),
    choice(
        "diablo_channel_category",
        "Outreach channel category",
        "Channel category typed into the research job. New categories are added to this dropdown automatically.",
        *CHANNEL_CATEGORIES,
    ),
    choice("diablo_tier", "Outreach tier", "Fit tier from the research run.", "Tier 1", "Tier 2", "Tier 3"),
    choice(
        "diablo_outreach_status",
        "Outreach company status",
        "Where the company is in the pipeline. Change Awaiting review to Approved or Rejected (gate 1).",
        *COMPANY_STATUSES,
    ),
    choice(
        "diablo_suppress_reason",
        "Outreach suppress reason",
        "Set this to stop all outreach to the company.",
        *SUPPRESS_REASONS,
    ),
]

CONTACT_PROPERTIES = [
    text("diablo_market", "Outreach market", "Market of the company this contact works for."),
    choice(
        "diablo_contact_status",
        "Outreach contact status",
        "Where the contact is in the pipeline. Change Copy ready to Approved to send (gate 2).",
        *CONTACT_STATUSES,
    ),
    text("diablo_email_status", "Outreach email status", "Email verification status from Apollo. Only Verified is sent."),
    text("diablo_apollo_id", "Outreach Apollo ID", "Apollo person ID, used to avoid duplicates on reruns."),
    number(
        "diablo_hierarchy_rank",
        "Outreach hierarchy rank",
        "Seniority rank inside the company, 1 = most senior found.",
    ),
    text("diablo_hierarchy_level", "Outreach hierarchy level", "Seniority level from settings, e.g. Top leadership, Directors."),
    text("diablo_subject_line", "Outreach subject line", "Personalised subject line, approved at gate 2."),
    long_text("diablo_personal_line", "Outreach personal line", "Personalised opening line, approved at gate 2."),
    text("diablo_instantly_campaign_id", "Outreach Instantly campaign ID", "Instantly campaign the contact was added to."),
    text("diablo_instantly_lead_id", "Outreach Instantly lead ID", "Instantly lead ID, used to match events."),
    text("diablo_last_event", "Outreach last event", "Latest Instantly event, e.g. reply_received."),
    date_time("diablo_last_event_at", "Outreach last event at", "When the latest Instantly event happened."),
]

PROPERTIES = {
    "companies": COMPANY_PROPERTIES,
    "contacts": CONTACT_PROPERTIES,
}
