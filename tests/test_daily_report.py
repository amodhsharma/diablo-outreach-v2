"""The daily summary email (Ariel, 27 Oct 2026): the agreed wording, the figures for the India day
before, and sending through Google from admin@diablosnosugar.com."""

import json

import pytest

from outreach import daily_log, daily_report
from outreach.common import PipelineError, load_settings
from outreach.schema import CONTACT_SOURCE, INBOX_TITLE, STOP_REASON

from .fakes import FakeCRM, FakeInstantly

DAY = "2026-10-26"


def quiet(_):
    pass


class FakeSMTP:
    def __init__(self):
        self.sent, self.login_as = [], None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.login_as = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


class Accounts:
    def __init__(self, accounts):
        self.accounts = accounts

    def list_accounts(self):
        return self.accounts


def _details(instantly, connected=None):
    """Instantly's campaign details and sending status, as the health check reads them."""
    def request(method, path, **kw):
        parts = path.strip("/").split("/")
        if len(parts) == 2:
            return dict(instantly.campaigns[parts[1]])
        return {"diagnostics": {"accounts_summary": {"total_connected": connected}}} if connected else {}
    instantly.request = request


def _world():
    hs, instantly = FakeCRM(), FakeInstantly()
    # Research on 26 Oct (India time): two in Australia, one in South Africa; one the day before.
    for name, country, when in (("Alpha", "Australia", "2026-10-26T03:00:00Z"), ("Beta", "Australia", "2026-10-26T10:00:00Z"),
                                ("Gamma", "South Africa", "2026-10-26T17:00:00Z"),
                                ("Old", "Australia", "2026-10-25T17:00:00Z")):  # 25 Oct, 22:30 India time
        hs.add("companies", name=name, country=country, createdate=when, hs_lastmodifieddate=when,
               hs_lead_status="New")
    approved = hs.add("companies", name="Approved Co", country="Australia", createdate="2026-10-20T00:00:00Z",
                      hs_lastmodifieddate="2026-10-26T06:00:00Z", hs_lead_status="GATE1: Approved for outreach")
    nowhere = hs.add("companies", name="Sport Benzin", createdate="2026-10-20T00:00:00Z",
                     hs_lastmodifieddate="2026-10-26T07:00:00Z", hs_lead_status="Missing Info",
                     **{STOP_REASON: "No contact found anywhere (2026-10-26): nobody in Apollo"})
    quiet_co = hs.add("companies", name="Quiet Co", createdate="2026-10-10T00:00:00Z",
                      hs_lastmodifieddate="2026-10-26T08:00:00Z", hs_lead_status="Contacted, but no response, unqualified")
    hs.past = {("companies", approved): [("GATE1: Approved for outreach", "2026-10-26T06:00:00Z"), ("New", "2026-10-20T00:00:00Z")],
               ("companies", nowhere): [("Missing Info", "2026-10-26T07:00:00Z"), ("GATE1: Approved for outreach", "2026-10-25T07:00:00Z")],
               ("companies", quiet_co): [("Contacted, but no response, unqualified", "2026-10-26T08:00:00Z"),
                                         ("Attempted to Contact", "2026-10-18T08:00:00Z")]}
    # Contacts found on 26 Oct: Approved Co has a person, Inbox Co only its website address.
    inbox_co = hs.add("companies", name="Inbox Co", createdate="2026-10-20T00:00:00Z", hs_lead_status="GATE1: Approved for outreach")
    person = hs.add("contacts", email="p@approved.example", jobtitle="Buyer", createdate="2026-10-26T06:30:00Z",
                    hs_lead_status="NEW_PERSONAL_LINE_FILLED", **{CONTACT_SOURCE: "Apollo"})
    hs.links[person] = [approved]
    inbox = hs.add("contacts", email="info@inbox.example", jobtitle=INBOX_TITLE, createdate="2026-10-26T06:40:00Z",
                   hs_lead_status="NEW")
    hs.links[inbox] = [inbox_co]
    felfel = hs.add("companies", name="FELFEL", createdate="2026-10-20T00:00:00Z", hs_lead_status="In Progress")
    happy = hs.add("contacts", email="a@felfel.example", jobtitle="Owner", createdate="2026-10-20T00:00:00Z",
                   hs_lead_status="IN_PROGRESS")
    hs.links[happy] = [felfel]
    # Instantly: three introductions sent on 26 Oct (one to a company inbox), one on 25 Oct.
    main = instantly.create_campaign({"name": "Diablo | OCT2026", "email_list": ["sales@x.example"], "status": 1})["id"]
    box = instantly.create_campaign({"name": "Diablo | OCT2026 | Company inboxes", "email_list": [], "status": 1})["id"]
    instantly.leads[main] = [{"email": "a@felfel.example", "timestamp_last_contact": "2026-10-26T09:00:00Z"},
                             {"email": "b@x.example", "timestamp_last_contact": "2026-10-26T10:00:00Z"},
                             {"email": "c@x.example", "timestamp_last_contact": "2026-10-25T10:00:00Z"}]
    instantly.leads[box] = [{"email": "info@y.example", "timestamp_last_contact": "2026-10-26T11:00:00Z"}]
    _details(instantly, connected=1)
    log = {"days": {DAY: {"positive": [happy], "negative": ["9"], "neutral": [], "auto": ["7", "8"], "bounced": ["6"],
                          "opted_out": []}},
           "before": {"2026-10": {"positive": 2, "negative": 1, "neutral": 1}}}
    accounts = Accounts([{"email": "sales@x.example", "status": 1, "warmup_status": 1, "stat_warmup_score": 100}])
    return hs, instantly, accounts, log


def test_the_email_reads_as_agreed():
    hs, instantly, accounts, log = _world()
    result = daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, date=DAY, preview=True,
                              log=quiet, log_data=log)
    assert result["subject"] == "Partner outreach: daily summary, Monday 26 October 2026"
    assert result["text"] == """Good morning,

Here is the summary of partner outreach for Monday 26 October 2026.

Prospecting
- New prospective partners identified: 3 (Australia 2, South Africa 1)
- Prospects approved for contact research: 1
- Companies where named contacts were found: 1
- Companies where only a general inbox was found (from their website): 1
- Companies where no contact was found, sales team input required: 1
  - Sport Benzin
- New prospects awaiting approval for contact research: 4
- Introductions written, awaiting approval to send: 1
- Companies marked unqualified after no response within 7 days: 1

Outreach
- Introductory emails sent: 3 (2 to named contacts, 1 to general company inboxes)
- Responses received: 2 (1 positive, 1 negative, 0 neutral)
- Positive responses requiring follow-up: 1
  - FELFEL
- Automatic replies, such as out of office: 2 (not counted as responses)
- Undelivered emails: 1 (delivery failure rate 33.3%)
- Opt-out requests: 0
- Sending accounts: the campaign for general company inboxes has no sending account connected; please assign one in Instantly

Month to date (1 to 26 October 2026)
- Prospects identified: 9
- Introductory emails sent: 4
- Responses received: 6 (3 positive)

Kind regards,
Diablo Partner Outreach
"""
    assert result["sent"] is False


def test_it_is_sent_from_the_agreed_mailbox(monkeypatch):
    hs, instantly, accounts, log = _world()
    smtp = FakeSMTP()
    with pytest.raises(PipelineError):  # no secrets yet: nothing is sent
        daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, date=DAY, log=quiet,
                         smtp=smtp, log_data=log)
    monkeypatch.setenv("DAILY_REPORT_TO", "one@team.example, two@team.example,three@team.example")
    monkeypatch.setenv("DAILY_REPORT_APP_PASSWORD", "app-password")
    daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, date=DAY, log=quiet, smtp=smtp,
                     log_data=log)
    msg = smtp.sent[0]
    assert smtp.login_as == ("admin@diablosnosugar.com", "app-password")
    assert msg["From"] == "Diablo Partner Outreach <admin@diablosnosugar.com>"
    assert msg["To"] == "one@team.example, two@team.example, three@team.example"
    html = msg.get_body(("html",)).get_content()
    assert "<b>Prospecting</b>" in html and "<li>FELFEL</li>" in html


def test_a_quiet_day_and_all_healthy():
    hs, instantly = FakeCRM(), FakeInstantly()
    instantly.create_campaign({"name": "Diablo | OCT2026", "email_list": ["sales@x.example"], "status": 1})
    _details(instantly)
    accounts = Accounts([{"email": "sales@x.example", "status": 1, "warmup_status": 1, "stat_warmup_score": 99}])
    text = daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, date="2026-11-01",
                            preview=True, log=quiet, log_data={})["text"]
    assert "- New prospective partners identified: 0\n" in text
    assert "- Introductory emails sent: 0\n" in text and "- Responses received: 0\n" in text
    assert "- Sending accounts: all healthy" in text and "Month to date (1 November 2026)" in text


def test_a_mailbox_that_needs_attention_is_named():
    hs, instantly = FakeCRM(), FakeInstantly()
    instantly.create_campaign({"name": "Diablo | OCT2026", "email_list": ["sales@x.example"], "status": 1})
    _details(instantly)
    accounts = Accounts([{"email": "sales@x.example", "status": -1, "warmup_status": 1, "stat_warmup_score": 100}])
    assert daily_report.health(instantly, load_settings(), accounts) == ["sales@x.example needs attention (connection error)"]


def test_the_log_records_each_answer_once_by_india_day(tmp_path):
    notes = tmp_path / "timeline_notes.json"
    notes.write_text(json.dumps({"reply:marked interested": ["1"], "bounced": ["2"]}))
    events = [({"id": "1"}, {}, "marked interested"),            # already known before the log: not again
              ({"id": "3"}, {"timestamp_last_reply": "2026-10-26T20:00:00Z"}, "replied"),  # 27 Oct India time
              ({"id": "4"}, {}, "out of office"), ({"id": "5"}, {}, "bounced"), ({"id": "6"}, {}, "blocklisted"),
              ({"id": "7"}, {}, "emailed")]
    import datetime as dt
    now = dt.datetime(2026, 10, 26, 12, 0, tzinfo=dt.timezone.utc)
    assert daily_log.record(events, notes_path=notes, now=now) == 4
    assert daily_log.record(events, notes_path=notes, now=now) == 0
    data = daily_log.load()
    assert daily_log.day(data, "2026-10-27")["neutral"] == ["3"]
    assert daily_log.day(data, DAY) == {"positive": [], "negative": [], "neutral": [], "auto": ["4"], "bounced": ["5"],
                                         "opted_out": ["6"]}
    assert daily_log.month_counts(data, "2026-10-01", "2026-10-31")["positive"] == 1  # from before the log
