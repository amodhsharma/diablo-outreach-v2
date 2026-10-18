"""The company's own contact address, for companies where Apollo holds nobody (agreed 19 Oct 2026).

When Apollo has nobody with an email at a company, the pipeline looks on the company's own
website (home page, contact, Kontakt, Impressum, contacto, about pages) for a contact address and
emails that instead, greeting "Hello <company> team" and asking them to pass the email on to the
person responsible for purchasing or new brands (templates/template_no_info_apollo_1.json and
templates/follow_up_no_info_apollo_1.json).

Rules for the address:
  - only an address on the company's own domain (or a subdomain of it);
  - never no-reply, privacy or data protection, jobs or careers, HR, press, webmaster or similar;
  - when there are several: purchasing first, then sales, then general (info@, office@ ...), then
    anything else;
  - the domain must be able to receive email (a mail server is listed for it), when that can be
    checked.

The address goes straight into HubSpot; it is never written to the repository.
"""

import html as html_lib
import re
from urllib.parse import unquote, urljoin, urlparse

import requests

from .import_checks import HEADERS, _read

# Pages most sites use for their contact details. The home page's own links to pages with these
# words are followed first.
LINK_WORDS = ("contact", "kontakt", "impressum", "imprint", "contacto", "contato", "contatti", "contactez",
              "nous-contacter", "about", "ueber-uns", "uber-uns", "chi-siamo", "quienes-somos", "sobre",
              "over-ons", "o-nas", "legal", "mentions-legales", "aviso-legal")
PATHS = ("/contact", "/contact-us", "/kontakt", "/impressum", "/imprint", "/contacto", "/contato",
         "/contatti", "/about", "/about-us")
MAX_PAGES = 8

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
# "name [at] firm [dot] com", "name(at)firm.com", "name at firm dot com" written to fool robots.
_AT = re.compile(r"\s*[\[\(\{]\s*(?:at|AT|@)\s*[\]\)\}]\s*")
_DOT = re.compile(r"\s*[\[\(\{]\s*(?:dot|DOT|punkt|\.)\s*[\]\)\}]\s*")

# Never used: addresses that are not for business enquiries.
EXCLUDED = ("noreply", "no-reply", "no_reply", "donotreply", "do-not-reply", "privacy", "datenschutz",
            "dsgvo", "gdpr", "rgpd", "dpo", "dataprotection", "data-protection", "jobs", "job", "career",
            "careers", "karriere", "bewerbung", "recruiting", "recruitment", "hr", "rrhh", "personal",
            "press", "presse", "prensa", "media", "pr", "webmaster", "postmaster", "abuse", "hostmaster",
            "newsletter", "unsubscribe", "support", "it", "security", "billing", "invoice", "invoices",
            "rechnung", "accounting", "buchhaltung", "complaints", "reklamation")
# Best first: purchasing, then sales, then general.
PREFERRED = (
    ("einkauf", "purchasing", "purchase", "procurement", "buying", "buyer", "buyers", "compras", "achats",
     "acquisti", "inkoop", "zakupy", "nakup", "beschaffung", "sourcing"),
    ("sales", "vertrieb", "verkauf", "ventas", "vendas", "vendite", "verkoop", "export", "commercial",
     "comercial", "business", "b2b", "wholesale", "trade", "handel", "orders", "order", "bestellung"),
    ("info", "office", "kontakt", "contact", "contacto", "contato", "hello", "hallo", "hola", "mail",
     "enquiries", "inquiries", "enquiry", "general", "zentrale", "service"),
)


def _deobfuscate(text):
    text = html_lib.unescape(text or "")
    text = unquote(text) if "%40" in text else text
    text = _AT.sub("@", text)
    return _DOT.sub(".", text)


def emails_in(text):
    """Every email address in a page, in order of appearance, lower case and without duplicates."""
    seen, out = set(), []
    for m in EMAIL.finditer(_deobfuscate(text)):
        email = m.group(0).strip(".").lower()
        if email.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):  # image names like logo@2x.png
            continue
        if email not in seen:
            seen.add(email)
            out.append(email)
    return out


def _bare(domain):
    domain = (domain or "").lower().strip()
    return domain[4:] if domain.startswith("www.") else domain


def on_domain(email, domain):
    host = email.rsplit("@", 1)[-1]
    domain = _bare(domain)
    return host == domain or host.endswith("." + domain)


def _local_words(email):
    return [w for w in re.split(r"[._+-]", email.split("@", 1)[0]) if w]


def usable(email, domain):
    if not on_domain(email, domain):
        return False
    local = email.split("@", 1)[0]
    words = _local_words(email)
    return not any(local == x or local.startswith(x + ".") or x in words for x in EXCLUDED)


def rank(email):
    """0 purchasing, 1 sales, 2 general, 3 anything else."""
    local = email.split("@", 1)[0]
    words = _local_words(email)
    for i, group in enumerate(PREFERRED):
        if any(local == x or x in words for x in group):
            return i
    return len(PREFERRED)


def best(emails, domain):
    """The best usable address, or None."""
    ok = [e for e in emails if usable(e, domain)]
    return min(ok, key=lambda e: (rank(e), ok.index(e))) if ok else None


def can_receive_mail(domain):
    """False only when DNS clearly says the domain has no mail server (needs dnspython; when it
    is not installed, or DNS cannot be asked, the address is given the benefit of the doubt)."""
    try:
        import dns.resolver  # type: ignore
    except ImportError:
        return True
    try:
        return bool(dns.resolver.resolve(_bare(domain), "MX", lifetime=8))
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        try:  # no MX record: mail then goes to the domain's own address, if it has one
            return bool(dns.resolver.resolve(_bare(domain), "A", lifetime=8))
        except Exception:
            return False
    except Exception:
        return True


def _links(page_html, base, domain):
    out = []
    for href in re.findall(r"""href\s*=\s*["']([^"'#]+)""", page_html or "", flags=re.I):
        if href.lower().startswith("mailto:"):
            continue
        url = urljoin(base, href)
        host = _bare(urlparse(url).netloc.split(":")[0])
        if host != _bare(domain) and not host.endswith("." + _bare(domain)):
            continue
        if any(w in url.lower() for w in LINK_WORDS) and url not in out:
            out.append(url)
    return out


def find_inbox(domain, session=None, mail_check=None, timeout=(5, 8)):
    """The company's best contact address on its own website, or None. Never raises."""
    domain = _bare(domain)
    if not domain:
        return None
    session = session or requests.Session()

    def get(url):
        try:
            resp = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True, stream=True)
            if resp.status_code >= 400:
                return None, url
            return _read(resp), (resp.url or url)
        except Exception:  # an odd website never stops the run
            return None, url

    found, visited = [], set()
    home, home_url = None, f"https://{domain}"
    for url in (f"https://{domain}", f"https://www.{domain}", f"http://{domain}"):
        home, home_url = get(url)
        visited.add(url)
        if home:
            break
    queue = []
    if home:
        found += emails_in(home)
        queue += _links(home, home_url, domain)
    root = home_url if home else f"https://{domain}"
    queue += [urljoin(root, p) for p in PATHS]
    for url in queue:
        if len(visited) >= MAX_PAGES + 3:
            break
        if url in visited:
            continue
        visited.add(url)
        text, _ = get(url)
        if text:
            found += [e for e in emails_in(text) if e not in found]
        choice = best(found, domain)
        if choice is not None and rank(choice) == 0:
            break  # a purchasing address: nothing better to find
    choice = best(found, domain)
    if choice is None:
        return None
    if not (mail_check or can_receive_mail)(domain):
        return None
    return choice
