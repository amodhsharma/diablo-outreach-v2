"""17 Nov 2026 (Ariel): every approved person is read and the next person due at each company goes; the next
person 48 hours after the previous introduction, each reminder 96 hours after the person's own introduction,
a person closed 48 hours after their reminder, the company 3 days after its last reminder; button 4 keeps
its own memory of every person and never gives anyone an email twice."""

import datetime as dt
import json

import pytest

from outreach import chain, send, send_memory, sync
from outreach.common import load_settings
from outreach.daily_log import INDIA
from outreach.next_in_line import decide_chain
from outreach.schema import INBOX_TITLE

from .fakes import FakeCRM, FakeEmails, FakeInstantly
from .test_corrupt import LS, ORDER, company, lead, quiet, rec

REAL_NOW = dt.datetime.now(dt.timezone.utc)


@pytest.fixture
def settings():
    s = load_settings()
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"
    return s


def person(pid, rank, state, **props):
    props.setdefault("diablo_personal_line", "Line.")
    return {"id": pid, "state": state, "sent_at": None,
            "properties": {"email": f"{pid}@x.example", "jobtitle": "Buyer", ORDER: str(rank), **props}}


def test_the_settings_hold_the_agreed_timings(settings):
    cfg = chain.config(settings)
    assert cfg["gap"] * 24 == 48 and cfg["reminder"] * 24 == 96
    assert cfg["contact_close_hours"] == 48 and cfg["close"] == 3
    assert cfg["reminders_per_mailbox"] == 20 and not cfg["reminders_by_mailbox"]


def test_48_hours_between_people_and_each_reminder_96_hours_after_their_own_introduction(settings):
    cfg = chain.config(settings)
    t0 = dt.datetime(2026, 11, 1, 9, tzinfo=dt.timezone.utc)
    at = lambda hours: t0 + dt.timedelta(hours=hours)  # noqa: E731
    p1, p2, p3 = person("p1", 1, "sent"), person("p2", 2, "approved"), person("p3", 3, "approved")
    touches = {"p1": [at(0)]}
    assert decide_chain([p1, p2, p3], "in_outreach", at(47), touches, cfg) == (None, "waiting")
    assert decide_chain([p1, p2, p3], "in_outreach", at(48), touches, cfg) == (p2, "next")
    p2["state"], touches["p2"] = "sent", [at(48)]
    assert decide_chain([p1, p2, p3], "in_outreach", at(95), touches, cfg) == (None, "waiting")
    # Hour 96: person 1's reminder and person 3's introduction are both due; each simply goes.
    assert decide_chain([p1, p2, p3], "in_outreach", at(96), touches, cfg) == (p1, "reminder")
    assert decide_chain([p1, p2, p3], "in_outreach", at(96), touches, dict(cfg, skip_reminder=["p1"])) == (p3, "next")
    touches["p1"].append(at(96))
    p3["state"], touches["p3"] = "sent", [at(96)]
    assert decide_chain([p1, p2, p3], "in_outreach", at(144), touches, cfg) == (p2, "reminder")
    touches["p2"].append(at(144))
    assert decide_chain([p1, p2, p3], "in_outreach", at(192), touches, cfg) == (p3, "reminder")
    touches["p3"].append(at(192))
    # The company closes 3 days after its last reminder.
    assert decide_chain([p1, p2, p3], "in_outreach", at(192 + 71), touches, cfg) == (None, "waiting_for_reply")
    assert decide_chain([p1, p2, p3], "in_outreach", at(192 + 72), touches, cfg) == (None, "no_reply")


def test_every_approved_person_is_read_so_person_1_goes_even_when_listed_last(settings):
    settings["send"]["contacts_per_run"] = 1  # only one person comes back from HubSpot: person 2
    hs, instantly = FakeCRM(), FakeInstantly()
    cid = hs.add("companies", name="Costco", domain="costco.example", country="Australia",
                 industry_type="Distributor Wholesaler", **{LS: "Contact located. Queued for processing"})
    for rank in (2, 1):
        pid = hs.add("contacts", email=f"p{rank}@costco.example", firstname=f"P{rank}", lastname="L", jobtitle="Buyer",
                     diablo_personal_line="Line.", diablo_company_note="imports sweets",
                     **{ORDER: str(rank), LS: "APPROVED_TO_SEND"})
        hs.links[pid] = [cid]
    result = send.run("test", settings, hs, instantly, log=quiet)
    assert result["queued"] == 1
    assert [l["email"] for ls in instantly.leads.values() for l in ls] == ["p1@costco.example"]


def three_started(settings):
    """A company of three; person 1's introduction went 4 days and 1 hour ago (T0)."""
    hs, instantly, emails = FakeCRM(), FakeInstantly(), FakeEmails()
    cid, people = company(hs, "Chain Co", "chain.example", ("Owner", "Buyer", "Category Manager"))
    send.run("test", settings, hs, instantly, log=quiet)
    t0 = REAL_NOW - dt.timedelta(days=4, hours=1)
    lead(instantly, "p1@chain.example")["timestamp_last_contact"] = t0.isoformat()
    emails.campaign_email("p1@chain.example", t0.isoformat(), subject="A sugar-free brand with no Australia partner yet")
    return hs, instantly, emails, cid, people, t0


def test_a_reminder_and_a_new_introduction_due_together_both_go_and_a_person_closes_48_hours_later(settings):
    hs, instantly, emails, cid, (p1, p2, p3), t0 = three_started(settings)
    at = lambda hours: t0 + dt.timedelta(hours=hours)  # noqa: E731
    moved = sync.advance(hs, instantly, settings, quiet, now=at(48.5), emails_api=emails)
    assert moved["next_contacts_added"] == 1 and rec(hs, p2)[LS] == "ATTEMPTED_TO_CONTACT"
    lead(instantly, "p2@chain.example")["timestamp_last_contact"] = at(48.4).isoformat()
    emails.campaign_email("p2@chain.example", at(48.4).isoformat(), subject="A sugar-free brand with no Australia partner yet")
    moved = sync.advance(hs, instantly, settings, quiet, now=at(96.5), emails_api=emails)
    assert moved["reminders_sent"] == 1 and moved["next_contacts_added"] == 1  # both in the same run
    assert rec(hs, p1)[LS] == "REMINDER_SENT" and rec(hs, p3)[LS] == "ATTEMPTED_TO_CONTACT"
    memory = json.loads(send_memory.FILE.read_text())
    assert set(memory["contacts"][p1]) >= {"queued", "introduced", "reminded"}
    assert "@" not in send_memory.FILE.read_text()  # IDs and times only
    lead(instantly, "p3@chain.example")["timestamp_last_contact"] = at(97).isoformat()
    emails.campaign_email("p3@chain.example", at(97).isoformat(), subject="A sugar-free brand with no Australia partner yet")
    moved = sync.advance(hs, instantly, settings, quiet, now=at(96.5 + 47), emails_api=emails)
    assert moved["contacts_closed"] == 0
    moved = sync.advance(hs, instantly, settings, quiet, now=at(96.5 + 48.5), emails_api=emails)
    assert moved["contacts_closed"] == 1 and moved["reminders_sent"] == 1  # person 1 closed, person 2 reminded
    assert rec(hs, p1)[LS] == "CONTACTED_NO_RESPONSE_UNQUALIFIED"
    assert rec(hs, p2)[LS] == "REMINDER_SENT"
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"  # the others carry on
    assert json.loads(send_memory.FILE.read_text())["contacts"][p1]["closed"]
    # The closed person is never reminded again and never stops the company.
    moved = sync.advance(hs, instantly, settings, quiet, now=at(96.5 + 49), emails_api=emails)
    assert moved["reminders_sent"] == 0 and rec(hs, p1)[LS] == "CONTACTED_NO_RESPONSE_UNQUALIFIED"


def test_the_memory_never_gives_anyone_a_second_introduction(settings):
    hs, instantly, emails, cid, (p1, p2, p3), t0 = three_started(settings)
    rec(hs, p1)[LS] = "APPROVED_TO_SEND"  # someone put person 1 back on GATE2 by hand
    for l in instantly.leads.values():
        l.clear()  # and Instantly no longer shows them
    result = send.run("test", settings, hs, instantly, log=quiet)
    assert result["queued"] == 0
    assert not [l for ls in instantly.leads.values() for l in ls]


def test_new_companies_go_inbox_only_first_then_in_order_within_the_day_s_room(settings):
    settings["send"]["daily_limit_per_mailbox"] = 2  # one mailbox: room for 2 new introductions today
    hs, instantly = FakeCRM(), FakeInstantly()
    names = []
    for name, inbox in (("Alpha", False), ("Beta Inbox", True), ("Gamma", False)):
        domain = name.split()[0].lower() + ".example"
        cid = hs.add("companies", name=name, domain=domain, country="Australia",
                     industry_type="Distributor Wholesaler", **{LS: "Contact located. Queued for processing"})
        pid = hs.add("contacts", email=f"info@{domain}" if inbox else f"p1@{domain}", firstname="" if inbox else "P1",
                     jobtitle=INBOX_TITLE if inbox else "Owner", diablo_personal_line="Line.",
                     diablo_company_note="imports sweets", **{ORDER: "1", LS: "APPROVED_TO_SEND"})
        hs.links[pid] = [cid]
        names.append(domain)
    result = send.run("test", settings, hs, instantly, log=quiet)
    sent = sorted(l["email"] for ls in instantly.leads.values() for l in ls)
    assert result["queued"] == 2 and sent == ["info@beta.example", "p1@alpha.example"]


def test_the_daily_summary_counts_introductions_and_reminders_from_the_memory():
    memory = {"started": "2026-11-17T05:00:00+00:00", "contacts": {
        "1": {"introduced": "2026-11-18T04:00:00+00:00", "inbox": False},
        "2": {"introduced": "2026-11-18T10:00:00+00:00", "inbox": True},
        "3": {"introduced": "2026-11-14T10:00:00+00:00", "reminded": "2026-11-18T09:00:00+00:00", "inbox": False},
        "4": {"introduced": "2026-11-18T20:00:00+00:00", "inbox": False},  # 19 Nov in India
    }}
    assert send_memory.day_counts(memory, "2026-11-18", INDIA) == {"person": 1, "inbox": 1, "reminders": 1}
    assert send_memory.day_counts(memory, "2026-11-17", INDIA) is None  # not covered in full: counted as before
