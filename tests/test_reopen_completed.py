"""23 Nov 2026 (Ariel): Instantly marks a campaign Completed once it has sent every introduction in it, and a
Completed campaign does not send what button 4 adds later until someone presses Resume. Button 4 now switches a
Completed Diablo campaign back on whenever introductions wait in it, and nothing else.

Every case goes through button 4 itself (send.run), so the same tests also show what the code did before."""
import datetime as dt

import pytest

from outreach import campaign_guard, daily_report, send

from .fakes import FakeCRM, FakeInstantly
from .test_daily_report import Accounts, _details
from .test_next_in_line import ago, company_with_three, lead, quiet, settings, tmp_runs  # noqa: F401

COMPLETED, RUNNING = 3, 1


def first_batch(settings, status=COMPLETED):
    """Noble Foods' introduction went out yesterday and Instantly then marked the campaign `status`."""
    hs, instantly = FakeCRM(), FakeInstantly()
    company_with_three(hs, "Noble Foods", "noble.in")
    send.run("test", settings, hs, instantly, log=quiet)
    camp = next(iter(instantly.campaigns))
    lead(instantly, "p1@noble.in")["timestamp_last_contact"] = ago(1)
    instantly.campaigns[camp]["status"] = status
    return hs, instantly, camp


def activated(instantly):
    return getattr(instantly, "activated", [])


# ---- 1. The problem: introductions added to a Completed campaign ---------------------------------------

def test_1_new_introductions_into_a_completed_campaign_switch_it_back_on(settings):
    hs, instantly, camp = first_batch(settings)
    company_with_three(hs, "Second Foods", "second.in")
    lines = []
    result = send.run("test", settings, hs, instantly, log=lines.append)
    assert result["queued"] == 1 and len(instantly.leads[camp]) == 2  # Second Foods' person 1 is in it
    assert activated(instantly) == [camp] and instantly.campaigns[camp]["status"] == RUNNING
    assert any("Instantly had marked it Completed; switched back on" in x for x in lines)


def test_2_introductions_added_earlier_and_never_sent_switch_it_back_on(settings):
    """This morning's case: the leads went in while the campaign was Completed and nobody pressed Resume."""
    hs, instantly, camp = first_batch(settings, status=RUNNING)
    company_with_three(hs, "Second Foods", "second.in")
    send.run("test", settings, hs, instantly, log=quiet)  # added while it still ran
    instantly.campaigns[camp]["status"] = COMPLETED  # then Instantly marked it Completed with it unsent
    send.run("test", settings, hs, instantly, log=quiet)  # nothing new to add at this run
    assert activated(instantly) == [camp]


def test_3_several_introductions_in_one_run_switch_it_on_once(settings):
    hs, instantly, camp = first_batch(settings)
    for name, domain in (("Second Foods", "second.in"), ("Third Foods", "third.in"), ("Fourth Foods", "fourth.in")):
        company_with_three(hs, name, domain)
    assert send.run("test", settings, hs, instantly, log=quiet)["queued"] == 3
    assert activated(instantly) == [camp]


# ---- 2. What must be left alone -------------------------------------------------------------------------

def test_4_a_completed_campaign_with_nothing_waiting_is_left_alone(settings):
    hs, instantly, camp = first_batch(settings)
    send.run("test", settings, hs, instantly, log=quiet)  # nobody new
    assert activated(instantly) == []


@pytest.mark.parametrize("status, what", [(RUNNING, "already running"), (2, "paused by a person"),
                                          (-2, "Bounce Protect"), (-1, "sending account problem"),
                                          (-99, "suspended"), (0, "not started")])
def test_5_any_other_state_is_never_switched_on_by_this(settings, status, what):
    hs, instantly, camp = first_batch(settings, status=status)
    company_with_three(hs, "Second Foods", "second.in")
    send.run("test", settings, hs, instantly, log=quiet)
    assert activated(instantly) == [], what


def test_6_finished_bounced_or_unsubscribed_leads_do_not_count_as_waiting(settings):
    hs, instantly, camp = first_batch(settings)
    lead(instantly, "p1@noble.in").update(timestamp_last_contact=None, status=3)  # finished in Instantly
    send.run("test", settings, hs, instantly, log=quiet)
    assert activated(instantly) == []
    view = {f"{s}@x.example": {"_campaign_id": camp, "status": s} for s in (3, -1, -2, -3)}
    assert campaign_guard.unsent_by_campaign(view) == {}
    view["new@x.example"] = {"_campaign_id": camp, "status": 1}
    view["sent@x.example"] = {"_campaign_id": camp, "status": 1, "timestamp_last_contact": ago(0.1)}
    assert campaign_guard.unsent_by_campaign(view) == {camp: 1}


def test_7_a_campaign_that_is_not_diablos_is_never_touched(settings):
    hs, instantly, camp = first_batch(settings)
    instantly.campaigns["other"] = {"name": "Someone else's campaign", "status": COMPLETED}
    instantly.leads["other"] = [{"email": "x@other.example", "_campaign_id": "other"}]
    send.run("test", settings, hs, instantly, log=quiet)
    assert "other" not in activated(instantly)


def test_8_a_trial_run_changes_nothing(settings):
    hs, instantly, camp = first_batch(settings)
    company_with_three(hs, "Second Foods", "second.in")
    send.run("test", settings, hs, instantly, log=quiet, dry_run=True)
    assert activated(instantly) == [] and instantly.campaigns[camp]["status"] == COMPLETED


# ---- 3. When Instantly refuses ---------------------------------------------------------------------------

def test_9_if_instantly_refuses_amodh_is_told_and_the_next_run_tries_again(settings, monkeypatch):
    sent = []
    monkeypatch.setattr("outreach.alert.send", lambda subject, text, log=print: sent.append(subject))
    hs, instantly, camp = first_batch(settings)
    company_with_three(hs, "Second Foods", "second.in")
    instantly.refuse_activate = True
    result = send.run("test", settings, hs, instantly, log=quiet)
    assert result["queued"] == 1  # the introduction is still added and its contact moves on
    assert activated(instantly) == [] and instantly.campaigns[camp]["status"] == COMPLETED
    assert any("could not be switched back on" in s for s in sent)
    send.run("test", settings, hs, instantly, log=quiet)  # next run: the unsent lead is still waiting
    assert activated(instantly) == [camp]


# ---- 4. The daily email ----------------------------------------------------------------------------------

def test_10_the_daily_email_says_what_happened(settings):
    hs, instantly, camp = first_batch(settings)
    company_with_three(hs, "Second Foods", "second.in")
    send.run("test", settings, hs, instantly, log=quiet)
    today = dt.datetime.now(campaign_guard_uk()).strftime("%Y-%m-%d")
    assert campaign_guard.reopened_on(today) == {camp: 1}
    instantly.campaigns[camp]["status"] = COMPLETED  # sent again since, so Completed once more
    instantly.campaigns[camp]["email_list"] = ["sales@x.example"]
    _details(instantly, connected=1)
    accounts = Accounts([{"email": "sales@x.example", "status": 1, "warmup_status": 1, "stat_warmup_score": 100}])
    h = daily_report.health(instantly, settings, accounts, view={}, day=today)
    row = next(r for r in h["campaigns"] if r[5] == camp)
    assert row[2] == "Completed"
    assert row[4][0] == "None: switched back on by itself 1 time this day, after Instantly marked it Completed"
    campaign_guard.save({})  # another day: nothing switched back on
    later = daily_report.health(instantly, settings, accounts, view={}, day=today)
    assert next(r for r in later["campaigns"] if r[5] == camp)[4][0] == (
        "None: switched back on by itself when new introductions are added")


def campaign_guard_uk():
    from outreach.daily_log import UK
    return UK
