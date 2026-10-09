"""Offline tests for button 6's mailbox health section."""

from outreach import check_instantly as ci

SETTINGS = {"send": {"sending_accounts": ["sales@diablosnosugar.com"]}, "sync": {"campaign_prefix": "Diablo |"}}


def acc(email, status=1, warm=1, score=100, first="Amodh", last="Sharma", limit=30, **extra):
    return {"email": email, "status": status, "warmup_status": warm, "stat_warmup_score": score,
            "first_name": first, "last_name": last, "daily_limit": limit, "setup_pending": False, **extra}


def test_verdicts():
    assert ci.mailbox_verdict(acc("a@x.com"))[0] == "Ready"
    assert ci.mailbox_verdict(acc("a@x.com", score=82))[0] == "Warming up"
    assert ci.mailbox_verdict(acc("a@x.com", score=None))[0] == "Warming up"
    verdict, reasons = ci.mailbox_verdict(acc("a@x.com", status=-1))
    assert verdict == "Problem" and "Reconnect" in reasons[0]
    assert ci.mailbox_verdict(acc("a@x.com", warm=-1))[0] == "Problem"
    assert ci.mailbox_verdict(acc("a@x.com", setup_pending=True))[0] == "Problem"
    assert ci.mailbox_verdict(acc("amir@diablosugarfree.com"))[0] == "Problem"
    verdict, reasons = ci.mailbox_verdict(acc("a@x.com", warm=0))
    assert verdict == "Ready" and "Warm-up is off" in reasons[0]


def test_section_flags_what_needs_attention():
    accounts = [acc("sales@diablosnosugar.com"),
                acc("sales@nosugardiablo.com", first="", last=""),
                acc("sales@diablosfreesugar.com", score=80),
                acc("sales@diablossugarfree.com", status=-1)]
    campaigns = [{"name": "Diablo | OCT2026", "email_list": ["sales@diablosnosugar.com", "sales@diablosfreesugar.com"]}]
    analytics = {"sales@diablosnosugar.com": {"landed_inbox": 99, "landed_spam": 1},
                 "sales@nosugardiablo.com": {"landed_inbox": 90, "landed_spam": 10}}
    text = ci.mailboxes_section(accounts, campaigns, analytics, SETTINGS, "Diablo | OCT2026")
    assert "4 mailboxes: 2 ready, 1 warming up, 1 with a problem." in text
    assert "**sales@nosugardiablo.com**: Ready but not used by this month's campaign" in text
    assert "**sales@nosugardiablo.com**: Sender name not set" in text
    assert "**sales@nosugardiablo.com**: 10 of 100 warm-up emails landed in spam (10%)" in text
    assert "**sales@diablosfreesugar.com**: Warm-up score 80: not ready" in text
    assert "**sales@diablosfreesugar.com**: Used by Diablo | OCT2026 although it is not ready" in text
    assert "**sales@diablossugarfree.com**: Connection error" in text
    assert "**sales@diablosnosugar.com**" not in text  # healthy: nothing to say
    assert "| sales@diablosnosugar.com | **Ready** | On | On | 100 | 99% inbox (99 of 100) | Amodh Sharma | 30 | Diablo | OCT2026 |" in text


def test_section_without_a_campaign_this_month_or_analytics():
    text = ci.mailboxes_section([acc("sales@nosugardiablo.com")], [], None, SETTINGS, "Diablo | NOV2026")
    assert "4b will not give it to new campaigns" in text and "could not be read" in text
    assert "No mailboxes" in ci.mailboxes_section([], [], {}, SETTINGS, "Diablo | NOV2026")
    healthy = ci.mailboxes_section([acc("sales@diablosnosugar.com")], [], {}, SETTINGS, "Diablo | NOV2026")
    assert "Nothing: every mailbox looks healthy." in healthy


class FakeApi:
    def __init__(self, fail_accounts=False):
        self.fail_accounts = fail_accounts

    def list_accounts(self):
        if self.fail_accounts:
            raise ci.InstantlyError("GET /accounts failed with 401: missing scope")
        return [acc("sales@diablosnosugar.com")]

    def warmup_analytics(self, emails):
        raise ci.InstantlyError("no analytics")


def test_mailboxes_survives_instantly_errors():
    text = ci.mailboxes(FakeApi(), [], SETTINGS)
    assert "1 mailbox: 1 ready" in text and "could not be read" in text
    assert "Could not be read" in ci.mailboxes(FakeApi(fail_accounts=True), [], SETTINGS)
