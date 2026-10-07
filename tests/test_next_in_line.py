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


def test_one_person_at_a_time_then_the_next_on_day_four(settings):
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

    # Day 4 and still no reply: the next person gets their own email in the same campaign.
    hs.records["contacts"][first]["diablo_last_event_at"] = ago(4)
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
