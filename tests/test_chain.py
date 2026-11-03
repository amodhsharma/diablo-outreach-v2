"""Everyone at a company is emailed, each with their own introduction and a reminder sent as a forward of
it, and the backlog of companies closed as "no response" is reopened oldest first (2 Nov 2026, Ariel)."""

import datetime as dt

import pytest

from outreach import chain, send, sync
from outreach.common import load_settings
from outreach.next_in_line import decide_chain
from outreach.stages import LeadStatus

from .fakes import FakeCRM, FakeEmails, FakeInstantly
from .test_corrupt import LS, ORDER, company, lead, quiet, rec

NOW = dt.datetime(2026, 11, 20, 12, 0, tzinfo=dt.timezone.utc)
RULES = {"enabled": True, "gap": 3, "reminder": 7, "close": 3, "inbox_reminder": True}


@pytest.fixture
def settings():
    s = load_settings()
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"
    return s


def ago(days):
    return NOW - dt.timedelta(days=days)


def person(pid, rank, state, title="Buyer", **props):
    props.setdefault("diablo_personal_line", "Line.")
    return {"id": pid, "state": state, "sent_at": None,
            "properties": {"email": f"{pid}@x.example", "jobtitle": title, ORDER: str(rank), **props}}


def at(day):
    """The time `day` days after person 1's introduction, which went out 20 days before NOW."""
    return ago(20) + dt.timedelta(days=day)


# ---- The schedule -------------------------------------------------------------------------------

def test_two_people_introductions_reminders_and_the_close():
    p1, p2 = person("p1", 1, "sent"), person("p2", 2, "approved")
    touches = {"p1": [at(0)]}
    assert decide_chain([p1, p2], "in_outreach", at(2), touches, RULES) == (None, "waiting")
    assert decide_chain([p1, p2], "in_outreach", at(3), touches, RULES) == (p2, "next")
    p2["state"], touches["p2"] = "sent", [at(3)]
    assert decide_chain([p1, p2], "in_outreach", at(6.9), touches, RULES) == (None, "waiting_same_person")
    assert decide_chain([p1, p2], "in_outreach", at(7), touches, RULES) == (p1, "reminder")
    touches["p1"].append(at(7))
    assert decide_chain([p1, p2], "in_outreach", at(10), touches, RULES) == (p2, "reminder")
    touches["p2"].append(at(10))
    assert decide_chain([p1, p2], "in_outreach", at(12.9), touches, RULES) == (None, "waiting_for_reply")
    assert decide_chain([p1, p2], "in_outreach", at(13), touches, RULES) == (None, "no_reply")


def test_every_contact_is_emailed_however_many_there_are():
    people = [person("p1", 1, "sent"), person("p2", 2, "sent"), person("p3", 3, "approved"),
              person("p4", 4, "approved", title="Company inbox (from website)")]
    touches = {"p1": [at(0)], "p2": [at(3)]}
    assert decide_chain(people, "in_outreach", at(6), touches, RULES) == (people[2], "next")
    people[2]["state"], touches["p3"] = "sent", [at(6)]
    assert decide_chain(people, "in_outreach", at(7), touches, RULES) == (people[0], "reminder")
    touches["p1"].append(at(7))
    assert decide_chain(people, "in_outreach", at(9), touches, RULES) == (people[3], "next")  # the inbox last


def test_a_contact_without_a_line_is_skipped_and_the_company_still_closes():
    p1, p2 = person("p1", 1, "sent"), person("p2", 2, "pending")
    touches = {"p1": [at(0), at(7)]}
    assert decide_chain([p1, p2], "in_outreach", at(10), touches, RULES) == (None, "no_reply")


def test_a_company_inbox_gets_its_reminder_only_when_switched_on():
    inbox = person("i1", 1, "sent", title="Company inbox (from website)")
    touches = {"i1": [at(0)]}
    assert decide_chain([inbox], "in_outreach", at(7), touches, RULES) == (inbox, "reminder")
    off = dict(RULES, inbox_reminder=False)
    assert decide_chain([inbox], "in_outreach", at(7), touches, off) == (None, "no_reply")


def test_a_reply_or_a_stopped_company_stops_everything():
    assert decide_chain([person("p1", 1, "stop"), person("p2", 2, "approved")], "in_outreach", at(5), {},
                        RULES) == (None, "stopped")
    assert decide_chain([person("p1", 1, "sent")], "replied", at(5), {"p1": [at(0)]}, RULES) == (None, "stopped")


def test_a_reopened_company_waits_3_days_for_person_1_s_reminder_and_one_person_closes_after_7():
    state = {"reopened": {"c1": {"at": ago(1).isoformat(), "single": False},
                          "c2": {"at": ago(1).isoformat(), "single": True}}}
    cfg = chain.config(load_settings())
    two = chain.company_rules(cfg, state, "c1")
    p1, p2 = person("p1", 1, "sent"), person("p2", 2, "queued")
    touches = {"p1": [ago(30)]}
    assert decide_chain([p1, p2], "in_outreach", NOW, touches, two) == (None, "waiting_same_person")
    assert decide_chain([p1, p2], "in_outreach", NOW + dt.timedelta(days=2), touches, two) == (p1, "reminder")
    one = chain.company_rules(cfg, state, "c2")
    assert decide_chain([p1], "in_outreach", NOW, touches, one) == (p1, "reminder")
    touches["p1"].append(NOW)
    assert decide_chain([p1], "in_outreach", NOW + dt.timedelta(days=6), touches, one) == (None, "waiting_for_reply")
    assert decide_chain([p1], "in_outreach", NOW + dt.timedelta(days=7), touches, one) == (None, "no_reply")


# ---- Gate 2 for everyone once person 1 is approved -----------------------------------------------

def test_everyone_goes_to_gate_2_with_person_1_s_line_copied_where_missing():
    hs = FakeCRM()
    statuses = LeadStatus(hs)
    p1 = person("p1", 1, "approved", diablo_personal_line="Line one.", diablo_company_note="imports sweets")
    p2 = person("p2", 2, "pending", diablo_personal_line="Own line.")
    p3 = person("p3", 3, "pending", diablo_personal_line="")
    hand = person("p4", 0, "pending", diablo_personal_line="")
    hand["properties"][ORDER] = ""  # added by hand, not yet given its place by button 3
    updates = dict(chain.fill_lines([p1, p2, p3, hand], statuses, log=quiet))
    assert updates["p2"] == {LS: "APPROVED_TO_SEND"}  # its own line kept
    assert updates["p3"]["diablo_personal_line"] == "Line one." and updates["p3"]["diablo_company_note"] == "imports sweets"
    assert "p4" not in updates and p3["state"] == "approved"
    assert chain.fill_lines([person("q1", 1, "pending", diablo_personal_line=""),
                             person("q2", 2, "pending", diablo_personal_line="")], statuses, log=quiet) == []
    dead = person("d0", 0, "skipped", diablo_personal_line="The dead contact's line.")
    p5, p6 = person("p5", 1, "approved", diablo_personal_line="Current line."), person("p6", 2, "pending",
                                                                                      diablo_personal_line="")
    assert dict(chain.fill_lines([dead, p5, p6], statuses, log=quiet))["p6"]["diablo_personal_line"] == "Current line."


# ---- Button 4 with the chain on -------------------------------------------------------------------

def started(settings, days, titles=("Owner", "Buyer")):
    """Person 1's introduction went out `days` days ago; the others wait (GATE2, no line of their own)."""
    from .test_corrupt import ago as days_ago
    hs, instantly, emails = FakeCRM(), FakeInstantly(), FakeEmails()
    cid, people = company(hs, "Chain Co", "chain.example", titles)
    for pid in people[1:]:
        rec(hs, pid).update({LS: "NEW"})
        rec(hs, pid).pop("diablo_personal_line")
    send.run("test", settings, hs, instantly, log=quiet)
    lead(instantly, "p1@chain.example")["timestamp_last_contact"] = days_ago(days)
    emails.campaign_email("p1@chain.example", days_ago(days), subject="A sugar-free brand with no Australia partner yet")
    return hs, instantly, emails, cid, people


def test_person_2_gets_their_own_introduction_in_the_month_s_campaign(settings, monkeypatch):
    hs, instantly, emails, cid, (p1, p2) = started(settings, 3.1)
    monkeypatch.setenv("GITHUB_RUN_ID", "run1")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["next_contacts_added"] == 0 and rec(hs, p2)[LS] == "APPROVED_TO_SEND"  # its line was copied this run
    monkeypatch.setenv("GITHUB_RUN_ID", "run2")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["next_contacts_added"] == 1 and not emails.forwards
    assert rec(hs, p2)[LS] == "ATTEMPTED_TO_CONTACT"
    assert rec(hs, p2)["diablo_personal_line"] == rec(hs, p1)["diablo_personal_line"]  # copied over
    month = send.campaign_name(settings["sync"]["campaign_prefix"])
    camp = next(i for i, c in instantly.campaigns.items() if c["name"] == month)
    assert "p2@chain.example" in [l["email"] for l in instantly.leads[camp]]


def test_person_1_s_reminder_goes_as_a_forward_of_their_introduction(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, 8)
    rec(hs, p2)[LS] = "UNQUALIFIED"  # rejected at gate 2: only person 1 is left
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["reminders_sent"] == 1
    sent = emails.replies[-1]
    assert sent["address"] == "p1@chain.example"
    assert sent["subject"] == "Fwd: A sugar-free brand with no Australia partner yet"
    assert "Forwarded message" in sent["html"]
    assert rec(hs, p1)[LS] == "REMINDER_SENT"


def test_reminders_wait_when_the_mailbox_has_sent_its_share_today(settings):
    settings["send"]["chain"]["reminders_per_mailbox_per_day"] = 0
    settings["send"]["chain"]["reminders_by_mailbox"] = {}
    hs, instantly, emails, cid, (p1, p2) = started(settings, 8)
    rec(hs, p2)[LS] = "UNQUALIFIED"
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["reminders_sent"] == 0 and rec(hs, p1)[LS] == "ATTEMPTED_TO_CONTACT"


# ---- The backlog ----------------------------------------------------------------------------------

def closed_company(hs, instantly, name, domain, days, backups=1):
    cid, people = company(hs, name, domain, ("Owner",) + ("Buyer",) * backups)
    hs.records["companies"][cid][LS] = "Contacted, but no response, unqualified"
    rec(hs, people[0])[LS] = "CONTACTED_NO_RESPONSE_UNQUALIFIED"
    for pid in people[1:]:
        rec(hs, pid).update({LS: "COLLEAGUE_CONTACTED_NO_RESPONSE"})
        rec(hs, pid).pop("diablo_personal_line")
    camp = next(iter(instantly.campaigns), None) or instantly.create_campaign({"name": "Diablo | OCT2026"})["id"]
    instantly.leads[camp].append({"email": f"p1@{domain}", "timestamp_last_contact": ago(days).isoformat(),
                                  "status": 3})
    return cid, people


def test_the_backlog_is_reopened_oldest_first_in_the_room_left(settings):
    hs, instantly = FakeCRM(), FakeInstantly()
    newer, (n1, n2) = closed_company(hs, instantly, "Newer", "newer.example", 10)
    older, (o1, o2) = closed_company(hs, instantly, "Older", "older.example", 25)
    single, (s1,) = closed_company(hs, instantly, "Solo", "solo.example", 20, backups=0)
    settings["send"]["chain"]["backlog_per_day"] = 2
    out = chain.run_backlog(hs, instantly, settings, log=quiet, now=NOW, emails_api=FakeEmails())
    assert out["reopened"] == 2
    assert hs.records["companies"][older][LS] == "Attempted to Contact"  # the oldest first
    assert hs.records["companies"][single][LS] == "Attempted to Contact"  # then the next oldest
    assert hs.records["companies"][newer][LS] == "Contacted, but no response, unqualified"  # waits for tomorrow
    assert rec(hs, o2)[LS] == "ATTEMPTED_TO_CONTACT" and rec(hs, o2)["diablo_personal_line"] == "Line."
    assert rec(hs, o1)[LS] == "ATTEMPTED_TO_CONTACT" and rec(hs, s1)[LS] == "ATTEMPTED_TO_CONTACT"
    month = send.campaign_name(settings["sync"]["campaign_prefix"])
    camp = next(i for i, c in instantly.campaigns.items() if c["name"] == month)
    assert [l["email"] for l in instantly.leads[camp]] == ["p2@older.example"]
    state = chain.load_state()
    assert state["reopened"][str(single)]["single"] and not state["reopened"][str(older)]["single"]
    assert chain.run_backlog(hs, instantly, settings, log=quiet, now=NOW)["reopened"] == 0  # 2 a day at most


def test_the_backlog_waits_when_the_new_introductions_fill_the_day(settings):
    hs, instantly = FakeCRM(), FakeInstantly()
    closed_company(hs, instantly, "Old", "old.example", 25)
    camp = next(iter(instantly.campaigns))
    instantly.leads[camp] += [{"email": f"n{i}@new.example", "status": 1} for i in range(30)]  # 30 waiting to go
    assert chain.run_backlog(hs, instantly, settings, log=quiet, now=NOW)["reopened"] == 0


def test_the_room_counts_what_was_sent_today_and_what_waits():
    leads = {"a": {"timestamp_last_contact": NOW.isoformat()}, "b": {"status": 1}, "c": {"status": 3},
             "d": {"timestamp_last_contact": ago(2).isoformat()}}
    assert chain.room_today(leads, 10, NOW) == 8


def test_a_contact_without_a_line_never_holds_the_company_open():
    p1, p2 = person("p1", 1, "sent"), person("p2", 2, "approved", diablo_personal_line="")
    assert decide_chain([p1, p2], "in_outreach", at(10), {"p1": [at(0), at(7)]}, RULES) == (None, "no_reply")


def test_the_backlog_never_reopens_a_company_that_replied_or_opted_out_late(settings):
    hs, instantly = FakeCRM(), FakeInstantly()
    replied, _ = closed_company(hs, instantly, "Replied", "replied.example", 25)
    opted, _ = closed_company(hs, instantly, "Opted", "opted.example", 24)
    quiet_one, _ = closed_company(hs, instantly, "Quiet", "quiet.example", 23)
    camp = next(iter(instantly.campaigns))
    for l in instantly.leads[camp]:
        if l["email"] == "p1@replied.example":
            l["email_reply_count"] = 1
        if l["email"] == "p1@opted.example":
            l["status"] = -2
    out = chain.run_backlog(hs, instantly, settings, log=quiet, now=NOW)
    assert out["reopened"] == 1
    assert hs.records["companies"][replied][LS] == hs.records["companies"][opted][LS] == \
        "Contacted, but no response, unqualified"
    assert hs.records["companies"][quiet_one][LS] == "Attempted to Contact"


def test_the_backlog_leaves_contacts_added_by_hand_to_button_3_and_never_reopens_twice(settings):
    hs, instantly = FakeCRM(), FakeInstantly()
    cid, (p1, p2) = closed_company(hs, instantly, "Hand", "hand.example", 25)
    hand = hs.add("contacts", email="hand@hand.example", jobtitle="Buyer", hs_lead_status="NEW")
    hs.links[hand] = [cid]
    chain.run_backlog(hs, instantly, settings, log=quiet, now=NOW)
    assert rec(hs, hand)[LS] == "NEW" and rec(hs, p2)[LS] == "ATTEMPTED_TO_CONTACT"
    hs.records["companies"][cid][LS] = "Contacted, but no response, unqualified"  # closed again later
    chain.save_state({})  # even with the state file lost, "Outreach stopped because" remembers
    assert chain.run_backlog(hs, instantly, settings, log=quiet, now=NOW)["reopened"] == 0


def test_a_reply_after_the_company_closed_is_still_seen(settings):
    hs, instantly = FakeCRM(), FakeInstantly()
    cid, (p1, p2) = closed_company(hs, instantly, "Late", "late.example", 25)
    camp = next(iter(instantly.campaigns))
    next(l for l in instantly.leads[camp] if l["email"] == "p1@late.example")["email_reply_count"] = 1
    sync.run("test", settings, hs, instantly, log=quiet)
    assert rec(hs, p1)[LS] == "IN_PROGRESS" and hs.records["companies"][cid][LS] == "In Progress"
    assert rec(hs, p2)[LS] == "COLLEAGUE_REPLIED"


def test_sales_and_info_send_up_to_20_reminders_a_day_the_others_10():
    cfg = chain.config(load_settings())
    state = {}
    assert chain.reminders_left(state, "Sales@diablosnosugar.com", cfg, NOW) == 20
    assert chain.reminders_left(state, "info@diablosnosugar.com", cfg, NOW) == 20
    assert chain.reminders_left(state, "dana@diabloexport.com", cfg, NOW) == 10
