"""Bounce notices from admin@diablosnosugar.com's label BOUNCED (agreed 20 Nov 2026, Ariel).

Instantly does not keep the "undeliverable" notice a receiving mail server sends back, so most bounces had no
reason we could read (43 contacts were labelled "not a dead address" without one). Since 20 Nov 2026 all eight
sending mailboxes (sales@ and info@diablosnosugar.com, joshua@, dana@ and elize@ on diabloexport.com and
meetdiablo.com) forward every bounce notice to admin@diablosnosugar.com, where a Gmail filter files it under the
label BOUNCED. Older notices Ariel forwards by hand ("Fwd: Undeliverable ...", from one of the eight mailboxes)
are read too.

At each run of button 4 (sync.run, before corrupt.check) this module reads those emails over IMAP with admin@'s
Google app password (the GitHub secret DAILY_REPORT_APP_PASSWORD, the same one the daily summary sends with),
read only: nothing is moved, deleted or marked as read. It returns {failed address: [notice text, ...]}; the
address is the one the notice says could not be reached, matched to an AUTO-OUTREACH contact by corrupt.check.
Nothing is saved: no address or email text is written to the repository.
"""

import datetime as dt
import email
import imaplib
import os
import re
from email import policy

LABEL = "BOUNCED"
DAYS = 150  # notices older than this are not read again
MAX_EMAILS = 1500
OUR_DOMAINS = ("diablosnosugar.com", "diabloexport.com", "meetdiablo.com", "diablosugarfree.com")
MAILBOXES = ("sales@diablosnosugar.com", "info@diablosnosugar.com", "joshua@diabloexport.com", "dana@diabloexport.com",
             "elize@diabloexport.com", "joshua@meetdiablo.com", "dana@meetdiablo.com", "elize@meetdiablo.com")
# 20 Nov 2026: no quotes inside the search (Gmail's IMAP refused the first live run with "Could not parse command");
# subject:(a b c) means every one of those words is in the subject.
SUBJECTS = ("undeliverable", "(delivery status notification)", "(undelivered mail)", "(mail delivery failed)",
            "(returned mail)", "(delivery incomplete)", "(message not delivered)", "(failure notice)")
EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
RECIPIENT_FIELDS = re.compile(r"(?:final|original)-recipient:\s*(?:rfc822;)?\s*<?([^\s;<>]+@[^\s;<>]+)>?", re.I)
NOT_A_RECIPIENT = re.compile(r"(mailer-daemon|postmaster|no-?reply|noreply|bounce|daemon)@", re.I)
SERVICE_HOSTS = ("google.com", "googlemail.com", "gmail.com", "outlook.com", "microsoft.com", "protection.outlook.com",
                 "office365.com", "zoho.com", "yahoo.com", "instantly.ai")


def gmail_query(days=DAYS):
    """The Gmail search: the BOUNCED label, or a bounce notice one of our mailboxes forwarded by hand."""
    froms = " OR ".join(MAILBOXES)
    subjects = " ".join(f"subject:{s}" for s in SUBJECTS)
    return f"newer_than:{days}d {{label:{LABEL} (from:({froms}) {{{subjects}}})}}"


def _ours(address):
    return address.lower().split("@")[-1] in OUR_DOMAINS


def _text_of(msg):
    """Everything readable in the email: subject, every text part (nested forwards and attached originals
    included) and the delivery report."""
    parts = [str(msg.get("subject") or "")]
    failed = msg.get_all("X-Failed-Recipients") or []
    parts += [f"X-Failed-Recipients: {f}" for f in failed]
    for part in msg.walk():
        kind = part.get_content_type()
        if kind in ("message/delivery-status", "text/rfc822-headers", "message/rfc822-headers"):
            payload = part.get_payload()
            if isinstance(payload, list):
                parts += [str(p) for p in payload]
            elif isinstance(payload, str):
                parts.append(payload)
            else:
                parts.append(str(part.get_payload(decode=True) or b"", "utf-8", "replace"))
        elif kind in ("text/plain", "text/html"):
            try:
                body = part.get_content()
            except Exception:  # an unknown charset: read it as it is
                body = str(part.get_payload(decode=True) or b"", "utf-8", "replace")
            if kind == "text/html":
                body = re.sub(r"<[^>]+>", " ", body)
            parts.append(body)
        elif kind == "message/rfc822":
            inner = part.get_payload()
            for m in inner if isinstance(inner, list) else [inner]:
                if hasattr(m, "get"):
                    parts.append(str(m.get("subject") or ""))
                    parts += [f"X-Failed-Recipients: {f}" for f in (m.get_all("X-Failed-Recipients") or [])]
    return "\n".join(p for p in parts if p)


def recipients_of(text):
    """The address(es) the notice says could not be reached: the delivery report's fields first, otherwise
    every address in it that is not ours, not a mail system's and not a service's own."""
    named = [a.lower() for a in RECIPIENT_FIELDS.findall(text)]
    named += [a.lower() for a in re.findall(r"X-Failed-Recipients:\s*([^\s,]+@[^\s,]+)", text)]
    named = [a.strip(".,;:<>") for a in named if not _ours(a)]
    if named:
        return sorted(set(named))
    out = set()
    for a in EMAIL.findall(text):
        a = a.lower().strip(".,;:<>")
        host = a.split("@")[-1]
        if _ours(a) or NOT_A_RECIPIENT.search(a) or any(host == h or host.endswith("." + h) for h in SERVICE_HOSTS):
            continue
        out.add(a)
    return sorted(out)


def parse(raw):
    """{address: notice text} for one email (bytes)."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    text = _text_of(msg)
    return {a: text for a in recipients_of(text)}


def read(address, password, days=DAYS, imap=None, log=print):
    """{failed address: [notice text, ...]} from admin@'s BOUNCED label (read only). {} when it cannot be read."""
    out = {}
    try:
        box = imap or imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=60)
        box.login(address, password)
        uids = []
        try:  # the label and the notices forwarded by hand, in one Gmail search
            typ, _ = box.select('"[Gmail]/All Mail"', readonly=True)
            typ, data = box.uid("SEARCH", "X-GM-RAW", f'"{gmail_query(days)}"') if typ == "OK" else ("NO", None)
            uids = (data[0] or b"").split() if typ == "OK" and data else []
            if typ != "OK":
                raise imaplib.IMAP4.error("the Gmail search was refused")
        except imaplib.IMAP4.error as err:  # then the label on its own, as an IMAP folder
            log(f"The Gmail search of admin@ was refused ({str(err)[:120]}); the BOUNCED label is read on its own")
            box.select(LABEL, readonly=True)
            since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%d-%b-%Y")
            typ, data = box.uid("SEARCH", None, "SINCE", since)
            uids = (data[0] or b"").split() if typ == "OK" and data else []
        for uid in uids[-MAX_EMAILS:]:
            typ, fetched = box.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((f[1] for f in fetched or [] if isinstance(f, tuple) and len(f) > 1), None)
            if typ != "OK" or not raw:
                continue
            for a, text in parse(raw).items():
                out.setdefault(a, []).append(text)
        try:
            box.logout()
        except Exception:
            pass
    except Exception as err:  # never stops the run; Instantly's own emails are still read
        log(f"Could not read the bounce notices in admin@'s BOUNCED label ({str(err)[:200]})")
        return {}
    log(f"Bounce notices read from the BOUNCED label: {sum(len(v) for v in out.values())} "
        f"for {len(out)} address(es)")
    return out


def read_for_run(settings=None, log=print):
    """The notices for this run of button 4, or {} when admin@'s app password is not available."""
    password = os.environ.get("DAILY_REPORT_APP_PASSWORD", "")
    sender = ((settings or {}).get("daily_report") or {}).get("sender") or "admin@diablosnosugar.com"
    if not password:
        log("The bounce notices were not read: the GitHub secret DAILY_REPORT_APP_PASSWORD is needed")
        return {}
    return read(sender, password, log=log)
