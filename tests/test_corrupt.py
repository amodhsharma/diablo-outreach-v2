"""Dead addresses (28 Oct 2026, Ariel): a hard bounce, or an automatic reply saying the person has left,
makes the contact "Unqualified Contact: Contact corrupt" with Outreach order 0; everyone below moves up
one; the new number 1 becomes GATE2 (now, or when its line arrives) and its introduction goes at the
next run of button 4, never the same one; with nobody left the company goes back to GATE1, or to
"Invalid inbox: Mail bounced, need input" when the dead address was its company inbox."""

import datetime as dt
import json

import pytest

from outreach import common, corrupt, find_contacts, send, sync
from outreach.common import load_settings
from outreach.schema import INBOX_TITLE

from .fakes import FakeApollo, FakeCRM, FakeEmails, FakeInstantly

LS = "hs_lead_status"
ORDER = "diablo_outreach_order"
REASON = "diablo_stop_reason"
CORRUPT = "UNQUALIFIED_CONTACT_CORRUPT"
LINE_C = ("Your range, from Swiss chocolate to Dutch biscuits, reflects a careful choice of brands for "
          "independent shops. We would welcome the chance to present our sugar free range for your "
          "consideration, should you see a place for it.")
DEAD_TEXT = "550 5.1.1 The email account that you tried to reach does not exist."


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


@pytest.fixture
def settings():
    s = load_settings()
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"
    return s


def ago(days):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()


def company(hs, name, domain, titles, line=True, status="APPROVED_TO_SEND"):
    cid = hs.add("companies", name=name, domain=domain, country="Australia", industry_type="Distributor Wholesaler",
                 **{LS: "GATE1: Approved for outreach"})
    people = []
    for rank, title in enumerate(titles, start=1):
        props = {"diablo_personal_line": "Line.", "diablo_company_note": "imports sweets"} if line else {}
        pid = hs.add("contacts", email=f"p{rank}@{domain}", firstname=f"P{rank}", lastname="L", jobtitle=title,
                     **{ORDER: str(rank), LS: status, **props})
        hs.links[pid] = [cid]
        people.append(pid)
    return cid, people


def lead(instantly, email):
    return next(l for ls in instantly.leads.values() for l in ls if l["email"] == email)


def started(settings, domain, titles, **kw):
    """Person 1's introduction went out a day ago; the others wait their turn."""
    hs, instantly, emails = FakeCRM(), FakeInstantly(), FakeEmails()
    cid, people = company(hs, domain.split(".")[0].title(), domain, titles, **kw)
    send.run("test", settings, hs, instantly, log=quiet)
    lead(instantly, f"p1@{domain}")["timestamp_last_contact"] = ago(1)
    emails.campaign_email(f"p1@{domain}", ago(1))
    return hs, instantly, emails, cid, people


def bounce(instantly, emails, address, text=DEAD_TEXT):
    lead(instantly, address).update(status=-1)
    if text is not None:
        emails._add(ue_type=2, from_address_email="mailer-daemon@googlemail.com", lead=address,
                    subject="Delivery Status Notification (Failure)", body={"text": text}, timestamp_email=ago(0.5))


def rec(hs, pid):
    return hs.records["contacts"][pid]


def test_a_dead_address_moves_everyone_up_and_the_new_number_1_goes_at_the_next_run(settings, monkeypatch):
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, "dead.example",
                                                       ("Managing Director", "Head of Buying", "Category Manager"))
    bounce(instantly, emails, "p1@dead.example")
    monkeypatch.setenv("GITHUB_RUN_ID", "run1")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == CORRUPT and rec(hs, p1)[ORDER] == "0"
    assert rec(hs, p1)[REASON].startswith("Contact corrupt: email bounced")
    assert rec(hs, p2)[ORDER] == "1" and rec(hs, p3)[ORDER] == "2"
    assert rec(hs, p2)[LS] == "APPROVED_TO_SEND"
    assert moved["contacts_corrupt"] == 1 and moved["next_contacts_added"] == 0  # not in the same run
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"  # the company is not the problem
    send.run("test", settings, hs, instantly, log=quiet)  # step 2 of the same run: still waits
    assert rec(hs, p2)[LS] == "APPROVED_TO_SEND"
    monkeypatch.setenv("GITHUB_RUN_ID", "run2")  # the next run of button 4
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["next_contacts_added"] == 1 and rec(hs, p2)[LS] == "ATTEMPTED_TO_CONTACT"
    assert rec(hs, p1)[LS] == CORRUPT and rec(hs, p3)[ORDER] == "2"  # checked once, never again


def test_the_new_number_1_without_a_line_becomes_gate_2_when_its_line_arrives(settings, monkeypatch):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "wait.example", ("Owner", "Buyer"))
    rec(hs, p2).update({LS: "NEW"})
    rec(hs, p2).pop("diablo_personal_line")
    bounce(instantly, emails, "p1@wait.example")
    monkeypatch.setenv("GITHUB_RUN_ID", "run1")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p2)[ORDER] == "1" and rec(hs, p2)[LS] == "NEW"
    assert corrupt.waiting_for_line(p2)
    rec(hs, p2).update({LS: "NEW_PERSONAL_LINE_FILLED", "diablo_personal_line": "Line."})  # the line arrives
    monkeypatch.setenv("GITHUB_RUN_ID", "run2")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p2)[LS] == "APPROVED_TO_SEND" and moved["next_contacts_added"] == 0
    monkeypatch.setenv("GITHUB_RUN_ID", "run3")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["next_contacts_added"] == 1 and rec(hs, p2)[LS] == "ATTEMPTED_TO_CONTACT"
    assert corrupt.load_promoted() == {}


def test_the_lines_import_puts_a_moved_up_contact_straight_on_gate_2(tmp_path):
    from outreach import import_lines
    check_lines = import_lines.check_lines
    hs = FakeCRM()
    cid, (p1,) = company(hs, "Lines Co", "lines.example", ("Owner",), line=False, status="NEW")
    corrupt.save_promoted({p1: {"moved_up": "28 Oct 2026"}})
    path = tmp_path / "lines.json"
    path.write_text(json.dumps({"format": check_lines.FORMAT, "run_date": "2026-10-28", "run_type": "manual",
                                "generated_from": "2026-10-28T10:00:00+00:00", "lines": [{
                                    "contact_id": p1, "company_name": "Lines Co", "personal_line": LINE_C,
                                    "company_note": "imports sweets and chocolate for shops", "style": "C"}]}))
    result = import_lines.import_file(path, hs)
    assert rec(hs, p1)[LS] == "APPROVED_TO_SEND", result
    assert "straight to 'GATE2: Approved to send'" in result


def test_nobody_left_sends_the_company_back_to_gate_1(settings):
    hs, instantly, emails, cid, (p1,) = started(settings, "solo.example", ("Director",))
    bounce(instantly, emails, "p1@solo.example")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == CORRUPT
    assert hs.records["companies"][cid][LS] == "GATE1: Approved for outreach"
    assert hs.records["companies"][cid][REASON].startswith("Back to GATE1")


def test_a_dead_company_inbox_with_nobody_left_needs_input(settings):
    hs, instantly, emails, cid, (inbox,) = started(settings, "inbox.example", (INBOX_TITLE,))
    bounce(instantly, emails, "p1@inbox.example")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, inbox)[LS] == CORRUPT and rec(hs, inbox)[ORDER] == "0"
    assert hs.records["companies"][cid][LS] == "Invalid inbox: Mail bounced, need input"
    assert hs.records["companies"][cid][REASON].startswith("Company inbox bounced")


def test_a_company_closed_earlier_because_of_a_bounce_is_put_right(settings):
    hs, instantly, emails, cid, (p1,) = started(settings, "past.example", ("Director",))
    bounce(instantly, emails, "p1@past.example")
    rec(hs, p1)[LS] = "UNQUALIFIED"  # before 28 Oct 2026: Unqualified, and the company closed as no response
    hs.records["companies"][cid][LS] = "Contacted, but no response, unqualified"
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == CORRUPT
    assert hs.records["companies"][cid][LS] == "GATE1: Approved for outreach"


def test_other_and_unreadable_bounces_stay_as_today_and_are_checked_once(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "full.example", ("Owner", "Buyer"))
    bounce(instantly, emails, "p1@full.example", text="452 4.2.2 The recipient's mailbox is full, try again later")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "UNQUALIFIED" and rec(hs, p1)[REASON].startswith("Email bounced")
    assert rec(hs, p2)[ORDER] == "2"  # nobody moved up
    hs2, instantly2, emails2, _, (q1, _) = started(settings, "blank.example", ("Owner", "Buyer"))
    bounce(instantly2, emails2, "p1@blank.example", text=None)  # no bounce message to read
    sync.run("test", settings, hs2, instantly2, log=quiet, emails_api=emails2)
    assert rec(hs2, q1)[LS] == "UNQUALIFIED" and "could not be read" in rec(hs2, q1)[REASON]


def test_an_automatic_reply_saying_they_left_is_a_dead_address_but_a_holiday_is_not(settings, monkeypatch):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "left.example", ("Owner", "Buyer"))
    lead(instantly, "p1@left.example").update(email_reply_count=1)
    emails.received("p1@left.example", ago(0.5), subject="Automatic reply: Partnering",
                    text="Thank you for your email. Pia is no longer with the company. Please write to info@.")
    monkeypatch.setenv("GITHUB_RUN_ID", "run1")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == CORRUPT and "have left" in rec(hs, p1)[REASON]
    assert rec(hs, p2)[ORDER] == "1"
    hs2, instantly2, emails2, _, (q1, q2) = started(settings, "away.example", ("Owner", "Buyer"))
    lead(instantly2, "p1@away.example").update(email_reply_count=1)
    emails2.received("p1@away.example", ago(0.5), subject="Out of office",
                     text="I am out of the office until Monday and will reply when I am back.")
    sync.run("test", settings, hs2, instantly2, log=quiet, emails_api=emails2)
    assert rec(hs2, q1)[LS] == "ATTEMPTED_TO_CONTACT" and rec(hs2, q2)[ORDER] == "2"


def test_the_bounce_reading_rules():
    assert corrupt.kind_of_bounce(DEAD_TEXT) == "dead"
    assert corrupt.kind_of_bounce("550 Recipient address rejected: mailbox no longer in use") == "dead"
    assert corrupt.kind_of_bounce("Empfänger unbekannt") == "dead"
    assert corrupt.kind_of_bounce("Mailbox full, quota exceeded") == "other"
    assert corrupt.kind_of_bounce("") == "unreadable"


def test_button_3_leaves_dead_addresses_out_and_never_adds_them_again():
    hs = FakeCRM()
    cid = hs.add("companies", name="Delta Foods", domain="delta.example", country="Switzerland",
                 industry_type="Distributors", hs_lead_status="GATE1: Approved for outreach")
    dead = hs.add("contacts", email="dead@delta.example", jobtitle="Owner", diablo_outreach_order="0",
                  hs_lead_status=CORRUPT)
    hs.links[dead] = [cid]
    apollo = FakeApollo({"delta.example": [{"id": "d0", "title": "Owner", "has_email": True},
                                           {"id": "d1", "title": "Purchasing Manager", "has_email": True}]},
                        {"d0": ("dead@delta.example", "verified"), "d1": ("new@delta.example", "verified")})
    summary = find_contacts.run("test", load_settings(), hs, apollo, log=quiet)
    emails = sorted(r["email"] for r in hs.records["contacts"].values())
    assert emails == ["dead@delta.example", "new@delta.example"]  # the dead address is not added twice
    new = next(r for r in hs.records["contacts"].values() if r["email"] == "new@delta.example")
    assert new["diablo_outreach_order"] == "1"
    assert hs.records["companies"][cid]["hs_lead_status"] == "GATE1: Approved for outreach"
    assert "6. Invalid inbox" in find_contacts.hubspot_filters("Amodh Sharma")
    assert summary["gate1"]
