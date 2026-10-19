"""Where a company or contact is in the pipeline, kept in HubSpot's own Lead Status (agreed 13 Oct 2026).

This is the only place that knows the Lead Status wording. Each pipeline step has a stage name;
the table below gives the Lead Status choice for it, by its label. Values are looked up in the
account itself, so the code works whatever the account calls a choice internally.

    Step                                       Company                       Contact
    Research found it / contact found          New                           New
    No website, or no contacts found           Missing Info
    Gate 1: a person approves the company      GATE1: Approved for outreach
    Email lines written                                                      "New, Personal line filled"
    Gate 2: a person approves the wording                                    GATE2: Approved to send
    Emails going out                           Attempted to Contact          Attempted to Contact
    Forward sent to a colleague (persons 2-4)                                Forward sent
    Person 1's one reminder sent                                             Reminder sent
    They replied                               In Progress                   In Progress
    Any dead end (rejected, not interested,    Unqualified                   Unqualified
    no reply, opted out, bounced)
    A colleague at the company answered for                                  "Colleague replied: positive",
    everyone (19 Oct 2026): the others are                                   "Colleague replied: negative" or
    never emailed and show what happened                                     "Colleague replied"

Any other Lead Status (for example Emailed or Won) means a person has taken the record over:
the pipeline treats it as "team" and stops.
"""

from .common import PipelineError
from .schema import LEAD_STATUS

STAGES = {
    "companies": {
        "found": "New",
        "missing_info": "Missing Info",
        "approved": "GATE1: Approved for outreach",
        "in_outreach": "Attempted to Contact",
        "replied": "In Progress",
        "closed": "Unqualified",
    },
    "contacts": {
        "found": "New",
        "copy_ready": "New, Personal line filled",
        "approved": "GATE2: Approved to send",
        "in_outreach": "Attempted to Contact",
        "forwarded": "Forward sent",
        "reminded": "Reminder sent",
        "replied": "In Progress",
        "closed": "Unqualified",
        # The rest of a company once someone there has answered (agreed 19 Oct 2026).
        "colleague_positive": "Colleague replied: positive",
        "colleague_negative": "Colleague replied: negative",
        "colleague_replied": "Colleague replied",
    },
}
COLLEAGUE_STAGES = ("colleague_positive", "colleague_negative", "colleague_replied")
# Contact stages that mean "emailed, no reply yet" (agreed 14 Oct 2026: the forward and the
# reminder get their own Lead Status so they can be checked in HubSpot).
EMAILED = ("in_outreach", "forwarded", "reminded")

# The internal value given to a choice when the setup has to add it (matching the live
# account's style: companies use the label itself, contacts use capitals).
NEW_OPTION_VALUES = {
    "companies": {"GATE1: Approved for outreach": "GATE1: Approved for outreach", "Missing Info": "Missing Info",
                  "New": "New", "Attempted to Contact": "Attempted to Contact",
                  "In Progress": "In Progress", "Unqualified": "Unqualified"},
    "contacts": {"New, Personal line filled": "NEW_PERSONAL_LINE_FILLED", "GATE2: Approved to send": "APPROVED_TO_SEND", "New": "NEW",
                 "Attempted to Contact": "ATTEMPTED_TO_CONTACT", "Forward sent": "FORWARD_SENT",
                 "Reminder sent": "REMINDER_SENT", "In Progress": "IN_PROGRESS",
                 "Unqualified": "UNQUALIFIED", "Colleague replied: positive": "COLLEAGUE_REPLIED_POSITIVE",
                 "Colleague replied: negative": "COLLEAGUE_REPLIED_NEGATIVE",
                 "Colleague replied": "COLLEAGUE_REPLIED"},
}

# Later stages win: a status only ever moves forward.
ORDER = {"": 0, "found": 0, "missing_info": 0, "copy_ready": 0, "approved": 0,
         "in_outreach": 1, "forwarded": 1, "reminded": 1.5, "replied": 2, "closed": 3,
         "colleague_positive": 2, "colleague_negative": 2, "colleague_replied": 2}
TEAM = "team"


class LeadStatus:
    """Lead Status choices of one HubSpot account, read once."""

    def __init__(self, hs):
        self._value = {}
        self._stage = {}
        self._labels = {}
        for obj, stages in STAGES.items():
            labels = hs.option_labels(obj, LEAD_STATUS)  # {value: label}
            self._labels[obj] = {str(v).lower(): l for v, l in labels.items()}
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
                '("1 - Setup HubSpot") for this account, which adds it.') from None

    def stage(self, obj, value):
        """The pipeline stage for a stored Lead Status value: "" when empty, "team" when it is a
        choice the pipeline does not use (a person has taken the record over)."""
        if value in (None, ""):
            return ""
        return self._stage[obj].get(str(value).lower(), TEAM)

    def of(self, obj, record_or_props):
        props = record_or_props.get("properties", record_or_props)
        return self.stage(obj, props.get(LEAD_STATUS))

    def label(self, obj, value):
        """The label HubSpot shows for a stored Lead Status value (e.g. "Forward sent")."""
        return self._labels.get(obj, {}).get(str(value or "").lower(), value or "")

    def has(self, obj, stage):
        return stage in self._value.get(obj, {})

    def props_or(self, obj, stage, fallback):
        """The props for a stage, or for the fallback stage when the account lacks that choice
        (for example before button 1 has added "Forward sent")."""
        return self.props(obj, stage if self.has(obj, stage) else fallback)

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
