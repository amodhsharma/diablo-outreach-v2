"""Where a company or contact is in the pipeline, kept in HubSpot's own Lead Status (agreed 13 Oct 2026).

This is the only place that knows the Lead Status wording. Each pipeline step has a stage name;
the table below gives the Lead Status choice for it, by its label. Values are looked up in the
account itself, so the code works whatever the account calls a choice internally.

    Step                                         Company                 Contact
    Research found it / contact found            New                     New
    No website, or no contacts found             Missing Info
    Gate 1: a person approves the company        Approved for outreach
    Email lines written                                                  Copy ready
    Gate 2: a person approves the wording                                Approved to send
    Emails going out                             Attempted to Contact    Attempted to Contact
    They replied                                 In Progress             In Progress
    Any dead end (rejected, not interested,      Unqualified             Unqualified
    no reply, opted out, bounced)

Any other Lead Status (for example Emailed or Won) means a person has taken the record over:
the pipeline treats it as "team" and stops.
"""

from .common import PipelineError
from .schema import LEAD_STATUS

STAGES = {
    "companies": {
        "found": "New",
        "missing_info": "Missing Info",
        "approved": "Approved for outreach",
        "in_outreach": "Attempted to Contact",
        "replied": "In Progress",
        "closed": "Unqualified",
    },
    "contacts": {
        "found": "New",
        "copy_ready": "Copy ready",
        "approved": "Approved to send",
        "in_outreach": "Attempted to Contact",
        "replied": "In Progress",
        "closed": "Unqualified",
    },
}

# The internal value given to a choice when the setup has to add it (matching the live
# account's style: companies use the label itself, contacts use capitals).
NEW_OPTION_VALUES = {
    "companies": {"Approved for outreach": "Approved for outreach", "Missing Info": "Missing Info",
                  "New": "New", "Attempted to Contact": "Attempted to Contact",
                  "In Progress": "In Progress", "Unqualified": "Unqualified"},
    "contacts": {"Copy ready": "COPY_READY", "Approved to send": "APPROVED_TO_SEND", "New": "NEW",
                 "Attempted to Contact": "ATTEMPTED_TO_CONTACT", "In Progress": "IN_PROGRESS",
                 "Unqualified": "UNQUALIFIED"},
}

# Later stages win: a status only ever moves forward.
ORDER = {"": 0, "found": 0, "missing_info": 0, "copy_ready": 0, "approved": 0,
         "in_outreach": 1, "replied": 2, "closed": 3}
TEAM = "team"


class LeadStatus:
    """Lead Status choices of one HubSpot account, read once."""

    def __init__(self, hs):
        self._value = {}
        self._stage = {}
        for obj, stages in STAGES.items():
            labels = hs.option_labels(obj, LEAD_STATUS)  # {value: label}
            by_label = {str(label).strip().lower(): value for value, label in labels.items()}
            self._value[obj] = {}
            self._stage[obj] = {}
            for stage, label in stages.items():
                value = by_label.get(label.lower())
                if value is not None:
                    self._value[obj][stage] = value
                    self._stage[obj][str(value).lower()] = stage

    def value(self, obj, stage):
        try:
            return self._value[obj][stage]
        except KeyError:
            label = STAGES[obj][stage]
            raise PipelineError(
                f'HubSpot\'s {obj[:-1]} Lead Status has no "{label}" choice. Run button 1 '
                '("One-time setup") for this account, which adds it.') from None

    def stage(self, obj, value):
        """The pipeline stage for a stored Lead Status value: "" when empty, "team" when it is a
        choice the pipeline does not use (a person has taken the record over)."""
        if value in (None, ""):
            return ""
        return self._stage[obj].get(str(value).lower(), TEAM)

    def of(self, obj, record_or_props):
        props = record_or_props.get("properties", record_or_props)
        return self.stage(obj, props.get(LEAD_STATUS))

    def filter(self, obj, stage):
        return {"propertyName": LEAD_STATUS, "operator": "EQ", "value": self.value(obj, stage)}

    def props(self, obj, stage):
        return {LEAD_STATUS: self.value(obj, stage)}


def forward(old_stage, new_stage):
    """True when moving from old_stage to new_stage is a step forward. A record a person has
    taken over ("team") is never changed."""
    if old_stage == TEAM:
        return False
    return ORDER.get(new_stage, 0) > ORDER.get(old_stage, 0)


# A company in one of these stages gets no more emails.
COMPANY_STOPPED = {"replied", "closed", TEAM}
