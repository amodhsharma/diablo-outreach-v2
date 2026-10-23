"""The company Lead Status "Missing info on Apollo" (Ariel, 23 Oct 2026), and a website address on
another domain whose owner the website names (McDrogerie: info@health-and-life.ch)."""

import datetime as dt
import json

import pytest

from outreach import apollo_status, common, company_inbox, find_contacts, import_research, known_companies
from outreach import research_queue as rq
from outreach.common import load_settings
from outreach.schema import STOP_REASON
from outreach.stages import LeadStatus

from .fakes import FakeApollo, FakeCRM


REAL_FIND = company_inbox.find_inbox  # taken before the test guard replaces it


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


def status(hs, cid):
    return hs.records["companies"][cid]["hs_lead_status"]


def reason(hs, cid):
    return hs.records["companies"][cid].get(STOP_REASON) or ""


def test_import_gives_apollo_nobody_its_own_status(tmp_path, monkeypatch):
    from .test_research_v2 import company, final_file
    monkeypatch.setattr(import_research, "ROOT", tmp_path)
    monkeypatch.setattr(rq, "QUEUE_FILE", tmp_path / "research" / "queue.csv")
    monkeypatch.setattr(common, "NOTES_FILE", tmp_path / "company_notes.json")
    monkeypatch.setattr(known_companies, "KNOWN_FILE", tmp_path / "known_companies.csv")
    rows = []
    rq.add(rows, "Mumbai, India", "distributors", wanted="2", on="2026-10-08")
    rq.save(rows)
    folder = tmp_path / "research" / "2026-10-09"
    folder.mkdir(parents=True)
    data = final_file()
    data["companies"] = [dict(company(), channel_category=["distributors"]),
                         dict(company(name="Empty Co", domain="empty.in", rank=2), channel_category=["distributors"]),
                         dict(company(name="Dead Co", domain="dead.in", rank=3), channel_category=["distributors"])]
    data["channels"][0]["companies_found"] = 3
    (folder / "J0001_mumbai-india_x.json").write_text(json.dumps(data))

    class Fixed:
        def prefetch(self, domains):
            pass

        def check(self, domain, confidence, name=None):
            return {"alphafoods.in": ("keep", ""),
                    "empty.in": ("missing_apollo", "Apollo holds nobody with an email at this website"),
                    "dead.in": ("missing_info", "the website does not open")}[domain]
    hs = FakeCRM()
    import_research.run("test", hs, log=quiet, checker=Fixed())
    added = {p["name"]: p for p in hs.records["companies"].values()}
    assert added["Alpha Foods"]["hs_lead_status"] == "New"
    assert added["Empty Co"]["hs_lead_status"] == "Missing info on Apollo"
    assert added["Empty Co"][STOP_REASON].startswith(apollo_status.APOLLO_NOBODY)
    assert added["Dead Co"]["hs_lead_status"] == "Missing Info"  # no working website: as before


def _gate1(hs, name="McDrogerie", domain="mcdrogerie.example", note=None):
    props = dict(name=name, domain=domain, country="Switzerland", industry_type="Retailers",
                 hs_lead_status="GATE1: Approved for outreach")
    if note:
        props[STOP_REASON] = note
    return hs.add("companies", **props)


def test_button_3_nothing_anywhere_gives_missing_info_and_remembers_it(monkeypatch):
    hs = FakeCRM()
    cid = _gate1(hs, note=apollo_status.apollo_reason(dt.date(2026, 10, 20)))
    monkeypatch.setattr(company_inbox, "find_inbox", lambda domain, **k: None)
    find_contacts.run("test", load_settings(), hs, FakeApollo({}, {}), log=quiet)
    assert status(hs, cid) == "Missing Info" and reason(hs, cid).startswith(apollo_status.NOWHERE)
    # Set to "Missing info on Apollo" again by mistake: back to "Missing Info" at the next run.
    hs.records["companies"][cid]["hs_lead_status"] = "Missing info on Apollo"
    find_contacts.run("test", load_settings(), hs, FakeApollo({}, {}), log=quiet)
    assert status(hs, cid) == "Missing Info"


def test_button_3_with_a_contact_moves_on_and_clears_the_note(monkeypatch):
    hs = FakeCRM()
    cid = _gate1(hs, note=apollo_status.apollo_reason(dt.date(2026, 10, 20)))
    monkeypatch.setattr(company_inbox, "find_inbox", lambda domain, **k: "info@mcdrogerie.example")
    find_contacts.run("test", load_settings(), hs, FakeApollo({}, {}), log=quiet)
    assert status(hs, cid) == "GATE1: Approved for outreach" and reason(hs, cid) == ""
    assert [c["email"] for c in hs.records["contacts"].values()] == ["info@mcdrogerie.example"]


def test_apollo_is_asked_again_every_two_weeks():
    hs = FakeCRM()
    statuses = LeadStatus(hs)
    today = dt.date(2026, 11, 10)

    def add(name, domain, checked):
        return hs.add("companies", name=name, domain=domain, country="Switzerland",
                      hs_lead_status="Missing info on Apollo",
                      **({STOP_REASON: apollo_status.apollo_reason(checked)} if checked else {}))
    now_known = add("Now Known", "known.example", dt.date(2026, 10, 23))
    still_empty = add("Still Empty", "empty.example", dt.date(2026, 10, 23))
    too_soon = add("Too Soon", "soon.example", dt.date(2026, 11, 1))
    by_hand = add("By Hand", "hand.example", None)  # set by a person: no date, asked straight away
    nowhere = hs.add("companies", name="Nowhere", domain="nowhere.example", hs_lead_status="Missing info on Apollo",
                     **{STOP_REASON: apollo_status.nowhere_reason(dt.date(2026, 10, 1))})
    apollo = FakeApollo({"known.example": [{"id": "1", "has_email": True}], "soon.example": [{"id": "2"}],
                         "hand.example": []}, {})
    assert apollo_status.tidy(hs, statuses, quiet) == 1
    assert status(hs, nowhere) == "Missing Info"
    result = apollo_status.recheck(hs, apollo, statuses, quiet, day=today)
    assert result == {"asked": 3, "back_to_new": 1}
    assert status(hs, now_known) == "New" and reason(hs, now_known).startswith(apollo_status.APOLLO_NOW)
    assert status(hs, still_empty) == status(hs, too_soon) == status(hs, by_hand) == "Missing info on Apollo"
    assert apollo_status.checked_on(hs.records["companies"][still_empty]) == today  # asked again today
    assert apollo_status.checked_on(hs.records["companies"][too_soon]) == dt.date(2026, 11, 1)  # not asked yet
    assert [d for d, _, _ in apollo.searches] == ["known.example", "empty.example", "hand.example"]


def test_without_the_new_choice_it_falls_back_to_missing_info():
    hs = FakeCRM()
    hs_status = LeadStatus(hs)
    hs_status._value["companies"].pop("missing_apollo")  # button 1 not run yet
    props = apollo_status.missing_apollo_props(hs, hs_status)
    assert props["hs_lead_status"] == "Missing Info" and props[STOP_REASON].startswith(apollo_status.APOLLO_NOBODY)
    assert apollo_status.recheck(hs, FakeApollo({}, {}), hs_status, quiet) == {"asked": 0, "back_to_new": 0}


class Page:
    def __init__(self, url, text, status=200):
        self.url, self.status_code, self.encoding = url, status, "utf-8"
        self._body = text.encode()

    def iter_content(self, size):
        yield self._body


class Site:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **kw):
        return Page(url, self.pages[url]) if url in self.pages else Page(url, "", 404)


def test_an_address_on_the_domain_of_the_company_named_in_the_impressum():
    """McDrogerie, 23 Oct 2026: mcdrogerie.ch shows info@health-and-life.ch, and its impressum names
    health and life AG, which runs the shop."""
    home = ('<footer>Kontakt: info@health-and-life.example <a href="/cp/impressum">Impressum</a></footer>')
    site = Site({"https://mcdrogerie.example": home,
                 "https://mcdrogerie.example/cp/impressum": "<h1>Impressum</h1><p>Betreiberin: health and life AG, "
                                                           "Waldeggstrasse 51, 3097 Liebefeld</p>"})
    found = REAL_FIND("mcdrogerie.example", session=site, mail_check=lambda d: True,
                                     name="McDrogerie")
    assert found == "info@health-and-life.example"
    # Without the impressum naming the owner, the address is still not used.
    alone = Site({"https://mcdrogerie.example": "Kontakt: info@health-and-life.example"})
    assert REAL_FIND("mcdrogerie.example", session=alone, mail_check=lambda d: True,
                                    name="McDrogerie") is None
    # Whoever built or hosts the site never counts, even with its legal form.
    agency = Site({"https://shop.example": "Webdesign: Webagence SA, hello@webagence.example"})
    assert REAL_FIND("shop.example", session=agency, mail_check=lambda d: True, name="Shop") is None
    assert company_inbox.named_on_page("cofi.example", "COFI SA, Lyon")
