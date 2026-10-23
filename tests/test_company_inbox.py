"""Company inboxes (agreed 19 Oct 2026): when Apollo holds nobody, the contact address on the
company's own website is emailed instead, from its own monthly campaign, greeting the team."""

import json

import pytest

from outreach import common, company_inbox, find_contacts, import_checks as ic, send, sync
from outreach.common import load_settings
from outreach.schema import INBOX_TITLE

from .fakes import FakeApollo, FakeCRM, FakeEmails, FakeInstantly


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


class Page:
    def __init__(self, url, text, status=200):
        self.url, self.status_code, self.encoding = url, status, "utf-8"
        self._body = text.encode()

    def iter_content(self, size):
        yield self._body


class Site:
    """A fake website: {url: html}. Anything else is a 404."""

    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def get(self, url, **kw):
        self.asked.append(url)
        return Page(url, self.pages[url]) if url in self.pages else Page(url, "", 404)


REAL_FIND = company_inbox.find_inbox  # taken before the test guard replaces it


def test_finding_the_best_address_on_the_website():
    site = Site({
        "https://alpha.example": '<a href="/de/kontakt">Kontakt</a> <a href="mailto:jobs@alpha.example">Jobs</a>',
        "https://alpha.example/de/kontakt": "Schreiben Sie an info@alpha.example oder einkauf [at] alpha [dot] example."
                                            " Datenschutz: datenschutz@alpha.example. Partner: x@other.example",
    })
    assert REAL_FIND("alpha.example", session=site, mail_check=lambda d: True) == "einkauf@alpha.example"
    assert "https://alpha.example/de/kontakt" in site.asked  # followed the home page's Kontakt link
    assert company_inbox.emails_in("a&#64;b.example and c (at) d (dot) example") == ["a@b.example", "c@d.example"]
    assert company_inbox.best(["press@a.example", "privacy@a.example", "sales@a.example", "info@a.example"],
                              "a.example") == "sales@a.example"
    assert company_inbox.best(["info@other.example"], "a.example") is None  # never another domain
    assert company_inbox.best(["jobs@a.example", "noreply@a.example"], "a.example") is None
    assert company_inbox.emails_in("logo@2x.png") == []
    assert REAL_FIND("alpha.example", session=site, mail_check=lambda d: False) is None  # no mail server
    assert REAL_FIND("empty.example", session=Site({}), mail_check=lambda d: True) is None


def test_an_address_on_the_companys_other_domain_is_used():
    """COFI, 19 Oct 2026: comptoir-produits-italiens.fr shows info@cofi.fr."""
    site = Site({
        "https://comptoir.example": '<a href="/contact">Contact</a> Site réalisé par <a href="https://webagence.example">'
                                    'Web Agence</a>',
        "https://comptoir.example/contact": "Écrivez-nous : info@cofi.example. Webmaster : hello@webagence.example",
    })
    assert REAL_FIND("comptoir.example", session=site, mail_check=lambda d: True,
                     name="COFI (Comptoir France-Italie)") == "info@cofi.example"  # the name matches
    assert REAL_FIND("comptoir.example", session=site, mail_check=lambda d: True, name="Comptoir Lyon") is None
    assert company_inbox.other_domain("info@cofi.example", "comptoir.example") == "cofi.example"
    assert company_inbox.other_domain("info@comptoir.example", "www.comptoir.example") is None
    # The website links to its other domain (not a credit): a general address there is used.
    linked = Site({
        "https://shop.example": '<a href="https://www.groupe-north.example/">Notre groupe</a>'
                                ' Contact: contact@groupe-north.example, anna.b@groupe-north.example',
    })
    assert REAL_FIND("shop.example", session=linked, mail_check=lambda d: True, name="Shop") == "contact@groupe-north.example"
    # Never: an agency credited for the site, a social network, a free mailbox or an unlinked domain.
    credit = Site({"https://a.example": 'Site by <a href="https://maker.example">Maker</a> info@maker.example'
                                        ' <a href="https://facebook.com/a">fb</a> a.shop@gmail.com info@stranger.example'})
    assert REAL_FIND("a.example", session=credit, mail_check=lambda d: True, name="Alpha") is None
    assert company_inbox.name_matches("alphafoods.example", "Alpha Foods GmbH")
    assert company_inbox.name_matches("saveuraldente.example", "Al Dente")
    assert not company_inbox.name_matches("food.example", "Alpha Foods")


def test_apollo_is_asked_about_the_other_domain(monkeypatch):
    class Some:
        def search_people(self, domain, *a, **k):
            return [{"has_email": True}] * 3 if domain == "cofi.example" else []
    checker = ic.Checker({"website": False, "company_inbox_fallback": True}, apollo=Some(), log=quiet)
    checker.find_inbox = lambda domain, **k: "info@cofi.example" if k.get("name", "").startswith("COFI") else None
    decision, reason = checker.check("comptoir.example", "high", "COFI (Comptoir France-Italie)")
    assert decision == "keep" and "3 with an email at cofi.example" in reason
    # Button 3 then searches cofi.example and adds the people there, not the inbox.
    hs = FakeCRM()
    hs.add("companies", name="COFI (Comptoir France-Italie)", domain="comptoir.example", country="France",
           industry_type="Distributor Wholesaler", hs_lead_status="GATE1: Approved for outreach")
    monkeypatch.setattr(company_inbox, "find_inbox", lambda domain, **k: "info@cofi.example")
    apollo = FakeApollo({"cofi.example": [{"id": "p1", "title": "Purchasing Manager", "seniority": "manager",
                                            "first_name": "A", "last_name": "B"}]},
                        {"p1": ("a.b@cofi.example", "verified")})
    summary = find_contacts.run("test", _settings(), hs, apollo, log=quiet)
    row = summary["rows"][0]
    assert row["other_domain"] == "cofi.example" and row["result"] == "contacts found"
    assert [c["email"] for c in hs.records["contacts"].values()] == ["a.b@cofi.example"]


def test_import_keeps_a_company_with_a_website_inbox_as_new():
    class NoOne:
        def search_people(self, *a, **k):
            return []
    checker = ic.Checker({"website": False, "company_inbox_fallback": True}, apollo=NoOne(), log=quiet)
    checker.find_inbox = lambda domain, **k: "info@alpha.example" if domain == "alpha.example" else None
    decision, reason = checker.check("alpha.example", "high")
    assert decision == "keep" and "contact address on the company's website" in reason
    assert checker.check("beta.example", "high") == ("missing_apollo", "Apollo holds nobody with an email at this website")
    off = ic.Checker({"website": False}, apollo=NoOne(), log=quiet)  # switched off: Missing Info as before
    off.find_inbox = lambda domain, **k: "info@alpha.example"
    assert off.check("alpha.example", "high")[0] == "missing_apollo"  # 23 Oct 2026: its own status


def _settings():
    s = load_settings()
    s["send"]["sending_accounts"] = ["one@getdiablo-test.com", "two@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"
    return s


def test_button_3_adds_the_website_inbox_when_apollo_has_nobody(monkeypatch):
    hs = FakeCRM()
    cid = hs.add("companies", name="Alpha Foods GmbH", domain="alpha.example", country="Germany",
                 industry_type="Distributor Wholesaler", hs_lead_status="GATE1: Approved for outreach")
    monkeypatch.setattr(company_inbox, "find_inbox", lambda domain, **k: "info@alpha.example")
    summary = find_contacts.run("test", _settings(), hs, FakeApollo({}, {}), log=quiet)
    contacts = list(hs.records["contacts"].values())
    assert len(contacts) == 1
    c = contacts[0]
    assert c["email"] == "info@alpha.example" and c["jobtitle"] == INBOX_TITLE and c["firstname"] == ""
    assert c["diablo_outreach_order"] == "1" and c["hs_lead_status"] == "NEW" and c["lead_source"] == "AUTO-OUTREACH"
    assert c["diablo_contact_source"] == "Company website"
    assert hs.records["companies"][cid]["hs_lead_status"] != "Missing Info"
    assert summary["rows"][0]["result"] == "company inbox added"
    # The new contact is handed to step 3 (mail writing) like any other.
    assert json.loads(find_contacts.new_contacts_file().read_text())["contact_ids"] == [summary["rows"][0]["contact_ids"][0]]


def test_button_3_without_the_new_field_and_without_any_inbox(monkeypatch):
    hs = FakeCRM()
    hs.missing_properties = {("contacts", "diablo_contact_source")}  # button 1 not run again yet
    cid = hs.add("companies", name="Alpha Foods", domain="alpha.example", country="Germany",
                 industry_type="Distributor Wholesaler", hs_lead_status="GATE1: Approved for outreach")
    monkeypatch.setattr(company_inbox, "find_inbox", lambda domain, **k: "info@alpha.example")
    find_contacts.run("test", _settings(), hs, FakeApollo({}, {}), log=quiet)
    c = next(iter(hs.records["contacts"].values()))
    assert "diablo_contact_source" not in c and c["jobtitle"] == INBOX_TITLE  # still recognised by the title
    hs2 = FakeCRM()
    cid2 = hs2.add("companies", name="Beta", domain="beta.example", country="Germany",
                   industry_type="Distributor Wholesaler", hs_lead_status="GATE1: Approved for outreach")
    monkeypatch.setattr(company_inbox, "find_inbox", lambda domain, **k: None)
    find_contacts.run("test", _settings(), hs2, FakeApollo({}, {}), log=quiet)
    assert not hs2.records["contacts"] and hs2.records["companies"][cid2]["hs_lead_status"] == "Missing Info"


def _approved_inbox(hs, name="Alpha Foods GmbH", domain="alpha.example"):
    cid = hs.add("companies", name=name, domain=domain, country="Germany", industry_type="Distributor Wholesaler",
                 hs_lead_status="GATE1: Approved for outreach")
    pid = hs.add("contacts", email=f"info@{domain}", firstname="", jobtitle=INBOX_TITLE, diablo_outreach_order="1",
                 diablo_personal_line="Line.", diablo_company_note="imports European sweets",
                 hs_lead_status="APPROVED_TO_SEND")
    hs.links[pid] = [cid]
    return cid, pid


def test_company_inboxes_get_their_own_campaign_greeting_and_cap():
    hs, instantly = FakeCRM(), FakeInstantly()
    _approved_inbox(hs)
    person = hs.add("companies", name="Beta Foods", domain="beta.example", country="Germany",
                    industry_type="Distributor Wholesaler", hs_lead_status="GATE1: Approved for outreach")
    pid = hs.add("contacts", email="anna@beta.example", firstname="Anna", jobtitle="Purchasing Manager",
                 diablo_outreach_order="1", diablo_personal_line="Line.", diablo_company_note="imports sweets",
                 hs_lead_status="APPROVED_TO_SEND")
    hs.links[pid] = [person]
    s = _settings()
    send.run("test", s, hs, instantly, log=quiet)
    camps = {b["name"]: dict(b, id=cid) for cid, b in instantly.campaigns.items()}
    main, inbox = send.campaign_name("Diablo |"), send.inbox_campaign_name("Diablo |", s["send"])
    assert inbox == main + " | Company inboxes" and set(camps) == {main, inbox}
    assert [l["email"] for l in instantly.leads[camps[inbox]["id"]]] == ["info@alpha.example"]
    assert [l["email"] for l in instantly.leads[camps[main]["id"]]] == ["anna@beta.example"]
    assert camps[inbox]["daily_limit"] == 10 and camps[main]["daily_limit"] == s["send"]["daily_limit"]
    inbox_body = camps[inbox]["sequences"][0]["steps"][0]["variants"][0]["body"]
    main_body = camps[main]["sequences"][0]["steps"][0]["variants"][0]["body"]
    assert "</div>Hello to the team at {{companyName}},</div>" in inbox_body and "pass this on to the person responsible" in inbox_body
    assert "</div>Hi {{full_name}},</div>" in main_body and "pass this on" not in main_body
    # Keeping the campaigns up to date never gives the inbox campaign the people's email, or the reverse.
    assert send.refresh_campaign_content(instantly, s, log=quiet) == 0
    lead = instantly.leads[camps[inbox]["id"]][0]
    text = send.render(inbox_body, lead)
    assert text.startswith("Hello to the team at Alpha Foods,")  # the short name, without "GmbH"


def test_company_inbox_reminder_uses_its_own_template():
    s = _settings()
    inbox = {"properties": {"email": "info@alpha.example", "firstname": "", "jobtitle": INBOX_TITLE,
                            "diablo_company_note": "imports sweets"}}
    person = {"properties": {"email": "anna@beta.example", "firstname": "Anna", "jobtitle": "Buyer"}}
    company = {"name": "Alpha Foods GmbH", "domain": "alpha.example", "country": "Germany"}
    assert sync.reminder_path(s, inbox) == "templates/follow_up_no_info_apollo_3.json"
    assert sync.reminder_path(s, person) == "templates/follow_up_3.json"
    assert sync.reminder_subject(s, inbox) == "Bad Jokes + Europe's largest Brand"
    html, text = sync.reminder_email(inbox, company, s)
    assert text.startswith("Hello to the team at Alpha Foods,")
    assert "If this is better suited to a colleague, could you kindly pass it on" in text
    html, text = sync.reminder_email(person, company, s)
    assert text.startswith("Hi Anna,") and "pass it on" not in text  # no last name: just the first name
