"""Button 4 reads only the email threads that can have changed (agreed 10 Nov 2026, Ariel).

Until now every run read the whole email history of everyone at every company in its loop, one person at a
time, and Instantly lets that list be read only 20 times a minute: 263 people took 22 minutes on 31 Oct
2026, 620 people 66 minutes on 6 Nov, and the time kept growing with every person emailed.

Now each run first asks Instantly once for every email created since the last run (an hour of overlap),
sent or received, and notes the addresses in them. A company is read again in full only when:
  - one of its people is in those emails (a reply, an out-of-office answer, a bounce notice, an email we sent);
  - one of its people changed in Instantly's lead list or in HubSpot (for example queued to sent, bounced);
  - the company's last full read is older than about a day (between 18 and 30 hours, spread by company,
    so the companies are not all read in the same run);
  - Instantly's list of new emails could not be read (then every company is read, as before).
Otherwise the times each person was emailed are taken from the last full read, and the company is only
checked for what is due. Whenever anything would happen to it (a forward, a reminder, an introduction,
"no response", a line copied, an opt-out), it is read in full first, exactly as before, so nothing is
ever sent or closed on an old reading.

data/mail_watch.json holds only HubSpot contact IDs, their state and the times they were emailed: no
names, addresses or email text.
"""

import datetime as dt
import json

from .common import ROOT
from .next_in_line import parse_time

FILE = ROOT / "data" / "mail_watch.json"
OVERLAP = dt.timedelta(hours=1)
MIN_AGE_HOURS, SPREAD_HOURS = 18, 12  # a company's last full read is trusted for 18 to 30 hours
KEEP = dt.timedelta(days=3)  # entries not used for this long are dropped
MAX_PAGES = 30  # more new emails than this (3,000) in one go: every company is read in full instead
ACTIVE = ("queued", "sent", "bounced")
# What decide() says when nothing happens to a company in this run.
QUIET = ("waiting", "waiting_same_person", "waiting_for_gate_2", "nothing", "stopped", "waiting_for_reply")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(when):
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path=None):
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("checked_at", None)
    if not isinstance(data.get("contacts"), dict):
        data["contacts"] = {}
    return data


def addresses_of(email):
    """Every address an email from Instantly's list names (from, to, cc, bcc and its lead)."""
    out = set()
    for key in ("from_address_email", "to_address_email_list", "cc_address_email_list", "bcc_address_email_list",
                "lead", "reply_to"):
        value = email.get(key)
        values = value if isinstance(value, (list, tuple)) else str(value or "").replace(";", ",").split(",")
        for v in values:
            v = str(v or "").strip().lower()
            if "<" in v and ">" in v:
                v = v[v.index("<") + 1:v.index(">")]
            if "@" in v:
                out.add(v)
    return out


class Watch:
    """One run's view of what may have changed. emails_api needs emails_since(iso time, max_pages)."""

    def __init__(self, emails_api, log=print, now=None, path=None):
        self.path, self.log = path, log
        self.now = now or _now()
        self.data = load(path)
        self.recent = None
        self.read_full = self.quiet = 0
        since = parse_time(self.data.get("checked_at"))
        if since is None:
            log("Email threads: no earlier run to compare with, so every company is read in full this time")
            return
        if not hasattr(emails_api, "emails_since"):
            return
        try:
            emails = emails_api.emails_since(_iso(since - OVERLAP), max_pages=MAX_PAGES)
        except Exception as err:  # never stops the run: everything is read in full instead
            log(f"Email threads: Instantly's list of new emails could not be read ({str(err)[:150]}); every "
                "company is read in full this run")
            return
        if emails is None:
            log("Email threads: very many new emails since the last run; every company is read in full this run")
            return
        self.recent = set()
        for e in emails:
            self.recent |= addresses_of(e)
        log(f"Email threads: {len(emails)} emails since the last run")

    def _max_age(self, company_id):
        try:
            spread = int(str(company_id)[-6:]) % (SPREAD_HOURS + 1)
        except ValueError:
            spread = 0
        return dt.timedelta(hours=MIN_AGE_HOURS + spread)

    def cached(self, company_id, contacts):
        """{contact id: [times emailed]} for a company none of whose people can have changed, or None (read
        it in full). contacts: as annotate() left them, before mark_sent()."""
        if self.recent is None:
            return None
        active = [c for c in contacts if c.get("state") in ACTIVE]
        if not active:
            return None
        touches = {}
        for c in active:
            entry = self.data["contacts"].get(str(c["id"]))
            email = (c["properties"].get("email") or "").strip().lower()
            if not entry or entry.get("state") != c.get("state") or not email or email in self.recent:
                return None
            at = parse_time(entry.get("at"))
            if at is None or self.now - at > self._max_age(company_id):
                return None
            times = [parse_time(t) for t in entry.get("touches") or []]
            touches[c["id"]] = [t for t in times if t is not None]
        return touches

    def remember(self, states, touches):
        """After a full read that left the company waiting: states {contact id: state before mark_sent}."""
        for cid, state in states.items():
            if state in ACTIVE:
                self.data["contacts"][str(cid)] = {"state": state, "at": _iso(self.now), "touches": sorted(
                    _iso(t) for t in (touches or {}).get(cid) or [] if t is not None)}

    def forget(self, contact_ids):
        for cid in contact_ids:
            self.data["contacts"].pop(str(cid), None)

    def finish(self, path=None):
        """Save for the next run. The time of this run is only kept when the new emails could be read (or
        on the first run), so nothing between two runs is ever skipped."""
        if self.recent is not None or self.data.get("checked_at") is None:
            self.data["checked_at"] = _iso(self.now)
        old = [cid for cid, e in self.data["contacts"].items()
               if (parse_time(e.get("at")) or self.now) < self.now - KEEP]
        for cid in old:
            self.data["contacts"].pop(cid, None)
        target = path or self.path or FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"checked_at": self.data["checked_at"],
                                      "contacts": dict(sorted(self.data["contacts"].items()))}, indent=1) + "\n",
                          encoding="utf-8")
        if self.quiet or self.read_full:
            self.log(f"Email threads: {self.read_full} companies read in full, {self.quiet} with no change since "
                     "their last reading")
