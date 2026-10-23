"""The website check and Apollo pre-check on researched companies (agreed 14 Oct 2026)."""

import json

import requests

from outreach import import_checks as ic


class Page:
    def __init__(self, url, status=200, text="<html>Welcome to our shop</html>"):
        self.url, self.status_code, self.encoding, self._text = url, status, "utf-8", text

    def iter_content(self, size):
        yield self._text.encode()


class Web:
    """A pretend internet: {url: Page or an exception}."""

    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **_):
        page = self.pages.get(url, requests.ConnectionError("no answer"))
        if isinstance(page, Exception):
            raise page
        return page


def test_site_status_only_counts_clear_failures():
    gone = lambda domain: False
    there = lambda domain: True
    assert ic.site_status("gone.example", Web({}), gone)[0] == ic.DEAD
    assert ic.site_status("shop.example", Web({"https://shop.example": Page("https://shop.example/")}), there)[0] == ic.OK
    forsale = Web({"https://cheap.example": Page("https://cheap.example/", text="This domain is for sale! Buy now")})
    assert ic.site_status("cheap.example", forsale, there)[0] == ic.PARKED
    moved = Web({"https://old.example": Page("https://www.hugedomains.com/domain_profile.cfm?d=old.example")})
    assert ic.site_status("old.example", moved, there)[0] == ic.PARKED
    blocked = Web({"https://shy.example": Page("https://shy.example/", status=403, text="Access denied")})
    assert ic.site_status("shy.example", blocked, there)[0] == ic.UNKNOWN  # benefit of the doubt
    assert ic.site_status("quiet.example", Web({}), there)[0] == ic.UNKNOWN  # no answer at all
    http_only = Web({"https://old-tls.example": requests.exceptions.SSLError("bad cert"),
                     "http://old-tls.example": Page("http://old-tls.example/")})
    assert ic.site_status("old-tls.example", http_only, there)[0] == ic.OK


class FakeApollo:
    def __init__(self, people=None, fail=False):
        self.people, self.fail, self.calls = people or {}, fail, 0

    def search_people(self, domain, titles, seniorities=None, per_page=25):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Apollo is down")
        return self.people.get(domain, [])


def test_checker_decisions():
    web = Web({"https://good.example": Page("https://good.example/"),
               "https://empty.example": Page("https://empty.example/"),
               "https://cheap.example": Page("https://cheap.example/", text="Buy this domain")})
    apollo = FakeApollo({"good.example": [{"id": "1", "has_email": True}],
                         "empty.example": [{"id": "2", "has_email": False}]})
    checker = ic.Checker({}, apollo=apollo, session=web, resolver=lambda d: True, log=lambda _: None)
    assert checker.check("good.example", "high") == ("keep", "")
    assert checker.check("empty.example", "medium")[0] == "missing_apollo"  # 23 Oct 2026: its own status
    assert checker.check("cheap.example", "high")[0] == "missing_info"
    assert checker.check("cheap.example", "low")[0] == "drop"
    assert checker.check("", "low")[0] == "drop" and checker.check("", "high")[0] == "missing_info"
    assert apollo.calls == 2  # a site that failed is not looked up in Apollo
    down = ic.Checker({"website": False}, apollo=FakeApollo(fail=True), log=lambda _: None)
    assert down.check("good.example", "low") == ("keep", "")  # Apollo down never blocks a company


def test_import_marks_failures_missing_info_and_leaves_out_weak_ones(tmp_path, monkeypatch):
    from outreach import common, import_research, known_companies
    from outreach import research_queue as rq
    from .fakes import FakeCRM
    from .test_research_v2 import company, final_file, quiet

    monkeypatch.setattr(import_research, "ROOT", tmp_path)
    monkeypatch.setattr(rq, "QUEUE_FILE", tmp_path / "research" / "queue.csv")
    monkeypatch.setattr(common, "NOTES_FILE", tmp_path / "company_notes.json")
    monkeypatch.setattr(known_companies, "KNOWN_FILE", tmp_path / "known_companies.csv")
    rows = []
    rq.add(rows, "Mumbai, India", "distributors, retailers", wanted="2", on="2026-10-08")
    rq.save(rows)
    folder = tmp_path / "research" / "2026-10-09"
    folder.mkdir(parents=True)
    data = final_file()
    data["companies"] = [
        dict(company(), channel_category=["distributors"]),
        dict(company(name="Empty Co", domain="empty.in", rank=2), channel_category=["distributors"]),
        dict(company(name="Weak Co", domain="weak.in", rank=3, confidence="low"), channel_category=["distributors"]),
    ]
    data["channels"][0]["companies_found"] = 3
    (folder / "J0001_mumbai-india_x.json").write_text(json.dumps(data))

    class Fixed:
        def prefetch(self, domains):
            pass

        def check(self, domain, confidence, name=None):
            if domain == "alphafoods.in":
                return "keep", ""
            return ("drop" if confidence == "low" else "missing_info"), "Apollo holds nobody with an email at this website"
    hs = FakeCRM()
    lines = import_research.run("test", hs, log=quiet, checker=Fixed())
    added = {p["name"]: p["hs_lead_status"] for p in hs.records["companies"].values()}
    assert added == {"Alpha Foods": "New", "Empty Co": "Missing Info"}
    assert "1 as New, 1 as Missing Info" in lines[0] and "1 left out" in lines[0]
    assert common.load_company_notes()["empty.in"]["import_check"].startswith("Apollo holds nobody")


def test_lookalike_hosts_are_not_parking_sites_and_odd_sites_never_crash():
    assert not ic._is_parking_host("jordan.com") and not ic._is_parking_host("hefty.com")
    assert ic._is_parking_host("sedo.com") and ic._is_parking_host("www.dan.com".replace("www.", ""))
    own = Web({"https://jordan.com": Page("https://www.jordan.com/")})
    assert ic.site_status("jordan.com", own, lambda d: True)[0] == ic.OK

    weird = Page("https://odd.example/")
    weird.encoding = "utf8mb4"
    odd = Web({"https://odd.example": weird})
    assert ic.site_status("odd.example", odd, lambda d: True)[0] == ic.OK  # unknown charset: still read

    class Broken:
        def get(self, *a, **k):
            raise ValueError("something odd")
    checker = ic.Checker({"apollo": False}, session=Broken(), resolver=lambda d: True, log=lambda _: None)
    checker.prefetch(["a.example", "b.example"])
    assert checker.check("a.example", "low") == ("keep", "")


def test_temporary_dns_trouble_is_not_a_dead_website(monkeypatch):
    import socket
    def again(*a, **k):
        raise socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
    monkeypatch.setattr(socket, "getaddrinfo", again)
    assert ic._resolves("busy.example")
    def gone(*a, **k):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    monkeypatch.setattr(socket, "getaddrinfo", gone)
    assert not ic._resolves("gone.example")
