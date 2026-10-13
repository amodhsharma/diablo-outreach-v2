"""One person per company at a time: most senior first, the reminder after 3 days, the
next person on day 4, and everyone stops when anyone at the company replies."""

import datetime as dt

import pytest

from outreach import common, send, sync
from outreach.common import load_settings

from .fakes import FakeCRM, FakeInstantly


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


@pytest.fixture
def settings():
    s = load_settings()
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
    return s


def ago(days):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()


def company_with_three(hs, name, domain):
    cid = hs.add("companies", name=name, domain=domain, diablo_market="India",
                 diablo_channel_category="grocery_wholesaler", diablo_outreach_status="contacts_found")
    people = []
    for rank, title in enumerate(("Managing Director", "Head of Buying", "Category Manager"), start=1):
        pid = hs.add("contacts", email=f"p{rank}@{domain}", firstname=f"P{rank}", jobtitle=title,
                     diablo_hierarchy_rank=str(rank), diablo_contact_status="approved_to_send",
                     diablo_subject_line="Hello", diablo_personal_line="Line.")
        hs.links[pid] = [cid]
        people.append(pid)
    return cid, people


def lead(instantly, email):
    return next(l for ls in instantly.leads.values() for l in ls if l["email"] == email)


def test_one_person_at_a_time_then_the_next_on_day_three(settings):
    hs, instantly = FakeCRM(), FakeInstantly()
    cid, (first, second, third) = company_with_three(hs, "Noble Foods", "noble.in")
    result = send.run("test", settings, hs, instantly, log=quiet)
    assert result["queued"] == 1 and result["waiting"] == 2  # only the most senior goes
    status = lambda pid: hs.records["contacts"][pid]["diablo_contact_status"]
    assert [status(first), status(second), status(third)] == ["queued", "approved_to_send", "approved_to_send"]
    assert send.run("test", settings, hs, instantly, log=quiet)["queued"] == 0  # pressing again sends nobody new

    # Day 2: first email went out two days ago, no reply. Nobody else yet.
    lead(instantly, "p1@noble.in")["timestamp_last_contact"] = ago(2)
    sync.run("test", settings, hs, instantly, log=quiet)
    assert status(first) == "sent" and status(second) == "approved_to_send"

    # Day 3 and still no reply: the next person gets their own email in the same campaign.
    hs.records["contacts"][first]["diablo_last_event_at"] = ago(3)
    moved = sync.run("test", settings, hs, instantly, log=quiet)
    assert moved["next_contacts_added"] == 1 and status(second) == "queued"
    camp_id = hs.records["contacts"][first]["diablo_instantly_campaign_id"]
    assert [l["email"] for l in instantly.leads[camp_id]] == ["p1@noble.in", "p2@noble.in"]

    # The second person replies: everyone stops, the third is never emailed.
    lead(instantly, "p2@noble.in").update(timestamp_last_contact=ago(1), email_reply_count=1,
                                           timestamp_last_reply=ago(0))
    sync.run("test", settings, hs, instantly, log=quiet)
    assert hs.records["companies"][cid]["diablo_outreach_status"] == "replied"
    hs.records["contacts"][second]["diablo_last_event_at"] = ago(9)
    sync.run("test", settings, hs, instantly, log=quiet)
    assert status(third) == "approved_to_send"
    assert len(instantly.leads[camp_id]) == 2


def test_no_reply_from_everyone_marks_the_company(settings):
    settings["send"]["rotation"]["rounds"] = 1  # one round only: no later emails
    hs, instantly = FakeCRM(), FakeInstantly()
    cid = hs.add("companies", name="Quiet Co", domain="quiet.in", diablo_market="India",
                 diablo_channel_category="grocery_wholesaler", diablo_outreach_status="contacts_found")
    only = hs.add("contacts", email="boss@quiet.in", diablo_hierarchy_rank="1",
                  diablo_contact_status="approved_to_send", diablo_subject_line="Hi", diablo_personal_line="Line.")
    hs.links[only] = [cid]
    send.run("test", settings, hs, instantly, log=quiet)
    lead(instantly, "boss@quiet.in")["timestamp_last_contact"] = ago(5)
    result = sync.run("test", settings, hs, instantly, log=quiet)  # Sent 5 days ago, nobody left
    assert result["no_reply"] == 1
    assert hs.records["companies"][cid]["diablo_outreach_status"] == "no_reply"


def test_waits_for_gate_two_before_moving_on(settings):
    hs, instantly = FakeCRM(), FakeInstantly()
    cid, (first, second, third) = company_with_three(hs, "Slow Co", "slow.in")
    hs.records["contacts"][second]["diablo_contact_status"] = "copy_ready"  # not approved yet
    hs.records["contacts"][third]["diablo_contact_status"] = "copy_ready"
    send.run("test", settings, hs, instantly, log=quiet)
    lead(instantly, "p1@slow.in")["timestamp_last_contact"] = ago(6)
    sync.run("test", settings, hs, instantly, log=quiet)
    hs.records["contacts"][first]["diablo_last_event_at"] = ago(6)
    result = sync.run("test", settings, hs, instantly, log=quiet)
    assert result["next_contacts_added"] == 0 and result["no_reply"] == 0
    assert hs.records["companies"][cid]["diablo_outreach_status"] == "in_outreach"



# ---- the rotation agreed on 13 Oct 2026 -------------------------------------

from outreach.next_in_line import decide  # noqa: E402


def person(pid, rank, status="sent"):
    return {"id": pid, "properties": {"diablo_hierarchy_rank": str(rank), "diablo_contact_status": status,
                                      "diablo_last_event_at": ago(20)}}


def days_ago(*days):
    now = dt.datetime.now(dt.timezone.utc)
    return [now - dt.timedelta(days=d) for d in days]


def test_rotation_order_and_week_rule():
    four = [person(f"p{i}", i) for i in (1, 2, 3, 4)]
    kw = dict(rounds=3, min_same_days=7)
    # Day 12: everyone had their first email, 3 days apart: back to person 1.
    touches = {"p1": days_ago(12), "p2": days_ago(9), "p3": days_ago(6), "p4": days_ago(3)}
    due, why = decide(four, "in_outreach", 3, touches=touches, **kw)
    assert why == "follow_up" and due["id"] == "p1"
    # Person 4 was emailed only 2 days ago: nobody yet.
    touches["p4"] = days_ago(2)
    assert decide(four, "in_outreach", 3, touches=touches, **kw) == (None, "waiting")
    # Round 2 under way: person 2 is next.
    touches = {"p1": days_ago(15, 3), "p2": days_ago(12), "p3": days_ago(9), "p4": days_ago(6)}
    assert decide(four, "in_outreach", 3, touches=touches, **kw)[0]["id"] == "p2"
    # Two people: person 1 waits until a full week after their first email.
    two = four[:2]
    touches = {"p1": days_ago(6), "p2": days_ago(3)}
    assert decide(two, "in_outreach", 3, touches=touches, **kw) == (None, "waiting_same_person")
    touches = {"p1": days_ago(7), "p2": days_ago(4)}
    assert decide(two, "in_outreach", 3, touches=touches, **kw)[0]["id"] == "p1"
    # Everyone had 3 emails and 3 days passed: No reply.
    touches = {p["id"]: days_ago(30, 20, 10 - i) for i, p in enumerate(four)}
    assert decide(four, "in_outreach", 3, touches=touches, **kw) == (None, "no_reply")
    # Later rounds without the emails key: wait, never mark No reply.
    assert decide(four, "in_outreach", 3, touches=None, **kw) == (None, "waiting_for_emails_key")
    # A bounced person is skipped; a reply anywhere stops everyone.
    bounced = [person("p1", 1, "bounced")] + four[1:]
    touches = {"p2": days_ago(12), "p3": days_ago(9), "p4": days_ago(6)}
    assert decide(bounced, "in_outreach", 3, touches=touches, **kw)[0]["id"] == "p2"
    replied = [person("p1", 1, "replied")] + four[1:]
    assert decide(replied, "in_outreach", 3, touches=touches, **kw) == (None, "stopped")


class FakeEmails:
    def __init__(self):
        self.sent, self.replies = {}, []

    def sent_emails(self, lead_email, campaign_id=None):
        return list(self.sent.get(lead_email, []))

    def reply(self, email, subject, html, text):
        self.replies.append({"to": email, "subject": subject, "html": html, "text": text})
        lead = next(k for k, v in self.sent.items() if email in v)
        self.sent[lead].append({"id": f"r{len(self.replies)}", "eaccount": email["eaccount"],
                                "subject": "Re: " + subject, "timestamp_email": dt.datetime.now(dt.timezone.utc).isoformat()})


def test_sync_sends_the_second_round_as_a_reply(settings):
    hs, instantly, emails = FakeCRM(), FakeInstantly(), FakeEmails()
    cid, people = company_with_three(hs, "Turn Co", "turn.in")
    hs.records["companies"][cid]["diablo_outreach_status"] = "in_outreach"
    for i, pid in enumerate(people):
        hs.records["contacts"][pid].update(diablo_contact_status="sent", firstname=f"P{i + 1}",
                                           diablo_last_event_at=ago(9 - 3 * i))
        emails.sent[f"p{i + 1}@turn.in"] = [{"id": f"e{i}", "eaccount": "sales@diablosnosugar.com",
                                             "subject": "Partnering to establish Diablo", "timestamp_email": ago(9 - 3 * i)}]
    moved = sync.advance(hs, instantly, settings, log=quiet)  # no key: the emails wait
    assert moved["waiting_for_emails_key"] == 1 and moved["follow_ups_sent"] == 0
    moved = sync.advance(hs, instantly, settings, log=quiet, emails_api=emails)
    assert moved["follow_ups_sent"] == 1 and moved["no_reply"] == 0
    sent = emails.replies[0]
    assert sent["to"]["id"] == "e0" and sent["subject"] == "Partnering to establish Diablo"
    assert "Hi P1," in sent["text"] and "samples" in sent["text"] and "{{" not in sent["html"]
    assert hs.records["contacts"][people[0]]["diablo_last_event"] == "email_2_sent"
    # Straight after, the company waits 3 days before anyone else.
    assert sync.advance(hs, instantly, settings, log=quiet, emails_api=emails)["follow_ups_sent"] == 0
