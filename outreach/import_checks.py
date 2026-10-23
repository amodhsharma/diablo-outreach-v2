"""Checks on each researched company before it reaches HubSpot (agreed 14 Oct 2026).

Research is careful (sources, confidence, no invented companies) but cannot promise that a
company's website still works or that Apollo holds anyone there. A company that fails here
would only waste the team's time at gate 1, so the research import (button 2) checks:

  1. Website: the domain exists and is not a "domain for sale" or parked page. Only a CLEAR
     failure counts: a domain that no longer exists, or a for-sale/parked page. A site that is
     slow, blocks automated visitors or errors is given the benefit of the doubt.
  2. Apollo: how many people Apollo holds at that website with an email (a free search; Apollo
     only charges when an email is revealed, at "find people"). None = nobody we can email.

A company failing either check arrives as Missing Info instead of New, so nobody reviews it.
A company that also had LOW confidence in the research (a directory or shop page only) is not
added at all. Settings: import_checks in config/settings.yaml.

From 19 Oct 2026 (import_checks.company_inbox_fallback): when Apollo holds nobody but the
company's own website shows a contact address (see company_inbox.py), the company arrives as New
like any other, with the note that the website's contact address will be emailed.

From 19 Oct 2026 (after COFI): the website's address may be on another domain of the same company
(comptoir-produits-italiens.fr shows info@cofi.fr). Apollo is then also asked about that domain;
when it holds people there, the company arrives as New and button 3 searches that domain too.
"""

import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor

import requests

UNKNOWN, OK, DEAD, PARKED = "unknown", "ok", "dead", "parked"

# Sites that host "this domain is for sale" and parking pages.
PARKING_HOSTS = (
    "sedo.com", "dan.com", "afternic.com", "hugedomains.com", "bodis.com", "parkingcrew.net",
    "above.com", "undeveloped.com", "domainmarket.com", "sav.com", "parklogic.com", "uniregistry.com",
    "buydomains.com", "domainnamesales.com", "squadhelp.com", "atom.com", "brandbucket.com",
    "efty.com", "epik.com", "porkbun.com/parked",
)
PARKED_TEXT = re.compile(
    r"(this|the) domain (name )?(is|may be) for sale|buy this domain|domain (is )?for sale|"
    r"this domain (has expired|is parked|has been registered)|domain parking|parked free|"
    r"parked courtesy of|this web page is parked|the domain [\w.-]+ is for sale",
    re.I,
)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36",
           "Accept-Language": "en-GB,en;q=0.8"}


# Only these DNS answers mean "this name does not exist"; "try again later" is not proof.
_NO_SUCH_NAME = {getattr(socket, "EAI_NONAME", -2), getattr(socket, "EAI_NODATA", -5)}


def _resolves(domain):
    """False only when neither the domain nor www.domain exists."""
    for name in (domain, "www." + domain):
        try:
            socket.getaddrinfo(name, 443)
            return True
        except socket.gaierror as err:
            if err.errno not in _NO_SUCH_NAME:
                return True  # a temporary DNS problem is not proof the domain is gone
        except Exception:
            return True  # anything else (e.g. a malformed name) is not proof either
    return False


def _read(resp, limit=200_000, seconds=15):
    """The first part of a page (parking pages are short), without downloading huge or slow pages."""
    body, start = b"", time.monotonic()
    try:
        for chunk in resp.iter_content(16384):
            body += chunk or b""
            if len(body) >= limit or time.monotonic() - start > seconds:
                break
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()
    try:
        return body.decode(resp.encoding or "utf-8", "ignore")
    except LookupError:  # a site naming a character set Python does not know
        return body.decode("utf-8", "ignore")


def _is_parking_host(host):
    return any(host == p or host.endswith("." + p) for p in (x.split("/")[0] for x in PARKING_HOSTS))


def site_status(domain, session=None, resolver=None, timeout=(5, 8)):
    """(status, detail). status: ok, dead (the domain no longer exists), parked (for sale or
    parked) or unknown (could not tell; treated as fine)."""
    if not (resolver or _resolves)(domain):
        return DEAD, "the website address no longer exists"
    session = session or requests.Session()
    for url in (f"https://{domain}", f"http://{domain}"):
        try:
            resp = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True, stream=True)
            text = _read(resp)
            final = (resp.url or "").lower()
        except requests.RequestException:
            continue
        host = re.sub(r"^https?://", "", final).split("/")[0].split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        if _is_parking_host(host) and host != domain:
            return PARKED, f"the website sends visitors to {host}, a domain sales site"
        if PARKED_TEXT.search(text or ""):
            return PARKED, "the website is a 'domain for sale' or parked page"
        if resp.status_code < 400:
            return OK, ""
        return UNKNOWN, f"the website answered {resp.status_code}"
    return UNKNOWN, "the website did not answer"


def apollo_people(apollo, domain):
    """How many people Apollo holds at the domain with an email (free search), or None when
    Apollo could not be asked."""
    try:
        people = apollo.search_people(domain, [], None, per_page=25)
    except Exception:  # Apollo down or out of searches: never block the import on it
        return None
    return sum(1 for p in people if p.get("has_email", True))


APOLLO_NOBODY_REASON = "Apollo holds nobody with an email at this website"
INBOX_NOTE = ("No people in Apollo: the contact address on the company's website will be emailed "
              "(greeting the team and asking them to pass it on)")


def other_domain_note(domain, other, people):
    return (f"Nobody in Apollo at {domain}, but {people} with an email at {other}, the company's other website "
            "(its contact address uses it); button 3 searches there")


class Checker:
    """Decides, for each company, keep / missing_info / drop, with a plain reason. Never raises:
    anything unexpected counts as "could not tell" and the company is kept."""

    def __init__(self, cfg, apollo=None, session=None, resolver=None, log=print):
        cfg = cfg or {}
        self.website = cfg.get("website", True)
        self.apollo = apollo if cfg.get("apollo", True) else None
        self.max_apollo = int(cfg.get("max_apollo_checks_per_run", 300))
        self.drop_low = cfg.get("drop_low_confidence_failures", True)
        self.workers = int(cfg.get("parallel_website_checks", 16))
        self.inbox_fallback = bool(cfg.get("company_inbox_fallback", False))
        self.find_inbox = None  # set in tests; otherwise company_inbox.find_inbox
        self.session, self.resolver, self.log = session, resolver, log
        self.apollo_used = 0
        self.apollo_problem = False
        self.sites = {}
        self.counts = {"website": 0, "apollo": 0, "dropped": 0, "company_inbox": 0}

    def _site(self, domain):
        try:
            return site_status(domain, self.session, self.resolver)
        except Exception as err:  # never let one odd website stop the import
            return UNKNOWN, f"could not check ({type(err).__name__})"

    def prefetch(self, domains):
        """Check many websites at once (much faster than one by one)."""
        todo = sorted({d for d in domains if d and d not in self.sites}) if self.website else []
        if not todo:
            return
        with ThreadPoolExecutor(max_workers=max(1, self.workers)) as pool:
            for domain, result in zip(todo, pool.map(self._site, todo)):
                self.sites[domain] = result

    def _apollo(self, domain):
        if self.apollo is None:
            return None
        if self.apollo_used >= self.max_apollo:
            if self.apollo_used == self.max_apollo:
                self.log(f"Apollo pre-check: the limit of {self.max_apollo} searches for this run was reached; "
                         "the remaining companies were not checked in Apollo")
                self.apollo_used += 1
            return None
        self.apollo_used += 1
        found = apollo_people(self.apollo, domain)
        if found is None and not self.apollo_problem:
            self.apollo_problem = True
            self.log("Apollo pre-check: Apollo could not be asked (key, limit or Apollo down); those companies "
                     "were kept without the check")
        return found

    def _inbox(self, domain, name=None):
        """The website's contact address, or None."""
        try:
            if self.find_inbox is None:
                from .company_inbox import find_inbox
                self.find_inbox = find_inbox
            return self.find_inbox(domain, session=self.session, name=name) or None
        except Exception:
            return None

    def check(self, domain, confidence, name=None):
        """(decision, reason). decision: keep, missing_info, missing_apollo (23 Oct 2026: Apollo holds
        nobody and the website shows no usable address) or drop."""
        try:
            reason = ""
            if not domain:
                reason = "no website was found"
            if not reason and self.website:
                status, detail = self.sites.get(domain) or self._site(domain)
                if status in (DEAD, PARKED):
                    reason = detail
                    self.counts["website"] += 1
            if not reason and self._apollo(domain) == 0:
                email = self._inbox(domain, name) if self.inbox_fallback else None
                if email:
                    from .company_inbox import other_domain
                    other = other_domain(email, domain)
                    people = self._apollo(other) if other else None
                    if people:
                        return "keep", other_domain_note(domain, other, people)
                    self.counts["company_inbox"] += 1
                    return "keep", INBOX_NOTE
                reason = APOLLO_NOBODY_REASON
                self.counts["apollo"] += 1
        except Exception as err:
            self.log(f"Check skipped for {domain}: {type(err).__name__}")
            return "keep", ""
        if not reason:
            return "keep", ""
        if self.drop_low and str(confidence or "").lower() == "low":
            self.counts["dropped"] += 1
            return "drop", reason
        return ("missing_apollo" if reason == APOLLO_NOBODY_REASON else "missing_info"), reason
