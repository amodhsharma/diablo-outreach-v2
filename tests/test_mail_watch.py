"""10 Nov 2026 (Ariel): button 4 reads a company's email threads in full only when something can have changed
(mail_watch.py), and always before anything is sent or closed."""

import datetime as dt
import json

import pytest

from outreach import common, mail_watch, sync

from .fakes import FakeEmails
from .test_next_in_line import ago, started, status_of  # noqa: F401


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


def _settings():
    from outreach.common import load_settings
    s = load_settings()
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"
    s["send"]["follow_ups_to_people"] = True
    s["send"]["reminder_to_company_inbox"] = True
    s["send"]["chain"]["enabled"] = False
    return s


class WatchedEmails(FakeEmails):
    """Instantly's emails, with the list of emails added since the last time it was asked."""

    def __init__(self, base=None):
        super().__init__()
        if base is not None:
            self.emails = base.emails
        self.listed = 0
        self.reads = 0
        self.broken = False

    def emails_since(self, min_created, max_pages=30):
        if self.broken:
            raise RuntimeError("Instantly did not answer")
        new, self.listed = self.emails[self.listed:], len(self.emails)
        return list(new)

    def thread_emails(self, lead_email):
        self.reads += 1
        return super().thread_emails(lead_email)


def _start(days):
    hs, instantly, emails, cid, people = started(_settings(), days=days)
    watched = WatchedEmails(emails)
    watched.listed = len(emails.emails)  # those were added long before the runs below
    return hs, instantly, watched, cid, people


def _run(hs, instantly, emails, now=None):
    return sync.advance(hs, instantly, _settings(), quiet, now=now, emails_api=emails)


def test_a_waiting_company_with_nothing_new_is_not_read_again():
    hs, instantly, emails, cid, people = _start(days=2)
    _run(hs, instantly, emails)  # first run: read in full
    first = emails.reads
    assert first >= 1
    saved = json.loads(mail_watch.FILE.read_text())
    assert saved["checked_at"] and set(saved["contacts"]) == {people[0]}
    assert "@" not in mail_watch.FILE.read_text()  # no addresses kept, only contact IDs and times
    result = _run(hs, instantly, emails)
    assert emails.reads == first  # nothing new: not read again
    assert result["forwards_sent"] == 0


def test_when_something_is_due_the_company_is_read_in_full_before_anything_is_sent():
    hs, instantly, emails, cid, (p1, p2, p3) = _start(days=2.6)
    _run(hs, instantly, emails)
    reads = emails.reads
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=12)  # 3.1 days after the introduction
    moved = _run(hs, instantly, emails, now=later)
    assert emails.reads > reads  # read in full first
    assert moved["forwards_sent"] == 1 and status_of(hs, p2) == "FORWARD_SENT"


def test_a_new_reply_gets_the_company_read_again():
    hs, instantly, emails, cid, (p1, p2, p3) = _start(days=2)
    _run(hs, instantly, emails)
    emails.received("p1@noble.in", ago(0))  # e.g. a reply Instantly's campaign counters do not show
    reads = emails.reads
    moved = _run(hs, instantly, emails)
    assert emails.reads > reads and moved["replied"] == 1
    assert hs.records["companies"][cid]["hs_lead_status"] == "In Progress"


def test_when_the_new_emails_cannot_be_listed_everything_is_read_as_before():
    hs, instantly, emails, cid, people = _start(days=2)
    _run(hs, instantly, emails)
    before = json.loads(mail_watch.FILE.read_text())["checked_at"]
    emails.broken = True
    reads = emails.reads
    _run(hs, instantly, emails)
    assert emails.reads > reads
    assert json.loads(mail_watch.FILE.read_text())["checked_at"] == before  # nothing in between is skipped


def test_a_reading_older_than_about_a_day_is_redone():
    hs, instantly, emails, cid, people = _start(days=0.5)
    _run(hs, instantly, emails)
    reads = emails.reads
    _run(hs, instantly, emails, now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=31))
    assert emails.reads > reads


def test_the_addresses_of_an_email_are_all_found():
    email = {"from_address_email": "A@x.example", "to_address_email_list": "b@y.example, C <c@z.example>",
             "cc_address_email_list": ["d@w.example"], "lead": "e@v.example"}
    assert mail_watch.addresses_of(email) == {"a@x.example", "b@y.example", "c@z.example", "d@w.example",
                                              "e@v.example"}


def test_with_the_chain_on_a_copied_line_and_the_next_introduction_are_never_skipped(monkeypatch):
    from outreach.common import load_settings
    from . import test_chain
    s = load_settings()  # the live settings: the chain is on
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"
    hs, instantly, plain, cid, (p1, p2) = test_chain.started(s, 1)
    emails = WatchedEmails(plain)
    emails.listed = len(plain.emails)

    def run(now=None, run_id="a"):
        monkeypatch.setenv("GITHUB_RUN_ID", run_id)
        return sync.advance(hs, instantly, s, quiet, now=now, emails_api=emails)

    run(run_id="1")  # person 2's line is copied over: read in full
    assert test_chain.rec(hs, p2)["hs_lead_status"] == "APPROVED_TO_SEND"
    run(run_id="2")  # read in full again (person 2 changed), then remembered while it waits
    reads = emails.reads
    assert run(run_id="3")["next_contacts_added"] == 0 and emails.reads == reads  # nothing new: skipped
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2.2)  # 3.2 days after person 1's email
    moved = run(now=later, run_id="4")
    assert emails.reads > reads and moved["next_contacts_added"] == 1
