"""The company's own contact address, for companies where Apollo holds nobody (agreed 19 Oct 2026).

When Apollo has nobody with an email at a company, the pipeline looks on the company's own
website (home page, contact, Kontakt, Impressum, contacto, about pages) for a contact address and
emails that instead, greeting "Hello <company> team" and asking them to pass the email on to the
person responsible for purchasing or new brands (templates/template_no_info_apollo_1.json and
templates/follow_up_no_info_apollo_1.json).

Rules for the address:
  - only an address on the company's own domain (or a subdomain of it), or on another domain that
    clearly belongs to the same company (agreed 19 Oct 2026, after COFI: comptoir-produits-italiens.fr
    shows info@cofi.fr). Another domain counts when
      1. the website itself moves visitors to it (a redirect), or
      2. its name matches the company's name (cofi.fr for "COFI (Comptoir France-Italie)"), or
      3. the website links to it (not a "site by ..." credit or a social network) and the address is
         a purchasing, sales or general one (info@, contact@ ...).
    Addresses of web agencies, partners or anyone else are still never used;
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

# Links that never make a domain the company's own: credits for whoever built the site, and
# platforms every site links to.
CREDIT_WORDS = re.compile(r"r[ée]alis[ée]|con[cç]u|conception|d[ée]velopp[ée]|cr[ée]{1,2} par|site by|website by|"
                          r"designed by|design by|made by|built by|powered by|propuls[ée]|webdesign|web design|"
                          r"webagentur|agence|agency|erstellt|umsetzung|realizzat|creado|hosted|h[ée]berg",
                          re.I)
PLATFORMS = ("facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com", "tiktok.com",
             "pinterest.com", "google.com", "goo.gl", "apple.com", "wordpress.org", "wordpress.com", "wix.com",
             "shopify.com", "squarespace.com", "jimdo.com", "ovh.com", "ovhcloud.com", "gmail.com", "outlook.com",
             "hotmail.com", "yahoo.com", "whatsapp.com", "wa.me", "t.me", "paypal.com", "tripadvisor.com",
             "gstatic.com", "googleapis.com", "cloudflare.com", "w3.org", "schema.org", "europa.eu", "gouv.fr",
             "cnil.fr", "legifrance.gouv.fr", "trustpilot.com", "doubleclick.net", "matomo.org")
# Words in company names that say nothing about who the company is.
NAME_FILLER = {"the", "and", "und", "et", "de", "des", "du", "la", "le", "les", "di", "del", "von", "van", "der",
               "food", "foods", "group", "groupe", "company", "co", "sas", "sarl", "sa", "gmbh", "kg", "ag",
               "ltd", "limited", "plc", "srl", "spa", "bv", "nv", "inc", "llc", "distribution", "international"}

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


def _host_of(url):
    host = urlparse(url).netloc.split(":")[0].lower()
    return _bare(host)


def _same_site(host, domain):
    domain = _bare(domain)
    return bool(host) and (host == domain or host.endswith("." + domain))


def _is_platform(host):
    return any(host == p or host.endswith("." + p) for p in PLATFORMS)


def _label(domain):
    """The name part of a domain: "cofi" for cofi.fr, "alpha-foods" for www.alpha-foods.co.uk."""
    parts = _bare(domain).split(".")
    if len(parts) >= 3 and len(parts[-2]) <= 3:  # co.uk, com.au ...
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def _name_words(name, keep_all=False):
    text = html_lib.unescape(name or "").lower()
    text = re.sub(r"[àáâãäå]", "a", text)
    text = re.sub(r"[èéêë]", "e", text)
    text = re.sub(r"[ìíîï]", "i", text)
    text = re.sub(r"[òóôõö]", "o", text)
    text = re.sub(r"[ùúûü]", "u", text).replace("ç", "c").replace("ß", "ss")
    words = re.findall(r"[a-z0-9]+", text)
    return words if keep_all else [w for w in words if w not in NAME_FILLER]


def name_matches(domain, name):
    """True when the domain's name part is the company's name: one of its words (at least 3
    letters), all its words run together, or its initials."""
    words = _name_words(name)
    if not words:
        return False
    label = re.sub(r"[^a-z0-9]", "", _label(domain))
    if len(label) < 3:
        return False
    initials = "".join(w[0] for w in words)
    for joined in {"".join(words), "".join(_name_words(name, keep_all=True))}:
        if label == joined or (len(label) >= 5 and label in joined) or (len(joined) >= 5 and joined in label):
            return True
    return any(len(w) >= 3 and label == w for w in words) or (len(words) >= 2 and label == initials)


def sister_domains(page_html, base, domain):
    """Other domains the company's own pages link to, leaving out credits for whoever built the
    site and the platforms every site links to."""
    out = set()
    for m in re.finditer(r"<a\b[^>]*href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", page_html or "", flags=re.I | re.S):
        href, text = m.group(1), m.group(2)
        if href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        host = _host_of(urljoin(base, href))
        if not host or _same_site(host, domain) or _is_platform(host):
            continue
        around = (page_html[max(0, m.start() - 120):m.start()] + " " + text + " " + href)
        if CREDIT_WORDS.search(around):
            continue
        out.add(host)
    return out


def own_domain(email, domain, name=None, redirected=(), linked=()):
    """True when the address is on the company's own domain or one that clearly belongs to it
    (see the rules at the top)."""
    if on_domain(email, domain):
        return True
    host = email.rsplit("@", 1)[-1].lower()
    if _is_platform(host):
        return False
    if any(_same_site(host, d) for d in redirected):
        return True
    if name and name_matches(host, name):
        return True
    return any(_same_site(host, d) for d in linked) and rank(email) < len(PREFERRED)


def usable(email, domain, name=None, redirected=(), linked=()):
    if not own_domain(email, domain, name, redirected, linked):
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


def best(emails, domain, name=None, redirected=(), linked=()):
    """The best usable address, or None. At the same level, an address on the website's own
    domain comes before one on the company's other domain."""
    ok = [e for e in emails if usable(e, domain, name, redirected, linked)]
    return min(ok, key=lambda e: (rank(e), 0 if on_domain(e, domain) else 1, ok.index(e))) if ok else None


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


def find_inbox(domain, session=None, mail_check=None, timeout=(5, 8), name=None):
    """The company's best contact address on its own website, or None. Never raises. The address
    can be on another domain of the same company (see the rules at the top); other_domain() tells."""
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

    found, visited, redirected, linked = [], set(), set(), set()
    home, home_url = None, f"https://{domain}"
    for url in (f"https://{domain}", f"https://www.{domain}", f"http://{domain}"):
        home, home_url = get(url)
        visited.add(url)
        if home:
            break
    queue = []
    if home:
        moved = _host_of(home_url)
        if moved and not _same_site(moved, domain) and not _is_platform(moved):
            redirected.add(moved)  # the website sends visitors to the company's other domain
        found += emails_in(home)
        linked |= sister_domains(home, home_url, domain)
        queue += _links(home, home_url, domain)
        for d in redirected:
            queue += _links(home, home_url, d)
    root = home_url if home else f"https://{domain}"
    queue += [urljoin(root, p) for p in PATHS]
    for url in queue:
        if len(visited) >= MAX_PAGES + 3:
            break
        if url in visited:
            continue
        visited.add(url)
        text, page_url = get(url)
        if text:
            found += [e for e in emails_in(text) if e not in found]
            linked |= sister_domains(text, page_url, domain)
        choice = best(found, domain, name, redirected, linked)
        if choice is not None and rank(choice) == 0:
            break  # a purchasing address: nothing better to find
    choice = best(found, domain, name, redirected, linked)
    if choice is None:
        return None
    if not (mail_check or can_receive_mail)(choice.rsplit("@", 1)[-1]):
        return None
    return choice


def other_domain(email, domain):
    """The company's other domain when the address is not on the website's own domain, else None."""
    if not email or on_domain(email, domain):
        return None
    return _bare(email.rsplit("@", 1)[-1])
