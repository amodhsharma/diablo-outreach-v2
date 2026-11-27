"""HARD RULE (27 Nov 2026, Ariel): people in HR, finance, IT, legal, PA roles, safety, marketing, store staff
and logistics are never emailed, and the next person at the company moves up."""

import pytest

from outreach import roles, send, sync
from outreach.common import load_settings
from outreach.next_in_line import contact_state
from outreach.stages import LeadStatus

from .fakes import FakeCRM, FakeEmails, FakeInstantly
from .test_corrupt import LS, ORDER, ago, company, lead, quiet, rec

REASON = "diablo_stop_reason"


@pytest.fixture
def settings():
    s = load_settings()
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"
    return s


@pytest.mark.parametrize("title, group", [
    ("People and Culture Manager", "HR"), ("Social Media Manager", "marketing"),
    ("People & Culture Business Partner", "HR"), ("Safety, Health & Environment Manager", "safety"),
    ("Senior Product Owner", "IT"), ("Senior Tech Product Owner", "IT"), ("Leiterin Personal Schweiz", "HR"),
    ("Store Leader", "store staff"), ("Head of Marketing", "marketing"), ("Accountant", "finance"),
    ("PA to Country Managing Director", "PA or assistant"), ("Executive Assistant to the CEO", "PA or assistant"),
    ("Chief Financial Officer", "finance"), ("Logistics Manager", "logistics"), ("Legal Counsel", "legal"),
    ("Vice President Marketing", "marketing"),
])
def test_roles_we_never_email(title, group):
    assert roles.wrong_role(title) == group


@pytest.mark.parametrize("title", [
    "CEO", "Managing Director", "Business Owner", "Founder", "General Manager", "Head of Buying", "Procurement Leader",
    "Category Manager Confectionery", "Assistant Buyer", "Head of Sales and Marketing", "Import Manager",
    "Supply Chain & Procurement Manager", "Einkaufsleiter", "Senior Product & Business Development Manager",
    "Commercial Director", "Key Account Manager", "Company inbox (from website)", "Referred by colleague", "",
])
def test_the_roles_we_email_still_go(title):
    assert roles.wrong_role(title) is None


def test_the_rule_can_be_switched_off_in_the_settings(settings):
    settings["contacts"]["never_email"] = {"enabled": False}
    roles.use(settings)
    try:
        assert roles.wrong_role("HR Manager") is None
    finally:
        roles.use(load_settings())


def _contact(title, status, email="x@y.example"):
    return {"id": "1", "properties": {"email": email, "jobtitle": title, LS: status}}


def test_an_open_contact_in_such_a_role_is_skipped_but_an_answer_still_stops_the_company():
    hs = FakeCRM()
    statuses = LeadStatus(hs)
    assert contact_state(_contact("HR Manager", "APPROVED_TO_SEND"), statuses, {}) == "skipped"
    sent = {"x@y.example": {"timestamp_last_contact": ago(1), "status": 1}}
    assert contact_state(_contact("HR Manager", "ATTEMPTED_TO_CONTACT"), statuses, sent) == "skipped"
    assert contact_state(_contact("HR Manager", "ATTEMPTED_TO_CONTACT"), statuses, sent, roles=False) == "sent"
    assert contact_state(_contact("HR Manager", "IN_PROGRESS"), statuses, sent) == "stop"  # they replied
    assert contact_state(_contact("Head of Buying", "APPROVED_TO_SEND"), statuses, {}) == "approved"


def test_the_next_person_gets_the_introduction_instead(settings):
    hs, instantly = FakeCRM(), FakeInstantly()
    cid, (hr, buyer) = company(hs, "Shop Co", "shop.example", ("People and Culture Manager", "Category Manager"))
    assert send.run("test", settings, hs, instantly, log=quiet)["queued"] == 1
    emails = [l["email"] for ls in instantly.leads.values() for l in ls]
    assert emails == ["p2@shop.example"]


def test_a_waiting_introduction_is_taken_out_and_no_reminder_goes(settings):
    """An introduction added before the rule is pulled from Instantly; someone already emailed gets no
    reminder; both records say why, once."""
    import copy
    before_rule = copy.deepcopy(settings)
    before_rule["contacts"]["never_email"] = {"enabled": False}
    hs, instantly, emails = FakeCRM(), FakeInstantly(), FakeEmails()
    try:
        cid, (social, hr, buyer) = company(hs, "Big Co", "big.example",
                                           ("Social Media Manager", "People and Culture Manager", "Head of Buying"))
        send.run("test", before_rule, hs, instantly, log=quiet)  # before the rule: the social media manager went
        assert [l["email"] for ls in instantly.leads.values() for l in ls] == ["p1@big.example"]
        lead(instantly, "p1@big.example")["timestamp_last_contact"] = ago(8)
        emails.campaign_email("p1@big.example", ago(8))
        rec(hs, social)[LS] = "ATTEMPTED_TO_CONTACT"
        hs.records["companies"][cid][LS] = "Attempted to Contact"
        rec(hs, hr)[LS] = "APPROVED_TO_SEND"
        some = next(iter(instantly.leads))  # the HR manager's introduction is waiting in Instantly
        instantly.leads[some].append({"id": "L-hr", "email": "p2@big.example", "_campaign_id": some})
    finally:
        roles.use(load_settings())
    lines = []
    moved = sync.run("test", settings, hs, instantly, log=lines.append, emails_api=emails)
    assert "p2@big.example" not in [l["email"] for ls in instantly.leads.values() for l in ls]
    assert moved.get("reminders_sent", 0) == 0
    assert rec(hs, social)[REASON].startswith(roles.REASON_START + " (marketing)")
    assert rec(hs, hr)[REASON].startswith(roles.REASON_START + " (HR)")
    assert any("taken out" in l and "People and Culture Manager" in l for l in lines)
    before = rec(hs, hr)[REASON]
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, hr)[REASON] == before  # written once
    send.run("test", settings, hs, instantly, log=quiet)  # the buyer is next in line
    assert "p3@big.example" in [l["email"] for ls in instantly.leads.values() for l in ls]
