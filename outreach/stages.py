"""Where a company or contact is in the pipeline, kept in HubSpot's own Lead Status (agreed 13 Oct 2026).

This is the only place that knows the Lead Status wording. Each pipeline step has a stage name;
the table below gives the Lead Status choice for it, by its label. Values are looked up in the
account itself, so the code works whatever the account calls a choice internally.

    Step                                       Company                       Contact
    Research found it / contact found          New                           New
    No website, or no contact found anywhere   Missing Info
    by button 3
    Button 3 found only contacts already in    Contact exists, not AUTO-OUTREACH
    HubSpot (26 Oct 2026)
    Apollo holds nobody and the website no     Missing info on Apollo
    usable address (23 Oct 2026): set it to
    GATE1 and button 3 searches everywhere
    Gate 1: a person approves the company      GATE1: Approved for outreach
    It has at least 1 AUTO-OUTREACH contact    Contact located. Queued for
    (10 Nov 2026), until the first email       processing
    Email lines written                                                      "New, Personal line filled"
    Gate 2: a person approves the wording                                    GATE2: Approved to send
    Emails going out                           Attempted to Contact          Attempted to Contact
    Forward sent to a colleague (persons 2-4)                                Forward sent
    Person 1's one reminder sent                                             Reminder sent
    They replied                               In Progress                   In Progress
    A colleague replied (19 Oct 2026)                                        "Colleague replied: positive"
                                                                             or "Colleague replied"

The dead ends (agreed 2 Nov 2026, Ariel). Columns: the company, the person emailed, the others there.

    You rejected it          Unqualified                  Unqualified company          Unqualified company
    The person said no       Unqualified: Employee        Unqualified: Response        Unqualified: Colleague
                             response negative            negative                     response negative
    The person opted out     Unqualified: Employee        Unqualified: Opted-out/      Unqualified: Colleague
    (unsubscribed, on the    Opted-out/Blocklist          Blocklist                    Opted-out/Blocklist
    blocklist, asked to stop)
    No reply after 1 week    Unqualified: Contacted,      Unqualified: Contacted,      Unqualified: Colleague
                             but no response              but no response              Contacted, but no response
    Its company inbox        Unqualified: Company inbox   Unqualified: Inbox Bounced   -
    bounced, nobody left     bounced
    A dead address, someone  Attempted to Contact         Unqualified: Contact         the next person moves up
    else is left             (unchanged)                  corrupt (Outreach order 0)   (corrupt.py)
    A dead address, nobody   Unqualified: Personal inbox  Unqualified: Contact
    left                     bounced                      corrupt
    Any other bounce         unchanged                    Unqualified: Bounced,        unchanged
    (a full mailbox)                                      other reason
    A person marks the       unchanged while someone is   Unqualified: Rejected/       the next person moves up
    contact by hand          left; with nobody left:      Redirected by company        (redirect.py)
    (on leave, redirected)   "Unqualified: One contact    owner (Outreach order 0)
                             inputted, which is
                             unavailable"

Plain "Unqualified" on a contact stays for a contact rejected at gate 2 by hand; the team's own
records outside AUTO-OUTREACH use it too and are never touched.

Any other Lead Status (for example Emailed or Won) means a person has taken the record over:
the pipeline treats it as "team" and stops.
"""

from .common import PipelineError
from .schema import LEAD_STATUS

STAGES = {
    "companies": {
        "found": "New",
        "missing_info": "Missing Info",
        # 23 Oct 2026 (Ariel): Apollo holds nobody and the website shows no usable address. A person may
        # still set it to GATE1; button 3 then searches everywhere and gives it contacts or "Missing Info".
        "missing_apollo": "Missing info on Apollo",
        # 26 Oct 2026 (Ariel): button 3 created nobody because the people it found (or the company's
        # contacts) are already in HubSpot, not tagged AUTO-OUTREACH. Tag one and the next run of button 3
        # sets the company back to GATE1 by itself.
        "contact_exists": "Contact exists, not AUTO-OUTREACH",
        "approved": "GATE1: Approved for outreach",
        # 10 Nov 2026 (Ariel): approved and has at least 1 AUTO-OUTREACH contact (a person or a company inbox);
        # it stays here while the lines are written, the contacts wait for GATE2 and their turn, until the
        # first email goes out. GATE1 now only means "approved, still waiting for people" (find_contacts.settle).
        "located": "Contact located. Queued for processing",
        "in_outreach": "Attempted to Contact",
        "replied": "In Progress",
        # 2 Nov 2026 (Ariel): plain Unqualified is now only "you rejected it".
        "closed": "Unqualified",
        "said_no": "Unqualified: Employee response negative",
        "opted_out": "Unqualified: Employee Opted-out/Blocklist",
        # 21 Oct 2026 (Ariel): the introduction got no reply in time; no follow-ups are sent.
        "no_response": "Unqualified: Contacted, but no response",
        # 28 Oct 2026 (Ariel): its company inbox bounced and nobody else is left to email.
        "invalid_inbox": "Unqualified: Company inbox bounced",
        # 2 Nov 2026 (Ariel): a person's address is dead and nobody is left to email.
        "personal_bounced": "Unqualified: Personal inbox bounced",
        # 2 Nov 2026 (Ariel): the one contact was marked Rejected/Redirected and nobody is left.
        "redirected_none": "Unqualified: One contact inputted, which is unavailable",
        # 3 Nov 2026 (Ariel): the receiving company's mail system blocks us (a policy block): its colleagues
        # would bounce too, so the company stops.
        "bounced_other": "Unqualified: Bounced, other reason",
        # 3 Nov 2026 (Ariel): a clear yes or no went to the sales team; the automation never touches it again.
        "sales": "END: Forwarded to Sales Team",
    },
    "contacts": {
        "found": "New",
        "copy_ready": "New, Personal line filled",
        "approved": "GATE2: Approved to send",
        "in_outreach": "Attempted to Contact",
        "forwarded": "Forward sent",
        "reminded": "Reminder sent",
        "replied": "In Progress",
        # 2 Nov 2026 (Ariel): plain Unqualified is now only a contact rejected at gate 2 by hand.
        "closed": "Unqualified",
        "said_no": "Unqualified: Response negative",
        "opted_out": "Unqualified: Opted-out/Blocklist",
        "bounced_other": "Unqualified: Bounced, other reason",
        # The rest of a company once someone there has answered (agreed 19 Oct 2026).
        "colleague_positive": "Colleague replied: positive",
        "colleague_negative": "Unqualified: Colleague response negative",
        "colleague_replied": "Colleague replied",
        # Someone at the company opted out (19 Oct 2026): blocklisted, unsubscribed or asked to stop.
        "colleague_opted_out": "Unqualified: Colleague Opted-out/Blocklist",
        # The company is Unqualified because you rejected it (21 Oct 2026, Ariel): every other contact there.
        "company_unqualified": "Unqualified company",
        # 21 Oct 2026 (Ariel): the person emailed did not reply in time.
        "no_response": "Unqualified: Contacted, but no response",
        # 2 Nov 2026 (Ariel): the others at a company whose person emailed did not reply in time.
        "colleague_no_response": "Unqualified: Colleague Contacted, but no response",
        # 28 Oct 2026 (Ariel): the address is dead (a hard bounce, or the person has left); the problem is
        # the contact, not the company. A company inbox gets its own label (2 Nov 2026).
        "corrupt": "Unqualified: Contact corrupt",
        "inbox_bounced": "Unqualified: Inbox Bounced",
        # 2 Nov 2026 (Ariel): set by hand (on leave, or pointed us to someone else); see redirect.py.
        "redirected": "Unqualified: Rejected/Redirected by company owner",
        # 3 Nov 2026 (Ariel): the person who gave a clear yes or no, and everyone else at that company.
        "sales": "END: Forwarded to Sales Team",
    },
}
# The old labels, renamed in place by button 1 so the records on them move with them (2 Nov 2026).
RENAMED = {
    "companies": {"Contacted, but no response, unqualified": "Unqualified: Contacted, but no response",
                  "Invalid inbox: Mail bounced, need input": "Unqualified: Company inbox bounced"},
    "contacts": {"Colleague replied: negative": "Unqualified: Colleague response negative",
                 "Colleague opted out": "Unqualified: Colleague Opted-out/Blocklist",
                 "Contacted, but no response, unqualified": "Unqualified: Contacted, but no response",
                 "Unqualified Contact: Contact corrupt": "Unqualified: Contact corrupt"},
}
COLLEAGUE_STAGES = ("colleague_positive", "colleague_negative", "colleague_replied", "colleague_opted_out",
                    "colleague_no_response")
# Contact stages that mean "emailed, no reply yet" (agreed 14 Oct 2026: the forward and the
# reminder get their own Lead Status so they can be checked in HubSpot).
EMAILED = ("in_outreach", "forwarded", "reminded")
# A contact's own dead end (2 Nov 2026: plain Unqualified split by what happened).
CONTACT_CLOSED = ("closed", "said_no", "opted_out", "bounced_other")
# A contact who is never emailed again and whose place the next person takes.
LEFT_OUT = ("corrupt", "inbox_bounced", "redirected")
# A company that is Unqualified because of an answer, or because you rejected it.
COMPANY_CLOSED = ("closed", "said_no", "opted_out")
# Until button 1 adds a new choice, the stage used instead (2 Nov 2026). Since 3 Nov 2026 (Ariel) never
# plain Unqualified: that is only ever set by a person, so the automation must not write it.
FALLBACK = {"inbox_bounced": "corrupt", "colleague_no_response": "company_unqualified", "located": "approved"}
# A company that is approved and not emailed yet: on GATE1, or with its contacts located (10 Nov 2026).
OPEN = ("approved", "located")

# The internal value given to a choice when the setup has to add it (matching the live
# account's style: companies use the label itself, contacts use capitals). A renamed choice keeps
# the value it had.
NEW_OPTION_VALUES = {
    "companies": {"GATE1: Approved for outreach": "GATE1: Approved for outreach", "Missing Info": "Missing Info",
                  "Missing info on Apollo": "Missing info on Apollo",
                  "Contact exists, not AUTO-OUTREACH": "Contact exists, not AUTO-OUTREACH", "New": "New",
                  "Contact located. Queued for processing": "Contact located. Queued for processing", "Attempted to Contact": "Attempted to Contact",
                  "In Progress": "In Progress", "Unqualified": "Unqualified",
                  "Unqualified: Employee response negative": "Unqualified: Employee response negative",
                  "Unqualified: Employee Opted-out/Blocklist": "Unqualified: Employee Opted-out/Blocklist",
                  "Unqualified: Contacted, but no response": "Contacted, but no response, unqualified",
                  "Unqualified: Company inbox bounced": "Invalid inbox: Mail bounced, need input",
                  "Unqualified: Personal inbox bounced": "Unqualified: Personal inbox bounced",
                  "Unqualified: One contact inputted, which is unavailable":
                      "Unqualified: One contact inputted, which is unavailable",
                  "Unqualified: Bounced, other reason": "Unqualified: Bounced, other reason",
                  "END: Forwarded to Sales Team": "END: Forwarded to Sales Team"},
    "contacts": {"New, Personal line filled": "NEW_PERSONAL_LINE_FILLED", "GATE2: Approved to send": "APPROVED_TO_SEND", "New": "NEW",
                 "Attempted to Contact": "ATTEMPTED_TO_CONTACT", "Forward sent": "FORWARD_SENT",
                 "Reminder sent": "REMINDER_SENT", "In Progress": "IN_PROGRESS",
                 "Unqualified": "UNQUALIFIED", "Colleague replied: positive": "COLLEAGUE_REPLIED_POSITIVE",
                 "Unqualified: Colleague response negative": "COLLEAGUE_REPLIED_NEGATIVE",
                 "Colleague replied": "COLLEAGUE_REPLIED",
                 "Unqualified: Colleague Opted-out/Blocklist": "COLLEAGUE_OPTED_OUT",
                 "Unqualified company": "UNQUALIFIED_COMPANY",
                 "Unqualified: Contacted, but no response": "CONTACTED_NO_RESPONSE_UNQUALIFIED",
                 "Unqualified: Contact corrupt": "UNQUALIFIED_CONTACT_CORRUPT",
                 "Unqualified: Response negative": "UNQUALIFIED_RESPONSE_NEGATIVE",
                 "Unqualified: Opted-out/Blocklist": "UNQUALIFIED_OPTED_OUT_BLOCKLIST",
                 "Unqualified: Bounced, other reason": "UNQUALIFIED_BOUNCED_OTHER",
                 "Unqualified: Colleague Contacted, but no response": "COLLEAGUE_CONTACTED_NO_RESPONSE",
                 "Unqualified: Inbox Bounced": "UNQUALIFIED_INBOX_BOUNCED",
                 "Unqualified: Rejected/Redirected by company owner": "UNQUALIFIED_REDIRECTED",
                 "END: Forwarded to Sales Team": "END_FORWARDED_TO_SALES_TEAM"},
}

# Later stages win: a status only ever moves forward.
ORDER = {"": 0, "found": 0, "missing_info": 0, "missing_apollo": 0, "contact_exists": 0, "copy_ready": 0, "approved": 0,
         "located": 0.5, "in_outreach": 1, "forwarded": 1, "reminded": 1.5, "replied": 2, "closed": 3,
         "said_no": 3, "opted_out": 3, "bounced_other": 3,
         "colleague_positive": 2, "colleague_negative": 2, "colleague_replied": 2, "colleague_opted_out": 2,
         "colleague_no_response": 3,
         "company_unqualified": 3, "no_response": 3, "corrupt": 3, "inbox_bounced": 3, "redirected": 3,
         "invalid_inbox": 3, "personal_bounced": 3, "redirected_none": 3,
         "sales": 4}  # 3 Nov 2026: the end; nothing moves a record on from there
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
            old = {new.lower(): before.lower() for before, new in RENAMED[obj].items()}
            for stage, label in stages.items():
                # Until button 1 has renamed a choice (2 Nov 2026), it is found under its old label.
                value = by_label.get(label.lower(), by_label.get(old.get(label.lower(), "")))
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
        """The props for a stage. A choice added on 2 Nov 2026 that the account does not have yet (button 1
        not pressed since) falls back to the one used before (FALLBACK), so nothing stops."""
        if not self.has(obj, stage) and stage in FALLBACK:
            return self.props(obj, FALLBACK[stage])
        return {LEAD_STATUS: self.value(obj, stage)}


def forward(old_stage, new_stage):
    """True when moving from old_stage to new_stage is a step forward. A record a person has
    taken over ("team") is never changed."""
    if old_stage == TEAM:
        return False
    return ORDER.get(new_stage, 0) > ORDER.get(old_stage, 0)


# A company in one of these stages gets no more emails.
COMPANY_STOPPED = {"replied", "closed", "said_no", "opted_out", "no_response", "invalid_inbox", "personal_bounced",
                   "redirected_none", "bounced_other", "sales", TEAM}
