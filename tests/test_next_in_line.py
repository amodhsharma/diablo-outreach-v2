"""One loop per company (agreed 14 Oct 2026): person 1's introduction, then every 3 days a forward
of the chain to the next person naming the colleague before them, then one reminder to person 1,
then Unqualified 3 days later. Everyone stops when anyone at the company replies."""

import datetime as dt

import pytest

from outreach import common, send, sync
from outreach.common import load_settings

from .fakes import FakeCRM, FakeEmails, FakeInstantly


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


@pytest.fixture
def settings():
    s = load_settings()
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"  # the real link is not set yet ("xxx")
    return s


def ago(days):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()


LS = "hs_lead_status"


def company_with_three(hs, name, domain):
    cid = hs.add("companies", name=name, domain=domain, country="India", industry_type="Distributor Wholesaler",
                 **{LS: "GATE1: Approved for outreach"})
    people = []
    for rank, title in enumerate(("Managing Director", "Head of Buying", "Category Manager"), start=1):
        pid = hs.add("contacts", email=f"p{rank}@{domain}", firstname=f"P{rank}", jobtitle=title,
                     diablo_outreach_order=str(rank), diablo_personal_line="Line.", diablo_company_note="imports European sweets", **{LS: "APPROVED_TO_SEND"})
        hs.links[pid] = [cid]
        people.append(pid)
    return cid, people


def lead(instantly, email):
    return next(l for ls in instantly.leads.values() for l in ls if l["email"] == email)


def status_of(hs, pid):
    return hs.records["contacts"][pid][LS]


def started(settings, name="Noble Foods", domain="noble.in", days=3.5):
    """A company of three, all approved; person 1's introduction went out `days` days ago."""
    hs, instantly, emails = FakeCRM(), FakeInstantly(), FakeEmails()
    cid, people = company_with_three(hs, name, domain)
    for i, pid in enumerate(people):
        hs.records["contacts"][pid]["lastname"] = f"L{i + 1}"
    result = send.run("test", settings, hs, instantly, log=quiet)
    assert result["queued"] == 1 and result["waiting"] == 2  # only person 1 goes through the campaign
    lead(instantly, f"p1@{domain}")["timestamp_last_contact"] = ago(days)
    emails.campaign_email(f"p1@{domain}", ago(days))
    return hs, instantly, emails, cid, people


def test_the_one_loop_from_introduction_to_unqualified(settings):
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=2)
    camp_id = next(iter(instantly.campaigns))
    # Day 2: nothing yet.
    assert sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)["forwards_sent"] == 0
    assert send.run("test", settings, hs, instantly, log=quiet)["queued"] == 0  # send never adds persons 2+

    # Day 3: person 2 gets a forward of person 1's email, naming person 1.
    emails.emails[0]["timestamp_email"] = ago(3.1)
    lead(instantly, "p1@noble.in")["timestamp_last_contact"] = ago(3.1)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 1 and status_of(hs, p2) == "FORWARD_SENT"
    fwd = emails.forwards[0]
    assert fwd["to"] == "p2@noble.in" and fwd["of"]["id"] == emails.emails[0]["id"]
    assert fwd["subject"] == "Fwd: Partnering to establish Diablo"
    assert ("Hi P2,\n\nIn case our earlier note to your colleague P1 L1 did not reach the right desk, we wanted "
            "to share it with you as well.\n\nLine.\n\nWould a brief 10-minute call with our outreach lead") in fwd["text"]
    assert "{{" not in fwd["html"]
    assert [l["email"] for l in instantly.leads[camp_id]] == ["p1@noble.in"]  # still one campaign lead

    # Straight after: the company waits 3 days.
    assert sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)["forwards_sent"] == 0

    # Day 6: person 3 gets a forward of the latest email in the chain (the one to person 2), naming person 2.
    emails.emails[-1]["timestamp_email"] = ago(3.1)
    emails.emails[0]["timestamp_email"] = ago(6.2)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 1 and status_of(hs, p3) == "FORWARD_SENT"
    fwd = emails.forwards[1]
    assert fwd["to"] == "p3@noble.in" and fwd["of"]["to_address_email_list"] == "p2@noble.in"
    assert "your colleague P2 L2 did not reach" in fwd["text"]
    assert fwd["subject"] == "Fwd: Partnering to establish Diablo"

    # Day 9: back to person 1, once, as a reply in their own thread.
    emails.emails[-1]["timestamp_email"] = ago(3.1)
    emails.emails[1]["timestamp_email"] = ago(6.1)
    emails.emails[0]["timestamp_email"] = ago(9.2)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["reminders_sent"] == 1 and moved["forwards_sent"] == 0
    assert status_of(hs, p1) == "REMINDER_SENT" and status_of(hs, p2) == "FORWARD_SENT"
    rem = emails.replies[0]
    # Under person 1's own first email (not the forwards), with its own subject (follow_up_2, 15 Oct 2026).
    assert rem["to"]["id"] == emails.emails[0]["id"] and rem["subject"] == "Bad Jokes + Europe's largest Brand"
    assert "Hi P1,\n\nI imagine your inbox is about as full as a regular chocolate bar is of sugar." in rem["text"]
    assert "I hope that bad joke buys me another email :)" in rem["text"]
    assert "Would this week work, or would next week suit better?" in rem["text"]
    assert "Joshua\nInternational Account Executive\nDiablo Sugar Free\nBook a quick meeting with us: " in rem["text"]
    assert "colleague" not in rem["text"] and "{{" not in rem["text"] and "privacy" not in rem["text"].lower()

    # Persons 2 and 3 never get a second email; 3 days after the reminder the company is Unqualified.
    assert sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)["no_reply"] == 0
    emails.emails[-1]["timestamp_email"] = ago(3.1)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["no_reply"] == 1 and hs.records["companies"][cid][LS] == "Unqualified"
    assert len(emails.forwards) == 2 and len(emails.replies) == 1


def test_a_reply_to_a_forward_stops_the_company(settings):
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)  # forward to person 2
    emails.received("p2@noble.in", ago(0))
    for e in emails.emails[:-1]:
        e["timestamp_email"] = ago(4)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["replied"] == 1 and moved["forwards_sent"] == 0
    assert status_of(hs, p2) == "IN_PROGRESS" and hs.records["companies"][cid][LS] == "In Progress"
    assert status_of(hs, p3) == "APPROVED_TO_SEND"  # never emailed


def test_a_reply_through_the_campaign_also_stops_everyone(settings):
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    lead(instantly, "p1@noble.in").update(email_reply_count=1, timestamp_last_reply=ago(0))
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["companies"][cid][LS] == "In Progress" and not emails.forwards


def test_forwards_and_the_reminder_wait_for_the_emails_key(settings):
    hs, instantly, emails, cid, people = started(settings, days=5)
    moved = sync.run("test", settings, hs, instantly, log=quiet)  # no INSTANTLY_EMAILS_KEY
    assert moved["waiting_for_emails_key"] == 1 and moved["forwards_sent"] == 0


def test_one_person_only_gets_a_reminder_after_a_week_then_unqualified(settings):
    hs, instantly, emails = FakeCRM(), FakeInstantly(), FakeEmails()
    cid = hs.add("companies", name="Quiet Co", domain="quiet.in", country="India", **{LS: "GATE1: Approved for outreach"})
    only = hs.add("contacts", email="boss@quiet.in", firstname="Bo", diablo_outreach_order="1",
                  diablo_personal_line="Line.", diablo_company_note="imports European sweets", **{LS: "APPROVED_TO_SEND"})
    hs.links[only] = [cid]
    send.run("test", settings, hs, instantly, log=quiet)
    lead(instantly, "boss@quiet.in")["timestamp_last_contact"] = ago(5)
    emails.campaign_email("boss@quiet.in", ago(5))
    assert sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)["reminders_sent"] == 0
    emails.emails[0]["timestamp_email"] = ago(7.1)
    assert sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)["reminders_sent"] == 1
    emails.emails[-1]["timestamp_email"] = ago(3.1)
    assert sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)["no_reply"] == 1
    assert hs.records["companies"][cid][LS] == "Unqualified"


def test_waits_for_gate_two_before_moving_on(settings):
    hs, instantly, emails = FakeCRM(), FakeInstantly(), FakeEmails()
    cid, (first, second, third) = company_with_three(hs, "Slow Co", "slow.in")
    hs.records["contacts"][second][LS] = "NEW_PERSONAL_LINE_FILLED"  # not approved yet
    hs.records["contacts"][third][LS] = "NEW_PERSONAL_LINE_FILLED"
    send.run("test", settings, hs, instantly, log=quiet)
    lead(instantly, "p1@slow.in")["timestamp_last_contact"] = ago(6)
    emails.campaign_email("p1@slow.in", ago(6))
    result = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert result["forwards_sent"] == 0 and result["no_reply"] == 0 and result["reminders_sent"] == 0
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"


def test_a_bounce_is_never_named_and_the_loop_carries_on(settings):
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, name="Bounce Co", domain="bounce.in", days=4)
    lead(instantly, "p1@bounce.in").update(status=-1)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert status_of(hs, p1) == "UNQUALIFIED" and hs.records["companies"][cid][LS] == "Attempted to Contact"
    # Person 1 bounced: nobody to name and nothing worth forwarding, so person 2 gets the introduction.
    assert moved["forwards_sent"] == 0 and moved["next_contacts_added"] == 1
    assert status_of(hs, p2) == "ATTEMPTED_TO_CONTACT"
    camp_id = next(iter(instantly.campaigns))
    assert [l["email"] for l in instantly.leads[camp_id]] == ["p1@bounce.in", "p2@bounce.in"]


# ---- the rule itself --------------------------------------------------------

from outreach.next_in_line import decide  # noqa: E402


def person(pid, rank, state="sent"):
    return {"id": pid, "properties": {"diablo_outreach_order": str(rank)}, "state": state,
            "sent_at": None, "campaign": "c1"}


def days_ago(*days):
    now = dt.datetime.now(dt.timezone.utc)
    return [now - dt.timedelta(days=d) for d in days]


def test_the_rule_for_four_people():
    kw = dict(min_same_days=7)
    four = [person("p1", 1), person("p2", 2, "approved"), person("p3", 3, "approved"), person("p4", 4, "approved")]
    # Nobody emailed yet: person 1's introduction.
    fresh = [dict(p, state="approved") for p in four]
    assert decide(fresh, "approved", 3, touches={}, **kw)[1] == "next"
    # Person 1 emailed 3 days ago: person 2 gets a forward.
    due, why = decide(four, "in_outreach", 3, touches={"p1": days_ago(3)}, **kw)
    assert (due["id"], why) == ("p2", "forward")
    # Only 2 days: wait.
    assert decide(four, "in_outreach", 3, touches={"p1": days_ago(2)}, **kw) == (None, "waiting")
    # All four emailed (days 0, 3, 6, 9): person 1's reminder on day 12.
    done = [person(f"p{i}", i) for i in (1, 2, 3, 4)]
    touches = {"p1": days_ago(12), "p2": days_ago(9), "p3": days_ago(6), "p4": days_ago(3)}
    due, why = decide(done, "in_outreach", 3, touches=touches, **kw)
    assert (due["id"], why) == ("p1", "reminder")
    # Reminder sent 3 days ago: the end.
    touches["p1"] = days_ago(15, 3)
    assert decide(done, "in_outreach", 3, touches=touches, **kw) == (None, "no_reply")
    # Two people: person 1's reminder waits for the full week.
    two = done[:2]
    assert decide(two, "in_outreach", 3, touches={"p1": days_ago(6), "p2": days_ago(3)}, **kw) == (None, "waiting_same_person")
    assert decide(two, "in_outreach", 3, touches={"p1": days_ago(7), "p2": days_ago(4)}, **kw)[1] == "reminder"
    # Without the emails key: wait, never give up.
    assert decide(four, "in_outreach", 3, touches=None, **kw)[1] in ("waiting_for_emails_key", "waiting")
    # A reply anywhere, or a person's own status, stops everyone.
    assert decide([person("p1", 1, "stop")] + four[1:], "in_outreach", 3, touches={"p1": days_ago(5)}, **kw) == (None, "stopped")
    assert decide(four, "team", 3, touches={"p1": days_ago(5)}, **kw) == (None, "stopped")


def test_test_gaps_need_confirm_and_never_run_on_live(settings):
    from outreach.common import PipelineError
    from outreach.next_in_line import apply_test_gaps
    assert apply_test_gaps(settings, "test", "") is False
    assert settings["send"]["next_contact_after_days"] == 3  # normal gaps untouched
    with pytest.raises(PipelineError, match="CONFIRM"):
        apply_test_gaps(settings, "test", "confirm")
    with pytest.raises(PipelineError, match="refused for the live"):
        apply_test_gaps(settings, "live", "CONFIRM")
    assert apply_test_gaps(settings, "test", "CONFIRM") is True
    assert settings["send"]["next_contact_after_days"] * 24 * 60 == pytest.approx(15)
    assert settings["send"]["rotation"]["min_days_same_person"] * 24 * 60 == pytest.approx(15)


def test_with_test_gaps_the_next_email_is_due_after_15_minutes(settings):
    from outreach.next_in_line import apply_test_gaps
    apply_test_gaps(settings, "test", "CONFIRM")
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=16 / (24 * 60))
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 1 and "your colleague P1 L1" in emails.forwards[0]["text"]
    assert sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)["forwards_sent"] == 0


def test_the_run_summary_and_the_overview_say_what_happened(settings, tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    text = summary.read_text()
    assert "## Button 4: what was sent this run" in text
    assert "| Noble Foods | Head of Buying | Forward sent, naming the Managing Director (Lead Status: Forward sent) |" in text
    assert "@" not in text and "P2" not in text  # job titles only: no names or email addresses
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert "| Noble Foods | the next email, 3 days after the last one |" in summary.read_text()
    view = sync.overview(hs, instantly, settings, emails_api=emails)
    assert "**Noble Foods**: next is the next email, 3 days after the last one, due" in view
    assert "| Noble Foods | 2 | Head of Buying | Forward sent |" in view
    assert "| Noble Foods | 3 | Category Manager | GATE2: Approved to send | not yet |" in view
    assert "@" not in view


def test_without_the_new_choices_the_forward_falls_back_to_attempted(settings):
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    for value in ("FORWARD_SENT", "REMINDER_SENT"):  # an account where button 1 has not added them yet
        hs.options[("contacts", "hs_lead_status")].pop(value)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert status_of(hs, p2) == "ATTEMPTED_TO_CONTACT"
