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
            raise ci.InstantlyError("GET /accounts failed with 401: Invalid scope. Required: accounts:read")
        return [acc("sales@diablosnosugar.com")]

    def warmup_analytics(self, emails):
        raise ci.InstantlyError("no analytics")


def test_mailboxes_survives_instantly_errors():
    text = ci.mailboxes(FakeApi(), [], SETTINGS)
    assert "1 mailbox: 1 ready" in text and "could not be read" in text
    failed = ci.mailboxes(FakeApi(fail_accounts=True), [], SETTINGS)
    assert "Could not be read" in failed and "INSTANTLY_ACCOUNTS_KEY" in failed


def test_partner_type_for_the_email():
    from outreach.next_in_line import partner_type
    assert partner_type("distributors") == "distributor"
    assert partner_type("Marketplace sellers") == "online seller"
    assert partner_type("importers") == "importer"
    assert partner_type("") == "partner"


def test_market_short_for_the_subject():
    from outreach.next_in_line import market_short
    assert market_short("Dublin, Ireland") == "Dublin" and market_short("India") == "India"


def test_booking_link_only_when_set():
    from outreach import send
    base = {"privacy_url": "https://x/p", "signature": {"name": "Joshua"}}
    _, body = send._template("template_1.json", base)
    assert "{{booking_sentence}}" not in body and "book a time" not in body
    _, body = send._template("template_1.json", dict(base, booking_link="https://book.example/diablo"))
    assert "works best for you. You can also book a time directly here: https://book.example/diablo<br/>" in body
    _, body = send._template("templates/template_2.json", dict(base, booking_link="https://book.example/diablo"))
    assert "better suited? You can also book a time directly here: https://book.example/diablo<br/>" in body


def test_footer_is_grey_small_with_clickable_links():
    from outreach import send
    base = {"privacy_url": "https://www.diablosugarfree.com/policies/privacy-policy", "signature": {"name": "Joshua"}}
    for name in ("template_1.json", "follow_up.json", "templates/template_2.json"):
        _, body = send._template(name, base)
        html = send.html_paragraphs(body)
        assert "--<br/>" not in body and "<hr " in html and "font-size:12px" in html and "color:#888888" in html
        assert '<a href="https://www.diablosugarfree.com" style="color:#888888">Diablo Sugar Free</a> (B Healthy Ltd, London)<br>' in html
        assert ('Privacy notice: <a href="https://www.diablosugarfree.com/policies/privacy-policy" '
                'style="color:#888888">https://www.diablosugarfree.com/policies/privacy-policy</a>') in html
        assert 'contact you again.<br><br>Privacy notice' in html
        text = send.render(html, {"first_name": "Ann"})
        assert "Diablo Sugar Free [https://www.diablosugarfree.com] (B Healthy Ltd, London)\n" in text
        assert "contact you again.\n\nPrivacy notice: https://www.diablosugarfree.com/policies/privacy-policy" in text


def test_template_1_is_used_and_filled():
    import json
    from outreach import send
    from outreach.common import load_settings
    from outreach.next_in_line import market_country
    s = load_settings()["send"]
    assert s["templates"]["first_email"] == "templates/template_2.json"
    body = send.sequence_steps(s)[0]["variants"][0]["body"]
    assert "office of the Strategy Director" in body and "direct partner in {{market_country}}" in body
    assert "Joshua<br/>Initial Outreach Team" in body and "<hr " in body  # same sign-off and footer
    current = json.loads(open("templates/template_1.json").read())["body"]
    assert "I hope this email finds you well" in current  # the current template is untouched
    assert market_country("Amsterdam, Netherlands") == "the Netherlands"
    assert market_country("Dublin, Ireland") == "Ireland"
    assert market_country("Plymouth, United Kingdom") == "the United Kingdom"
