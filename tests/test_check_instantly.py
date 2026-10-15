"""Offline tests for the health check (button 4)."""

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
    assert "button 4 will not give it to new campaigns" in text and "could not be read" in text
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
    _, body = send._template("template_1.json", dict(base, booking_link="xxx"))  # the placeholder is never shown
    assert "book a time" not in body and "xxx" not in body
    _, body = send._template("templates/template_2.json", dict(base, booking_link="https://book.example/diablo"))
    assert ("you can do it from the link below.<br/>https://book.example/diablo<br/><br/>Best regards,") in body


def test_template_2_agreed_14_oct():
    from outreach import send
    base = {"privacy_url": "https://x/p", "signature": {"name": "Joshua"}, "catalogue_link": "https://c/x",
            "booking_link": "xxx"}
    _, body = send._template("templates/template_2.json", base)
    intro = body.index("By way of introduction")
    assert intro < body.index("{{personal_line}}") < body.index('Attaching a catalogue <a href="https://c/x">here</a> for your reference.')
    assert "We supply more than 126 countries" in body
    assert "UK brand" not in body and "{{market_country}}" not in body and "I'd love" not in body
    assert ("We would be more than glad to set up a call between your team and our outreach or strategy team "
            "leads, so we can") in body
    assert ("Let us know what day and time suits your team's schedule. Or if you would want to set up a call "
            "directly, you can do it from the link below.<br/>xxx<br/><br/>Best regards,") in body


def test_no_sending_while_the_booking_link_is_a_placeholder():
    from outreach import send
    settings = {"send": {"templates": {"first_email": "templates/template_2.json"}, "booking_link": "xxx"}}
    assert "booking link is missing" in send.booking_link_problem(settings)
    settings["send"]["booking_link"] = ""
    assert send.booking_link_problem(settings)
    settings["send"]["booking_link"] = "https://book.example/diablo"
    assert send.booking_link_problem(settings) == ""
    settings = {"send": {"templates": {"first_email": "templates/template_1.json"}, "booking_link": "xxx"}}
    assert send.booking_link_problem(settings) == ""  # template 1 simply leaves the sentence out


def test_footer_is_grey_small_with_clickable_links():
    from outreach import send
    base = {"privacy_url": "https://www.diablosugarfree.com/policies/privacy-policy", "signature": {"name": "Joshua", "title": "Initial Outreach Team"}}
    for name in ("template_1.json", "follow_up.json", "templates/template_2.json", "templates/forward.json"):
        _, body = send._template(name, base)
        html = send.html_paragraphs(body)
        assert "--<br/>" not in body and "<hr " in html and "font-size:12px" in html and "color:#888888" in html
        assert ('Privacy notice: <a href="https://www.diablosugarfree.com/policies/privacy-policy" '
                'style="color:#888888">https://www.diablosugarfree.com/policies/privacy-policy</a>') in html
        assert 'contact you again.<br><br>Privacy notice' in html
        text = send.render(html, {"first_name": "Ann"})
        assert "contact you again.\n\nPrivacy notice: https://www.diablosugarfree.com/policies/privacy-policy" in text
        if name != "template_1.json":
            # 14 Oct 2026: the company line moved from the footer into the signature, linked; no phone or website line
            assert "(B Healthy Ltd, London)<br>" not in html  # gone from the footer
            assert ('Joshua<br/>Initial Outreach Team<br/><a href="https://www.diablosugarfree.com">Diablo Sugar Free</a> '
                    "(B Healthy Ltd, London)</div>") in html
            assert "| Diablo Sugar Free [https://www.diablosugarfree.com] (B Healthy Ltd, London)\n" in text
            assert "www.diablosugarfree.com\n" not in text.split("Best regards,")[1].split("---")[0].replace(
                "[https://www.diablosugarfree.com]", "")


def test_template_1_is_used_and_filled():
    import json
    from outreach import send
    from outreach.common import load_settings
    from outreach.next_in_line import market_country
    s = load_settings()["send"]
    assert s["templates"]["first_email"] == "templates/template_3.json"  # Ariel's new introduction (15 Oct 2026)
    steps = send.sequence_steps(s)
    body, subject = steps[0]["variants"][0]["body"], steps[0]["variants"][0]["subject"]
    assert subject == "A sugar-free brand with no {{country_name}} partner yet"
    assert "office of the Strategy Director" in body and "as we noticed {{companyName}} {{company_note}}." in body
    assert "a direct partner in {{market_country}} yet" in body and "We supply more than 126 countries" in body
    assert '<a href="https://www.diablosugarfree.com/pages/catalogue-2026">diablosugarfree.com/pages/catalogue-2026</a>' in body
    assert 'Book a quick meeting with us: <a href="https://calendly.com/outreach-diablo/intro">calendly.com/outreach-diablo/intro</a>' in body
    assert "Joshua<br/>International Account Executive<br/>Diablo Sugar Free<br/>" in body and "<hr " in body
    assert "privacy" not in body.lower() and "{{personal_line}}" not in body
    old = json.loads(open("templates/template_2.json").read())["body"]
    assert "{{personal_line}}" in old and "Initial Outreach Team" not in old  # template 2 is kept unchanged
    current = json.loads(open("templates/template_1.json").read())["body"]
    assert "I hope this email finds you well" in current  # the current template is untouched
    assert market_country("Amsterdam, Netherlands") == "the Netherlands"
    assert market_country("Dublin, Ireland") == "Ireland"
    assert market_country("Plymouth, United Kingdom") == "the United Kingdom"
