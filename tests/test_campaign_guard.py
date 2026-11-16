"""Paused campaigns and temporary bounces (agreed 16 Nov 2026, Ariel, after an Outlook outage)."""

import datetime as dt
import json

from outreach import campaign_guard, corrupt, sync
from outreach.common import load_settings

from .test_chain import settings  # noqa: F401
from .test_corrupt import LS, ago, bounce, quiet, rec, started

T0 = dt.datetime(2026, 11, 16, 6, 0, tzinfo=dt.timezone.utc)
HEALTHY = {"status": 1, "warmup_status": 1, "stat_warmup_score": 100}


class Camps:
    def __init__(self, status=-1, accounts=None):
        self.camps = [{"id": "c1", "name": "Diablo | NOV2026", "status": status,
                       "email_list": ["sales@diablosnosugar.com", "joshua@meetdiablo.com"]},
                      {"id": "x", "name": "Someone else's", "status": -1, "email_list": []}]
        self.accounts = accounts if accounts is not None else [
            dict(HEALTHY, email="sales@diablosnosugar.com"), dict(HEALTHY, email="joshua@meetdiablo.com")]
        self.activated = []

    def list_campaigns(self):
        return [dict(c) for c in self.camps]

    def list_accounts(self):
        return [dict(a) for a in self.accounts]

    def activate_campaign(self, cid):
        self.activated.append(cid)
        for c in self.camps:
            if c["id"] == cid:
                c["status"] = 1


def guard(api, at, mails, log_path):
    return campaign_guard.run(api, load_settings(), log=quiet, now=at, log_path=log_path,
                              alert=lambda subject, text: mails.append((subject, text)))


def test_a_mailbox_pause_is_resumed_after_6_hours_when_all_is_well(tmp_path):
    api, mails, log = Camps(), [], tmp_path / "log.json"
    guard(api, T0, mails, log)
    assert api.activated == [] and len(mails) == 1 and "paused in Instantly" in mails[0][0]
    assert "resumed automatically once" in mails[0][1]
    guard(api, T0 + dt.timedelta(hours=3), mails, log)  # 3 hours: still waiting, no second email
    assert api.activated == [] and len(mails) == 1
    guard(api, T0 + dt.timedelta(hours=6), mails, log)
    assert api.activated == ["c1"] and "resumed automatically" in mails[-1][0]
    guard(api, T0 + dt.timedelta(hours=9), mails, log)  # running again: nothing more
    assert len(mails) == 2


def test_never_resumed_for_bounces_a_person_or_a_suspension(tmp_path):
    for status, words in ((-2, "too many emails bounced"), (2, "someone paused it"), (-99, "suspended")):
        api, mails = Camps(status=status), []
        guard(api, T0, mails, tmp_path / "log.json")
        guard(api, T0 + dt.timedelta(hours=30), mails, tmp_path / "log.json")
        assert api.activated == [] and len(mails) == 1, status  # told once, never resumed
        assert words in mails[0][1] and "NOT resumed automatically" in mails[0][1]
        campaign_guard.FILE.unlink()


def test_an_unhealthy_mailbox_holds_it_and_says_which(tmp_path):
    sick = [dict(HEALTHY, email="sales@diablosnosugar.com"),
            {"email": "joshua@meetdiablo.com", "status": -1, "warmup_status": 1, "stat_warmup_score": 100}]
    api, mails = Camps(accounts=sick), []
    guard(api, T0, mails, tmp_path / "log.json")
    guard(api, T0 + dt.timedelta(hours=7), mails, tmp_path / "log.json")
    assert api.activated == [] and "joshua@meetdiablo.com" in mails[-1][1] and "Connection error" in mails[-1][1]
    guard(api, T0 + dt.timedelta(hours=10), mails, tmp_path / "log.json")
    assert len(mails) == 2  # the same reason is not emailed twice
    api.accounts = [dict(HEALTHY, email="sales@diablosnosugar.com"), dict(HEALTHY, email="joshua@meetdiablo.com")]
    guard(api, T0 + dt.timedelta(hours=13), mails, tmp_path / "log.json")
    assert api.activated == ["c1"]


def test_many_real_bounces_hold_it_but_temporary_ones_do_not(tmp_path):
    log = tmp_path / "log.json"
    log.write_text(json.dumps({"days": {"2026-11-16": {"bounced": [str(i) for i in range(8)]}}}))
    api, mails = Camps(), []
    guard(api, T0, mails, log)
    guard(api, T0 + dt.timedelta(hours=7), mails, log)
    assert api.activated == [] and "8 emails bounced" in mails[-1][1]
    corrupt.save_temporary({str(i): {"day": "2026-11-16", "notices": 1} for i in range(5)})
    guard(api, T0 + dt.timedelta(hours=10), mails, log)  # 3 real bounces left
    assert api.activated == ["c1"]


def test_paused_again_within_a_day_is_left_for_a_person(tmp_path):
    api, mails = Camps(), []
    guard(api, T0, mails, tmp_path / "log.json")
    guard(api, T0 + dt.timedelta(hours=6), mails, tmp_path / "log.json")
    assert api.activated == ["c1"]
    api.camps[0]["status"] = -1  # paused again
    guard(api, T0 + dt.timedelta(hours=9), mails, tmp_path / "log.json")
    guard(api, T0 + dt.timedelta(hours=20), mails, tmp_path / "log.json")
    assert api.activated == ["c1"] and "paused again" in mails[-1][0]


# ---- temporary bounces ----

def test_a_temporary_bounce_keeps_the_person_in_the_loop(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "outage.example", ("Owner", "Buyer"))
    bounce(instantly, emails, "p1@outage.example",
           text="451 4.7.500 Server busy. Please try again later. Delivery has been delayed.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "ATTEMPTED_TO_CONTACT"  # not "Bounced, other reason"
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"
    assert p1 in corrupt.temporary_ids()
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)  # stays so on the next runs
    assert rec(hs, p1)[LS] == "ATTEMPTED_TO_CONTACT"


def test_a_second_temporary_bounce_counts_as_a_bounce(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "twice.example", ("Owner", "Buyer"))
    bounce(instantly, emails, "p1@twice.example", text="421 4.4.2 Connection timed out, will be retried")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "ATTEMPTED_TO_CONTACT"
    emails.received("mailer-daemon@googlemail.com", ago(0.1), subject="Delivery Status Notification (Failure)",
                    text="451 4.3.0 Service temporarily unavailable, try again later")["lead"] = "p1@twice.example"
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "UNQUALIFIED_BOUNCED_OTHER" and p1 not in corrupt.temporary_ids()


def test_which_bounces_are_temporary():
    k = corrupt.kind_of_bounce
    assert k("451 4.7.500 Server busy. Please try again later") == "temporary"
    assert k("Delivery to the following recipient has been delayed. Service unavailable") == "temporary"
    assert k("550 5.1.1 User unknown") == "dead"
    assert k("452 4.2.2 The recipient's mailbox is full, try again later") == "other"  # as since 2 Nov 2026
    assert k("554 5.0.0 rejected, try again later") == "other"  # anything permanent is never temporary
