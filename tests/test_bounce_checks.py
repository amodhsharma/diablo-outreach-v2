"""Bounces, agreed 20 Nov 2026 (Ariel): the reason is read from the notices forwarded to admin@'s label BOUNCED;
every bounced contact's "Outreach stopped because" starts with "Bounced:"; a domain with no mail system stops
everyone there; free checks before a first email (broken records held, a dead domain never emailed); old and
hand-added addresses at most 20 a day; our own 3% brake over the last 200 emails of the last 7 days."""

import datetime as dt

import pytest

from outreach import address_checks, bounce_inbox, corrupt, daily_report, send, sync
from outreach.schema import CONTACT_SOURCE

from .fakes import FakeCRM, FakeInstantly
from .test_corrupt import CORRUPT, LS, ORDER, REASON, bounce, company, lead, quiet, rec, started


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    from outreach import common
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


@pytest.fixture
def settings():
    from outreach.common import load_settings
    s = load_settings()
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"
    return s


GMAIL_DSN = b"""From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>
To: sales@diablosnosugar.com
Subject: Delivery Status Notification (Failure)
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="b1"

--b1
Content-Type: text/plain; charset="UTF-8"

Address not found
Your message wasn't delivered to sandesh.p@jbmetro.example because the address couldn't be found.
The response was: 550 5.1.1 The email account that you tried to reach does not exist.

--b1
Content-Type: message/delivery-status

Reporting-MTA: dns; googlemail.com

Final-Recipient: rfc822; sandesh.p@jbmetro.example
Action: failed
Status: 5.1.1

--b1--
"""

MICROSOFT_NDR = b"""From: postmaster@sevendays.example
To: info@diablosnosugar.com
Subject: Undeliverable: Partnering to establish Diablo
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<html><body><p>Your message to <b>neira.h@sevendays.example</b> couldn't be delivered.</p>
<p>Remote server returned '550 5.4.1 Recipient address rejected: Access denied.'</p></body></html>
"""

FORWARDED_BY_HAND = b"""From: Sales <sales@diablosnosugar.com>
To: admin@diablosnosugar.com
Subject: Fwd: Delivery Status Notification (Failure)
MIME-Version: 1.0
Content-Type: text/plain; charset="UTF-8"

---------- Forwarded message ---------
From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>
To: sales@diablosnosugar.com

Message not delivered
Your message wasn't delivered to purchasing@timstock.example because the domain timstock.example couldn't be found.
DNS Error: DNS type 'mx' lookup of timstock.example responded with code SERVFAIL
"""


# ---- Reading the BOUNCED label ------------------------------------------------------------------

def test_the_failed_address_and_the_reason_are_read_from_each_kind_of_notice():
    gmail = bounce_inbox.parse(GMAIL_DSN)
    assert list(gmail) == ["sandesh.p@jbmetro.example"]
    assert corrupt.classify(gmail["sandesh.p@jbmetro.example"]) == "dead"
    ms = bounce_inbox.parse(MICROSOFT_NDR)
    assert list(ms) == ["neira.h@sevendays.example"]  # the postmaster and our own mailbox are never taken
    assert corrupt.classify(ms["neira.h@sevendays.example"]) == "dead"
    fwd = bounce_inbox.parse(FORWARDED_BY_HAND)
    assert list(fwd) == ["purchasing@timstock.example"]
    assert corrupt.classify(fwd["purchasing@timstock.example"]) == "no_mail"


class FakeImap:
    """Gmail over IMAP, as admin@ sees it. Records what was asked, so the test checks it only reads."""

    def __init__(self, emails):
        self.emails, self.calls = emails, []

    def login(self, user, password):
        self.calls.append(("login", user))

    def select(self, box, readonly=False):
        self.calls.append(("select", box, readonly))
        return "OK", [b"3"]

    def uid(self, command, *args):
        self.calls.append(("uid", command) + args)
        if command == "SEARCH":
            return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.emails)))]
        return "OK", [(b"1 (BODY[] {1}", self.emails[int(args[0]) - 1]), b")"]

    def logout(self):
        self.calls.append(("logout",))


def test_the_label_is_read_only_and_bounces_are_grouped_by_address():
    imap = FakeImap([GMAIL_DSN, FORWARDED_BY_HAND, GMAIL_DSN])
    out = bounce_inbox.read("admin@diablosnosugar.com", "app-password", imap=imap, log=quiet)
    assert sorted(out) == ["purchasing@timstock.example", "sandesh.p@jbmetro.example"]
    assert len(out["sandesh.p@jbmetro.example"]) == 2  # two notices for the same address
    assert ("select", '"[Gmail]/All Mail"', True) in imap.calls  # read only
    fetches = [c for c in imap.calls if c[:2] == ("uid", "FETCH")]
    assert fetches and all(c[3] == "(BODY.PEEK[])" for c in fetches)  # never marked as read
    query = next(c for c in imap.calls if c[:2] == ("uid", "SEARCH"))[3]
    assert "label:BOUNCED" in query and "sales@diablosnosugar.com" in query
    # one quoted string with no quotes inside it (Gmail refused the first live run: "Could not parse command")
    assert query.startswith('"') and query.endswith('"') and '"' not in query[1:-1]


def test_when_the_gmail_search_is_refused_the_label_is_read_as_a_folder():
    import imaplib

    class Refuses(FakeImap):
        def uid(self, command, *args):
            if command == "SEARCH" and args[0] == "X-GM-RAW":
                raise imaplib.IMAP4.error("UID command error: BAD [b'Could not parse command']")
            return super().uid(command, *args)
    imap = Refuses([GMAIL_DSN])
    out = bounce_inbox.read("admin@diablosnosugar.com", "app-password", imap=imap, log=quiet)
    assert list(out) == ["sandesh.p@jbmetro.example"]
    assert ("select", "BOUNCED", True) in imap.calls


def test_no_password_or_an_error_means_no_notices_and_the_run_goes_on(monkeypatch):
    monkeypatch.delenv("DAILY_REPORT_APP_PASSWORD", raising=False)
    assert bounce_inbox.read_for_run({}, log=quiet) == {}

    class Broken(FakeImap):
        def login(self, user, password):
            raise OSError("authentication failed")
    assert bounce_inbox.read("admin@diablosnosugar.com", "x", imap=Broken([]), log=quiet) == {}


# ---- The reason on the contact --------------------------------------------------------------------

@pytest.fixture
def label(monkeypatch):
    """What admin@'s BOUNCED label holds for this run."""
    held = {}
    monkeypatch.setattr(bounce_inbox, "read_for_run", lambda settings=None, log=print: dict(held))
    return held


def test_a_dead_address_found_only_in_the_label_is_contact_corrupt_and_the_next_moves_up(settings, label):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "jbmetro.example", ("Owner", "Buyer"))
    rec(hs, p1)["email"] = "sandesh.p@jbmetro.example"
    lead(instantly, "p1@jbmetro.example").update(email="sandesh.p@jbmetro.example", status=-1)
    label.update(bounce_inbox.parse(GMAIL_DSN))
    for k in label:
        label[k] = [label[k]]
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)  # Instantly holds no notice at all
    assert rec(hs, p1)[LS] == CORRUPT
    assert rec(hs, p1)[REASON].startswith("Bounced: address does not exist (")
    assert "5.1.1" in rec(hs, p1)[REASON]
    assert rec(hs, p2)[ORDER] == "1"


def test_a_domain_with_no_mail_system_stops_everyone_there(settings, label):
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, "timstock.example", ("Owner", "Buyer", "Manager"))
    bounce(instantly, emails, "p1@timstock.example", text=None)
    label["p1@timstock.example"] = ["DNS Error: DNS type 'mx' lookup of timstock.example responded with code SERVFAIL"]
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == CORRUPT and rec(hs, p1)[REASON].startswith("Bounced: domain has no mail system")
    for p in (p2, p3):  # never emailed: their emails could never arrive either
        assert rec(hs, p)[LS] == CORRUPT and "domain has no mail system" in rec(hs, p)[REASON]
        assert not rec(hs, p)[REASON].startswith("Bounced:")  # they did not add to the bounce rate
    assert hs.records["companies"][cid][LS] == "Unqualified: Personal inbox bounced"


def test_instantly_finding_no_mail_system_counts_without_a_notice(settings, label):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "nomx.example", ("Owner", "Buyer"))
    bounce(instantly, emails, "p1@nomx.example", text=None)
    lead(instantly, "p1@nomx.example")["esp_code"] = 1000
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == CORRUPT and rec(hs, p1)[REASON].startswith("Bounced: domain has no mail system")


def test_an_unreadable_bounce_says_so_and_is_put_right_when_its_notice_arrives(settings, label):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "later.example", ("Owner", "Buyer"))
    bounce(instantly, emails, "p1@later.example", text=None)
    lead(instantly, "p1@later.example")["esp_code"] = 999  # Instantly knows nothing useful
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "UNQUALIFIED_BOUNCED_OTHER"
    assert rec(hs, p1)[REASON].startswith("Bounced: reason could not be read, check by hand")
    assert "not a dead address" not in rec(hs, p1)[REASON]
    label["p1@later.example"] = ["550 5.1.1 The email account that you tried to reach does not exist."]
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)  # Ariel forwarded the notice
    assert rec(hs, p1)[LS] == CORRUPT and rec(hs, p1)[REASON].startswith("Bounced: address does not exist")
    assert rec(hs, p2)[ORDER] == "1"


def test_a_temporary_bounce_stays_in_the_loop_but_is_marked_bounced(settings, label):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "busy.example", ("Owner", "Buyer"))
    bounce(instantly, emails, "p1@busy.example", text=None)
    label["p1@busy.example"] = ["451 4.3.0 Mail server temporarily unavailable, try again later"]
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "ATTEMPTED_TO_CONTACT"
    assert rec(hs, p1)[REASON].startswith("Bounced: temporary problem")


def test_a_full_inbox_and_a_policy_block_are_named(settings, label):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "fullbox.example", ("Owner", "Buyer"))
    bounce(instantly, emails, "p1@fullbox.example", text=None)
    label["p1@fullbox.example"] = ["Recipient inbox full. 552 5.2.2 The recipient's inbox is out of storage space."]
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "UNQUALIFIED_BOUNCED_OTHER" and rec(hs, p1)[REASON].startswith("Bounced: inbox full")
    assert rec(hs, p2)[ORDER] == "2"
    hs2, instantly2, emails2, cid2, (q1, q2) = started(settings, "strict.example", ("Owner", "Buyer"))
    bounce(instantly2, emails2, "p1@strict.example", text=None)
    label.clear()
    label["p1@strict.example"] = ["550 5.7.1 The organization has a policy that prohibited the mail"]
    sync.run("test", settings, hs2, instantly2, log=quiet, emails_api=emails2)
    assert rec(hs2, q1)[REASON].startswith("Bounced: blocked by their mail system")
    assert hs2.records["companies"][cid2][LS] == "Unqualified: Bounced, other reason"


def test_the_older_wordings_are_rewritten_so_one_filter_finds_every_bounce(settings, label):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "old.example", ("Owner", "Buyer"))
    rec(hs, p1).update({LS: CORRUPT, REASON: "Contact corrupt: email bounced, the address does not exist or is no longer "
                                             "used (28 Oct 2026). Bounce message: 550 5.1.1 gone"})
    rec(hs, p2).update({LS: "UNQUALIFIED_BOUNCED_OTHER", REASON: "Email bounced (3 Nov 2026): their mail system blocks "
                                                                 "our emails; the company stops. Bounce message: 5.7.1"})
    other = hs.add("contacts", email="x@old.example", **{LS: "UNQUALIFIED", REASON: "Opted out (1 Nov 2026)"})
    corrupt.rename_old(hs, log=quiet)
    assert rec(hs, p1)[REASON] == "Bounced: address does not exist (28 Oct 2026). Bounce message: 550 5.1.1 gone"
    assert rec(hs, p2)[REASON].startswith("Bounced: blocked by their mail system (3 Nov 2026)")
    assert rec(hs, other)[REASON] == "Opted out (1 Nov 2026)"  # anything else is left alone
    assert corrupt.rename_old(hs, log=quiet) == 0  # nothing left to do


# ---- Free checks before a first email ----------------------------------------------------------------

def test_a_broken_record_is_held_and_named_not_sent(settings):
    hs, instantly = FakeCRM(), FakeInstantly()
    cid, (p1,) = company(hs, "Broken Co", "broken.example", ("Owner",))
    rec(hs, p1)["firstname"] = "owner@broken.example"
    out = send.run("test", settings, hs, instantly, log=quiet)
    assert out["held"] == 1 and out["queued"] == 0 and rec(hs, p1)[LS] == "APPROVED_TO_SEND"
    assert address_checks.broken({"email": "no-at-sign", "firstname": "A"}) == "its email address is not a valid address"
    assert address_checks.broken({"email": "a@b.example", "lastname": "www.b.example"}) is not None
    assert address_checks.broken({"email": "anna.berg@b.example", "firstname": "Anna", "lastname": "Berg"}) is None


@pytest.mark.address_checks
def test_a_domain_that_cannot_take_email_is_never_emailed_and_the_next_moves_up(settings, monkeypatch):
    from outreach import company_inbox
    monkeypatch.setattr(company_inbox, "can_receive_mail", lambda d: d != "deadmx.example")
    hs, instantly = FakeCRM(), FakeInstantly()
    cid, (p1, p2) = company(hs, "Dead MX", "deadmx.example", ("Owner", "Buyer"))
    rec(hs, p2)["email"] = "buyer@alive.example"  # a working domain for the colleague
    monkeypatch.setenv("GITHUB_RUN_ID", "run1")
    out = send.run("test", settings, hs, instantly, log=quiet)
    assert out["dead_domain"] == 1 and out["queued"] == 0
    assert rec(hs, p1)[LS] == CORRUPT and "checked before sending" in rec(hs, p1)[REASON]
    assert not instantly.leads or not any(instantly.leads.values())
    assert rec(hs, p2)[ORDER] == "1"
    monkeypatch.setenv("GITHUB_RUN_ID", "run2")  # the next run: the colleague goes
    out = send.run("test", settings, hs, instantly, log=quiet)
    assert out["queued"] == 1 and rec(hs, p2)[LS] == "ATTEMPTED_TO_CONTACT"


@pytest.mark.address_checks
def test_old_and_hand_added_addresses_go_at_most_20_a_day(settings, monkeypatch):
    monkeypatch.setattr(address_checks, "domain_ok", lambda email, check=None: True)
    settings["send"]["chain"]["daily_new_companies"] = 1000
    hs, instantly = FakeCRM(), FakeInstantly()
    for i in range(25):
        company(hs, f"Old {i}", f"old{i}.example", ("Owner",))  # no Outreach contact source
    for i in range(5):
        _, (p,) = company(hs, f"Apollo {i}", f"apollo{i}.example", ("Owner",))
        rec(hs, p)[CONTACT_SOURCE] = "Apollo"
    out = send.run("test", settings, hs, instantly, log=quiet)
    sent = {l["email"] for ls in instantly.leads.values() for l in ls}
    assert sum(1 for e in sent if e.endswith(tuple(f"@old{i}.example" for i in range(25)))) == 20
    assert sum(1 for e in sent if "@apollo" in e) == 5  # Apollo's are not held back
    out = send.run("test", settings, hs, instantly, log=quiet)  # later the same day: none of the old ones
    assert out["queued"] == 0


# ---- The 3% brake --------------------------------------------------------------------------------

def _view(campaign, sent, bounced, days_ago=1.0):
    when = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()
    return {f"p{i}@x{i}.example": {"_campaign_id": campaign, "timestamp_last_contact": when,
                                   "status": -1 if i < bounced else 1} for i in range(sent)}


def test_the_brake_comes_on_at_3_percent_and_lifts_by_itself():
    cfg = address_checks.settings_of({})
    data, alerts = {}, []
    alert = lambda subject, text: alerts.append(subject)  # noqa: E731
    assert address_checks.braked(_view("c1", 100, 4), cfg, data, {"Diablo | NOV2026": "c1"}, log=quiet,
                                 alert=alert) == {"c1"}
    assert alerts == ["Partner outreach: bounce brake on"]
    assert address_checks.braked(_view("c1", 100, 4), cfg, data, {}, log=quiet, alert=alert) == {"c1"}
    assert len(alerts) == 1  # told once, not every run
    old = _view("c1", 100, 4, days_ago=8)  # a week later the bounces have dropped out
    assert address_checks.braked(old, cfg, data, {}, log=quiet, alert=alert) == set()
    assert alerts[-1] == "Partner outreach: bounce brake lifted"
    assert address_checks.braked(_view("c1", 100, 2), cfg, {}, {}, log=quiet) == set()  # 2%: under the brake
    assert address_checks.braked(_view("c1", 40, 4), cfg, {}, {}, log=quiet) == set()  # too few emails yet
    many = _view("c1", 400, 0)  # only the last 200 count
    assert address_checks.campaign_rates(many, cfg)["c1"][1] == 200


def test_no_new_introductions_go_into_a_braked_campaign(settings, monkeypatch):
    hs, instantly = FakeCRM(), FakeInstantly()
    camp = instantly.create_campaign({"name": send.campaign_name(settings["sync"]["campaign_prefix"])})["id"]
    instantly.leads[camp] = list(dict(v, email=k) for k, v in _view(camp, 100, 5).items())
    cid, (p1,) = company(hs, "Waits", "waits.example", ("Owner",))
    out = send.run("test", settings, hs, instantly, log=quiet)
    assert out["braked"] == [camp] and out["queued"] == 0 and rec(hs, p1)[LS] == "APPROVED_TO_SEND"


# ---- The daily email ------------------------------------------------------------------------------

def test_the_daily_email_names_why_each_company_bounced():
    detail = {"accounts": [("sales@diablosnosugar.com", 2, 40)],
              "companies": [("Kadac", "Australia", ["address does not exist"]), ("Timstock", "Australia", [])]}
    lines = [i[1] for i in daily_report.bounce_lines(detail, 2)]
    assert "At: Kadac (Australia: address does not exist), Timstock (Australia)" in lines
    assert daily_report._bounce_label("Bounced: inbox full (20 Nov 2026). Bounce message: x") == "inbox full"
    assert daily_report._bounce_label("Opted out (1 Nov 2026)") is None


def test_a_held_broken_record_is_named_and_counted_as_needing_input():
    from outreach.common import load_settings
    from .test_daily_report import DAY, _world
    hs, instantly, accounts, log = _world()
    co = hs.add("companies", name="Broken Co", country="Australia", hs_lead_status="GATE1: Approved for outreach")
    c = hs.add("contacts", email="x@broken.example", firstname="owner@broken.example", jobtitle="Owner",
               hs_lead_status="APPROVED_TO_SEND", diablo_personal_line="Line.")
    hs.links[c] = [co]
    text = daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, charts=False, date=DAY,
                            preview=True, log=quiet, log_data=log)["text"]
    lines = [" ".join(line.split()) for line in text.splitlines()]
    assert "Contacts held: broken record (fix it in HubSpot) 1" in lines
    assert "Broken Co (its first name holds an email or web address)" in lines
    block = lines[lines.index("Initial stages - your input needed or not (at midnight UK)") + 1:]
    assert "Contacts held: broken record 1" in block and "Introductions approved, waiting their turn to send 0" in block
