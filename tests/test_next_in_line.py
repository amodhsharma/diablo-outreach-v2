"""One loop per company (agreed 14 Oct 2026): person 1's introduction, then every 3 days a forward
of the chain to the next person naming the colleague before them, then one reminder to person 1,
then Unqualified 3 days later. Everyone stops when anyone at the company replies."""

import datetime as dt

import pytest

from outreach import common, send, sync
from outreach.common import load_settings
from outreach.schema import INBOX_TITLE

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
    # These tests cover the whole loop with its forwards and reminder, which is kept in the code but
    # switched off since 21 Oct 2026 (follow_ups_to_people: false); the off mode has its own tests.
    s["send"]["follow_ups_to_people"] = True
    s["send"]["reminder_to_company_inbox"] = True
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
    # forward_2.json (19 Oct 2026): the company note is the reason, then the fit and the call.
    assert ("Hi P2 L2,\n\nA few days ago I wrote to your colleague P1 L1, as we noticed Noble Foods imports European "
            "sweets. We do not yet have a direct partner in India, and we believe your company would be the right "
            "fit for us.\n\nMy earlier note is below, and our catalogue is here:") in fwd["text"]
    assert "Would this week work for a short call with our Strategy Director, or would next week suit better?" in fwd["text"]
    assert "Line." not in fwd["text"] and "Privacy notice" not in fwd["text"]  # no personal line, no privacy link
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
    assert "your colleague P2 L2, as we noticed" in fwd["text"]
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
    assert rem["address"] == "p1@noble.in"  # 20 Oct 2026: sent to person 1 themselves, not back to our mailbox
    assert "Hi P1 L1,\n\nI imagine your inbox is about as full as a regular chocolate bar is of sugar." in rem["text"]
    assert "I hope that bad joke buys me another email :)" in rem["text"]
    assert "Would this week work, or would next week suit better?" in rem["text"]
    assert "Book a quick meeting with us: " in rem["text"] and "Best regards,\n| Joshua\n| International Account Executive\n| Diablo Sugar Free" in rem["text"]
    assert "colleague" not in rem["text"] and "{{" not in rem["text"] and "privacy" not in rem["text"].lower()

    # Persons 2 and 3 never get a second email; 3 days after the reminder the company is Unqualified.
    assert sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)["no_reply"] == 0
    emails.emails[-1]["timestamp_email"] = ago(3.1)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["no_reply"] == 1 and hs.records["companies"][cid][LS] == "Contacted, but no response, unqualified"  # 21 Oct 2026
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
    # Never emailed; since 19 Oct 2026 the others show that a colleague answered, not gate 2.
    assert status_of(hs, p3) == "COLLEAGUE_REPLIED" and status_of(hs, p1) == "COLLEAGUE_REPLIED"


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
    assert hs.records["companies"][cid][LS] == "Contacted, but no response, unqualified"


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


def test_signature_name_from_the_mailbox_is_off_by_default_and_follows_the_mailbox_when_on(settings):
    """Provision added 18 Oct 2026, switched off: every email is signed with signature.name."""
    s = settings["send"]
    assert s["signature"]["name_from_mailbox"] is False
    assert send.sender_name_for(s, "dana@diabloexport.com") == s["signature"]["name"]
    _, body = send._template("templates/template_3.json", s)
    assert "{{sendingAccountFirstName}}" not in body and s["signature"]["name"] in body
    # Switched on: forwards and the reminder use the name listed for their mailbox, the first email
    # (mailbox picked by Instantly) uses Instantly's own placeholder, and an unlisted mailbox the fixed name.
    s["signature"]["name_from_mailbox"] = True
    s["signature"]["names_by_mailbox"] = {"Dana@diabloexport.com": "Dana"}
    assert send.sender_name_for(s, "dana@diabloexport.com") == "Dana"
    assert send.sender_name_for(s, "other@diabloexport.com") == s["signature"]["name"]
    _, body = send._template("templates/template_3.json", s)
    assert "{{sendingAccountFirstName}}" in body
    p = {"properties": {"email": "p@x.example", "firstname": "P"}}
    html, _ = sync.forward_email(p, {"name": "X GmbH", "domain": "x.example"}, settings, colleague="Q",
                                 original={"eaccount": "dana@diabloexport.com", "body": {}})
    assert "Dana" in html
    html, _ = sync.reminder_email(p, {"name": "X GmbH", "domain": "x.example"}, settings,
                                  mailbox="dana@diabloexport.com")
    assert "Dana" in html


def test_info_mailbox_is_a_sending_account():
    s = load_settings()["send"]
    assert s["sending_accounts"] == ["sales@diablosnosugar.com", "info@diablosnosugar.com"]
    assert not any(a.endswith("@diablosugarfree.com") for a in s["sending_accounts"])  # never the main domain


def test_the_forward_waits_for_the_company_note_and_the_old_template_still_works(settings):
    """forward_2.json needs the Outreach company note; forward.json (kept unchanged) the personal line."""
    assert settings["send"]["templates"]["forward"] == "templates/forward_3.json"
    assert sync.forward_field(settings) == ("diablo_company_note", "Outreach company note")
    settings["send"]["templates"]["forward"] = "templates/forward.json"
    assert sync.forward_field(settings) == ("diablo_personal_line", "Outreach personal line")
    p = {"properties": {"email": "p@x.example", "firstname": "P", "diablo_personal_line": "Line."}}
    html, text = sync.forward_email(p, {"name": "X GmbH", "domain": "x.example"}, settings, colleague="Q R")
    assert "In case our earlier note to your colleague Q R" in text and "Line." in text


def test_colleagues_show_a_positive_or_negative_answer(settings):
    """S2 and S4 of the strain test (19 Oct 2026): when person 1 answers, persons 2 and 3 are not
    left at gate 2 but show the answer."""
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=0.5)
    lead(instantly, "p1@noble.in").update(lt_interest_status=1)  # Instantly's green thumbs up
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert status_of(hs, p1) == "IN_PROGRESS" and hs.records["companies"][cid][LS] == "In Progress"
    assert status_of(hs, p2) == status_of(hs, p3) == "COLLEAGUE_REPLIED_POSITIVE"

    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=0.5)
    lead(instantly, "p1@noble.in").update(lt_interest_status=-1)  # marked not interested
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["companies"][cid][LS] == "Unqualified"
    assert status_of(hs, p2) == status_of(hs, p3) == "COLLEAGUE_REPLIED_NEGATIVE"


def test_a_blocklisted_person_1_stops_the_company(settings):
    """S6 of the strain test (19 Oct 2026): blocklisting in Instantly does not mark the lead
    unsubscribed, so Sync reads the blocklist itself and nobody else is emailed."""
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    instantly.blocked = {"p1@noble.in"}
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 0 and not emails.forwards
    assert status_of(hs, p1) == "UNQUALIFIED" and hs.records["companies"][cid][LS] == "Unqualified"
    # 19 Oct 2026: the others show "Colleague opted out" and HubSpot says why, also on the timeline.
    assert status_of(hs, p2) == status_of(hs, p3) == "COLLEAGUE_OPTED_OUT"
    assert hs.records["contacts"][p1]["diablo_stop_reason"].startswith("Opted out: on Instantly's blocklist (")
    assert hs.records["contacts"][p2]["diablo_stop_reason"].startswith("A colleague opted out (")
    assert hs.records["companies"][cid]["diablo_stop_reason"].startswith("A contact opted out (")
    assert any(n[1] == p1 and "blocklist" in n[2] for n in hs.notes)
    # A whole blocklisted domain counts too, also for a colleague reached by a forward.
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    instantly.blocked = {"noble.in"}
    assert sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)["forwards_sent"] == 0


def test_the_forward_carries_the_earlier_email_underneath(settings):
    """S5 of the strain test (19 Oct 2026): the forward arrived without the earlier email."""
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    emails.emails[0]["body"] = {"html": "<div>Hi P1, the first email</div>", "text": "Hi P1, the first email"}
    emails.emails[0]["from_address_email"] = "sales@getdiablo-test.com"
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    fwd = emails.forwards[0]
    assert "---------- Forwarded message ---------" in fwd["text"] and "Hi P1, the first email" in fwd["text"]
    assert "From: sales@getdiablo-test.com" in fwd["text"] and "To: p1@noble.in" in fwd["text"]
    assert "<div>Hi P1, the first email</div>" in fwd["html"]


def test_a_reply_from_another_address_counts_for_the_person_written_to(settings):
    """Case c3 (19 Oct 2026): the reply to a forward came from the person's main address, not the
    address we wrote to; it counts for the person whose conversation it arrived in."""
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)  # forward to person 2
    reply = emails.received("p2.main@other.example", ago(0))
    reply["lead"] = "p2@noble.in"  # filed in person 2's conversation
    for e in emails.emails[:-1]:
        e["timestamp_email"] = ago(4)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["replied"] == 1 and moved["forwards_sent"] == 0
    assert status_of(hs, p2) == "IN_PROGRESS" and hs.records["companies"][cid][LS] == "In Progress"


# ---- 19 Oct 2026, second strain test: opt-outs (c5) and automatic answers (c6) ------------------

@pytest.fixture
def no_waiting(monkeypatch):
    monkeypatch.setattr(sync, "BLOCKLIST_RETRY_SECONDS", 0)


def test_the_blocklist_matches_plus_addresses_and_domains():
    blocked = sync.BlockList({"clgdbt+c5p1@gmail.com", "noble.in"})
    assert sync.is_blocked("CLGDBT+c5p1@gmail.com", blocked)
    assert sync.is_blocked("clgdbt@gmail.com", blocked)  # the same mailbox without its "+tag"
    assert sync.is_blocked("x@noble.in", blocked)  # a whole domain
    assert not sync.is_blocked("other@gmail.com", blocked)
    assert sync.is_blocked("p1+test@noble.example", {"p1@noble.example"})  # a plain set works too


def test_an_unreadable_blocklist_never_stops_the_other_emails(settings, monkeypatch, no_waiting):
    """Ariel, 19 Oct 2026: holding everything back because one list cannot be read is not wanted.
    The forward still goes; an opt-out HubSpot already holds still stops its company."""
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    def refuse():
        raise RuntimeError("401 not allowed")
    instantly.blocklist = refuse
    shown = []
    monkeypatch.setattr(sync, "step_summary", shown.append)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 1
    assert "Instantly blocklist could not be read" in shown[-1]

    hs, instantly, emails, cid2, (q1, q2, q3) = started(settings, name="Other", domain="other.in", days=3.1)
    instantly.blocklist = refuse
    hs.records["contacts"][q1]["diablo_stop_reason"] = "Opted out: on Instantly's blocklist (18 Oct 2026)"
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 0 and hs.records["companies"][cid2][LS] == "Unqualified"


def test_the_blocklist_is_checked_again_just_before_an_email(settings, monkeypatch):
    """An address blocklisted while the run is going is still caught before the forward."""
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    calls = []
    def changing():
        calls.append(1)
        return set() if len(calls) == 1 else {"p1@noble.in"}
    instantly.blocklist = changing
    monkeypatch.setattr(sync, "BLOCKLIST_FRESH_SECONDS", -1)  # always read again before an email
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert len(calls) >= 2 and moved["forwards_sent"] == 0 and not emails.forwards
    assert hs.records["companies"][cid][LS] == "Unqualified" and status_of(hs, p2) == "COLLEAGUE_OPTED_OUT"


def test_an_automatic_answer_is_no_reply(settings):
    """Case c6: an out-of-office answer does not stop the loop; person 2 still gets the forward."""
    for subject, text, interest in (("Automatic reply: Partnering to establish Diablo", "Away.", None),
                                    ("Re: Partnering to establish Diablo",
                                     "Thank you for your email. I am out of the office until 25 October.", 0),
                                    ("Abwesenheitsnotiz: Partnering", "Ich bin im Urlaub.", None)):
        hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
        lead(instantly, "p1@noble.in").update(email_reply_count=1, lt_interest_status=interest)
        emails.received("p1@noble.in", ago(1), subject=subject, text=text)
        moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
        assert status_of(hs, p1) == "ATTEMPTED_TO_CONTACT", subject
        assert moved["forwards_sent"] == 1 and moved["replied"] == 0, subject


def test_a_real_reply_still_stops_the_company(settings):
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    lead(instantly, "p1@noble.in").update(email_reply_count=1)
    emails.received("p1@noble.in", ago(1), text="Interesting, please send your price list.\n\nOn Mon, J wrote:\n"
                                              "> Unsubscribe here if you prefer")  # the quote is ignored
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert status_of(hs, p1) == "IN_PROGRESS" and moved["forwards_sent"] == 0
    assert status_of(hs, p2) == "COLLEAGUE_REPLIED"


def test_a_reply_asking_to_stop_is_an_opt_out(settings):
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    lead(instantly, "p1@noble.in").update(email_reply_count=1)
    emails.received("p1@noble.in", ago(1), text="Please remove me from your mailing list.")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 0 and status_of(hs, p1) == "UNQUALIFIED"
    assert hs.records["companies"][cid][LS] == "Unqualified" and status_of(hs, p2) == "COLLEAGUE_OPTED_OUT"
    assert hs.records["contacts"][p1]["diablo_stop_reason"].startswith("Opted out: asked in a reply")

    # The same in German, to a forward (Instantly's campaign does not count replies to forwards).
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)  # forward to person 2
    reply = emails.received("p2@noble.in", ago(0), text="Bitte keine weiteren E-Mails.")
    for e in emails.emails[:-1]:
        e["timestamp_email"] = ago(4)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 0 and status_of(hs, p2) == "UNQUALIFIED"
    assert hs.records["companies"][cid][LS] == "Unqualified" and status_of(hs, p3) == "COLLEAGUE_OPTED_OUT"


def test_without_the_new_choice_colleagues_show_negative(settings):
    """Before button 1 adds "Colleague opted out", nothing breaks: the others show the negative choice."""
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    del hs.options[("contacts", "hs_lead_status")]["COLLEAGUE_OPTED_OUT"]
    hs.missing_properties = {("contacts", "diablo_stop_reason"), ("companies", "diablo_stop_reason")}
    instantly.blocked = {"p1@noble.in"}
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 0 and status_of(hs, p2) == "COLLEAGUE_REPLIED_NEGATIVE"
    assert "diablo_stop_reason" not in hs.records["contacts"][p1]


def test_one_company_whose_emails_cannot_be_read_does_not_stop_the_others(settings):
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    other, (q1, q2, q3) = company_with_three(hs, "Other Foods", "other.in")
    send.run("test", settings, hs, instantly, log=quiet)
    lead(instantly, "p1@other.in")["timestamp_last_contact"] = ago(3.1)
    emails.campaign_email("p1@other.in", ago(3.1))
    real = emails.thread_emails
    def flaky(address):
        if address.endswith("@noble.in"):
            raise RuntimeError("GET /emails kept failing after retries")
        return real(address)
    emails.thread_emails = flaky
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 1 and emails.forwards[0]["to"] == "p2@other.in"


# ---- 20 Oct 2026, third strain test (round e) -----------------------------------------------------

def test_an_automatic_answer_labelled_interested_is_still_no_reply(settings):
    """Case e4: Instantly labelled "Automatic reply Re: ..." as Interested; the colleagues were never
    emailed. The answer itself decides, not the label."""
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    lead(instantly, "p1@noble.in").update(email_reply_count=1, lt_interest_status=1)
    emails.received("p1@noble.in", ago(1), subject="Automatic reply Re: A sugar-free brand with no Germany partner yet",
                    text="Please contact after 1 day\n\nOn Mon, Oct 19, 2026 at 5:42 PM Joshua wrote:\n> Hi")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert status_of(hs, p1) == "ATTEMPTED_TO_CONTACT" and hs.records["companies"][cid][LS] != "In Progress"
    assert moved["forwards_sent"] == 1 and emails.forwards[0]["to"] == "p2@noble.in"

    # A real answer that Instantly labelled Interested still stops the company, as before.
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.1)
    lead(instantly, "p1@noble.in").update(email_reply_count=1, lt_interest_status=1)
    emails.received("p1@noble.in", ago(1), text="Yes, please send the price list.")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert status_of(hs, p1) == "IN_PROGRESS" and status_of(hs, p2) == "COLLEAGUE_REPLIED_POSITIVE"
    assert moved["forwards_sent"] == 0


def test_a_reminder_hubspot_already_holds_is_never_sent_again(settings):
    """Case e5: HubSpot said "Reminder sent" but Instantly held no record of it. No second reminder;
    the loop ends after the usual gap."""
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=9.5)
    for pid in (p2, p3):
        hs.records["contacts"][pid][LS] = "UNQUALIFIED"
    hs.records["contacts"][p1][LS] = "REMINDER_SENT"
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["reminders_sent"] == 0 and not emails.replies
    assert moved["no_reply"] == 1 and hs.records["companies"][cid][LS] == "Contacted, but no response, unqualified"


def test_a_key_without_the_blocklist_permission_is_explained(monkeypatch, settings):
    class NoScope:
        def blocklist(self):
            raise RuntimeError('GET /block-lists-entries failed with 401: {"message":"Invalid scope. Required: '
                               'block_list_entries:read. Found: emails:all"}')
    monkeypatch.setattr(sync, "BLOCKLIST_RETRY_SECONDS", 0)
    shown = []
    blocked = sync.read_blocklist(NoScope(), log=shown.append)
    assert not blocked.ok and "INSTANTLY_BLOCKLIST_KEY" in blocked.problem and "block_list_entries:read" in blocked.problem
    assert shown[0].startswith("WARNING: Instantly's blocklist could not be read")


def test_more_words_mark_an_automatic_answer():
    """Ariel, 20 Oct 2026: a safety check with more words, in the subject or the text."""
    auto = [
        {"subject": "Re: A sugar-free brand", "body": {"text": "This is an automated response. Thank you."}},
        {"subject": "Out of Office: A sugar-free brand", "body": {"text": "Hello"}},
        {"subject": "Re: Partnering", "body": {"text": "I am on annual leave with limited access to email."}},
        {"subject": "AW: Partnering", "body": {"text": "Vielen Dank. Ich bin außer Haus und ab Montag wieder da."}},
        {"subject": "Réponse automatique : Partnering", "body": {"text": "Merci."}},
        {"subject": "Re: Partnering", "body": {"text": "Je suis absente du bureau jusqu'au 3 novembre."}},
        {"subject": "Re: Partnering", "body": {"text": "Estoy fuera de la oficina hasta el lunes."}},
        {"subject": "Re: Partnering", "body": {"text": "Sono fuori ufficio, rientro il 4."}},
        {"subject": "Automatisch antwoord: Partnering", "body": {"text": "Ik ben afwezig."}},
        {"subject": "Re: Partnering", "body": {"text": "Hi", "html": ""}, "headers": "Auto-Submitted: auto-replied"},
        {"subject": "Re: Partnering", "is_auto_reply": 1, "body": {"text": "Thanks"}},
        {"subject": "Re: Partnering", "body": {"text": "Thank you for your email. She has left the company."}},
    ]
    for e in auto:
        assert sync.is_auto_reply(e), e
    real = [
        {"subject": "Re: A sugar-free brand", "body": {"text": "Yes, please send your price list and samples."}},
        {"subject": "Re: Partnering", "body": {"text": "We are currently out of stock of sugar free lines, so yes."}},
        # A long real answer that mentions a holiday, with no return date: still a real answer.
        {"subject": "Re: Partnering", "body": {"text": "Thank you for reaching out. " * 30 +
                                                      "Our buyer is on holiday but we are interested."}},
    ]
    for e in real:
        assert not sync.is_auto_reply(e), e


def test_contacts_of_an_unqualified_company_become_unqualified_company():
    """21 Oct 2026 (Ariel): when a company is Unqualified, by a person or by the loop, its other contacts
    become "Unqualified company", kept apart from a contact's own "Unqualified"."""
    from outreach.stages import LeadStatus
    hs = FakeCRM()
    cid, (p1, p2, p3) = company_with_three(hs, "Closed Foods", "closed.in")
    hs.records["companies"][cid][LS] = "Unqualified"  # a person set the company to Unqualified
    hs.records["contacts"][p1][LS] = "UNQUALIFIED"  # p1's own reason stays
    hs.records["contacts"][p2][LS] = "REMINDER_SENT"
    other, (q1, _, _) = company_with_three(hs, "Open Foods", "open.in")
    hs.records["companies"][other][LS] = "Attempted to Contact"
    team = hs.add("contacts", email="t@closed.in", **{LS: "Emailed"})  # a person took this one over
    hs.links[team] = [cid]
    statuses = LeadStatus(hs)
    assert sync.close_company_contacts(hs, statuses, log=lambda *_: None) == 2
    assert status_of(hs, p1) == "UNQUALIFIED"
    assert status_of(hs, p2) == status_of(hs, p3) == "UNQUALIFIED_COMPANY"
    assert status_of(hs, team) == "Emailed" and status_of(hs, q1) == "APPROVED_TO_SEND"
    assert hs.records["contacts"][p2]["diablo_stop_reason"].startswith("The company is Unqualified")
    assert sync.close_company_contacts(hs, statuses, log=lambda *_: None) == 0  # nothing twice


def test_with_follow_ups_off_only_the_introduction_goes():
    """21 Oct 2026 (Ariel): no forwards and no reminder to people; a bounce passes the introduction on at
    once; no reply within no_reply_after_days ends the loop. The company inbox reminder is off too."""
    kw = dict(min_same_days=7, follow_ups=False, no_reply_days=7, inbox_reminder=False)
    four = [person("p1", 1), person("p2", 2, "approved"), person("p3", 3, "approved"), person("p4", 4, "approved")]
    fresh = [dict(p, state="approved") for p in four]
    assert decide(fresh, "approved", 3, touches={}, **kw)[1] == "next"
    assert decide(four, "in_outreach", 3, touches={"p1": days_ago(3)}, **kw) == (None, "waiting_for_reply")
    assert decide(four, "in_outreach", 3, touches={"p1": days_ago(6.9)}, **kw) == (None, "waiting_for_reply")
    assert decide(four, "in_outreach", 3, touches={"p1": days_ago(7.1)}, **kw) == (None, "no_reply")
    bounced = [dict(four[0], state="bounced")] + four[1:]
    due, why = decide(bounced, "in_outreach", 3, touches={"p1": days_ago(0.1)}, **kw)
    assert (due["id"], why) == ("p2", "next")  # at once, not after 3 days
    all_bounced = [dict(p, state="bounced") for p in four]
    assert decide(all_bounced, "in_outreach", 3, touches={}, **kw) == (None, "no_reply")
    inbox = [dict(person("i1", 1), properties={**person("i1", 1)["properties"], "jobtitle": INBOX_TITLE})]
    assert decide(inbox, "in_outreach", 3, touches={"i1": days_ago(7.1)}, **kw) == (None, "no_reply")
    due, why = decide(inbox, "in_outreach", 3, touches={"i1": days_ago(7.1)}, **{**kw, "inbox_reminder": True})
    assert (due["id"], why) == ("i1", "reminder")  # kept in the code, back when switched on


def test_with_follow_ups_off_the_company_closes_after_a_week(settings):
    settings["send"]["follow_ups_to_people"] = False
    from outreach.stages import LeadStatus
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, days=3.5)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["forwards_sent"] == 0 and moved["no_reply"] == 0 and status_of(hs, p2) == "APPROVED_TO_SEND"
    emails.emails[0]["timestamp_email"] = ago(7.2)
    lead(instantly, "p1@noble.in")["timestamp_last_contact"] = ago(7.2)
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["no_reply"] == 1 and moved["forwards_sent"] == 0 and moved["reminders_sent"] == 0
    assert hs.records["companies"][cid][LS] == "Contacted, but no response, unqualified"
    assert status_of(hs, p1) == "CONTACTED_NO_RESPONSE_UNQUALIFIED"
    assert status_of(hs, p2) == status_of(hs, p3) == "UNQUALIFIED_COMPANY"  # in the same run
    assert emails.forwards == [] and emails.replies == []
