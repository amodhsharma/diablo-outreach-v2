"""Free checks before an introduction goes, and our own bounce brake (agreed 20 Nov 2026, Ariel).

No paid address verification is used (the free Instantly credits expired on 15 Jun 2026). Instead, at button 4's
send step (send.run), for the next person due at each company:

  1. Broken records are put right by the automation itself (21 Nov 2026, Ariel: no waiting for a person), for
     every contact on GATE2: Approved to send at each run (repair):
     - an address (or a web address) typed into a name: that name is cleared, when it is the contact's own address
       or a web address. A person whose first name is then empty, or whose name holds another email address than
       their own, becomes Contact corrupt;
     - no valid email address, or a technical mailbox of their mail system (postmaster@, mailer-daemon@, abuse@,
       no-reply@ and similar): Contact corrupt.
     Contact corrupt means "Unqualified: Contact corrupt" (also for a company inbox), "Outreach stopped because"
     saying why, and the next person at the company moves up (corrupt.close_dead). Only if HubSpot cannot be
     changed is the contact held and named under "Waiting for you" in the daily email.
  2. A first email to an address whose domain cannot receive email (no mail server in DNS) is not sent: the
     contact becomes "Unqualified: Contact corrupt" (Inbox Bounced for a company inbox), with "Outreach stopped
     because" saying why, and the next person at the company moves up (corrupt.close_dead).
  3. Old records and hand-added addresses (no Outreach contact source; about 12% of them bounced, against about
     3% for Apollo's) get their first email at most 20 a UK day (send.risky_per_day), mixed in with the others.
     Someone already emailed (a restart round) does not count.
  4. The brake: each campaign's bounce rate over its last 200 leads emailed in the last 7 days (send.brake). At 3%
     or more (with at least 50 of them), no new introductions go into that campaign: they wait on GATE2. Amodh is
     emailed when the brake comes on and when it lifts. Reminders and the other campaign carry on. Old bounces
     drop out after 7 days, so the brake lifts by itself once the rate is back under 3%. Instantly's own pause is
     at 5%.

data/address_checks.json keeps only counters, campaign IDs and dates: no names or addresses.
"""

import datetime as dt
import json
import re

from .common import ROOT
from .daily_log import UK
from .schema import CONTACT_SOURCE

FILE = ROOT / "data" / "address_checks.json"
VALID = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
URLISH = re.compile(r"(@|https?://|www\.)", re.I)
EMAIL_IN = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# 21 Nov 2026 (Ariel): the mail system's own mailboxes; no buyer reads them
TECHNICAL = ("postmaster", "mailer-daemon", "mailerdaemon", "hostmaster", "abuse", "webmaster", "noreply",
             "no-reply", "no_reply", "donotreply", "do-not-reply", "bounce", "bounces")
DEFAULTS = {"risky_per_day": 20, "brake": {"rate": 0.03, "last": 200, "days": 7, "min_sent": 50}}


def settings_of(settings):
    s = dict(DEFAULTS, **((settings or {}).get("send") or {}).get("address_checks", {}) or {})
    s["brake"] = dict(DEFAULTS["brake"], **(s.get("brake") or {}))
    return s


def load(path=None):
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data, path=None):
    path = path or FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


# ---- 1. Broken records ------------------------------------------------------------------------

def broken(contact):
    """Why this contact's record is broken (held for a person), or None."""
    p = contact.get("properties", contact) or {}
    email = str(p.get("email") or "").strip()
    if not VALID.match(email):
        return "its email address is not a valid address"
    for field, label in (("firstname", "first name"), ("lastname", "last name")):
        if URLISH.search(str(p.get(field) or "")):
            return f"its {label} holds an email or web address"
    return None


def repair(contact, today):
    """21 Nov 2026 (Ariel): put a broken record right without waiting for a person. Returns (fixes, why): fixes are
    the HubSpot changes that make the record usable (names cleared), why is the "Outreach stopped because" text
    when the contact is corrupt instead. (None, None) when nothing is wrong."""
    from .next_in_line import is_company_inbox
    record = contact if "properties" in contact else {"properties": contact}
    p = record.get("properties") or {}
    email = str(p.get("email") or "").strip()
    end = f" (found before sending, {today}); never emailed"
    if not VALID.match(email):
        return None, "Contact corrupt: its email address is not a valid address" + end
    local = email.split("@")[0].lower()
    if local in TECHNICAL:
        return None, f"Contact corrupt: {local}@ is a technical mailbox of their mail system, not a person or team" + end
    fixes = {}
    for field in ("firstname", "lastname"):
        value = str(p.get(field) or "")
        if not URLISH.search(value):
            continue
        if {a.lower() for a in EMAIL_IN.findall(value)} - {email.lower()}:
            return None, ("Contact corrupt: its name holds another email address than its own, so neither can be "
                          "trusted" + end)
        fixes[field] = ""
    if not fixes:
        return None, None
    if not is_company_inbox(record) and not str({**p, **fixes}.get("firstname") or "").strip():
        return None, "Contact corrupt: no name to greet them by, only an address" + end
    return fixes, None


# ---- 2. The domain can receive email -----------------------------------------------------------

_MAIL = {}


def domain_ok(email, check=None):
    """False only when DNS clearly says the address's domain has no mail server (each domain asked once a run)."""
    from .company_inbox import can_receive_mail
    domain = str(email or "").lower().split("@")[-1]
    if not domain:
        return True
    if domain not in _MAIL:
        _MAIL[domain] = bool((check or can_receive_mail)(domain))
    return _MAIL[domain]


def dead_domain_reason(today):
    return f"Contact corrupt: its email domain has no mail system (checked before sending, {today}); never emailed"


# ---- 3. Old records and hand-added addresses, at most 20 a day ---------------------------------

def risky(contact, emailed_before):
    """True for a first email to an address with no Outreach contact source (old records, added by hand)."""
    p = contact.get("properties", contact) or {}
    return not emailed_before and not str(p.get(CONTACT_SOURCE) or "").strip()


def uk_today(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(UK).date().isoformat()


def risky_room(data, cfg, now=None):
    """How many more old or hand-added addresses may get their first email today (UK day)."""
    day = uk_today(now)
    used = data.get("risky_sent", 0) if data.get("risky_day") == day else 0
    return max(0, int(cfg["risky_per_day"]) - used)


def count_risky(data, n, now=None):
    day = uk_today(now)
    if data.get("risky_day") != day:
        data["risky_day"], data["risky_sent"] = day, 0
    data["risky_sent"] = data.get("risky_sent", 0) + n


# ---- 4. The brake --------------------------------------------------------------------------------

def campaign_rates(view, cfg, now=None):
    """{campaign id: (bounced, emailed)} over each campaign's last `last` leads emailed in the last `days` days."""
    from .next_in_line import parse_time
    now = now or dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=float(cfg["brake"]["days"]))
    by_campaign = {}
    for lead in (view or {}).values():
        when = parse_time(lead.get("timestamp_last_contact"))
        if when and when >= since and lead.get("_campaign_id"):
            by_campaign.setdefault(lead["_campaign_id"], []).append((when, lead.get("status") == -1))
    out = {}
    for cid, items in by_campaign.items():
        last = sorted(items, key=lambda x: x[0], reverse=True)[:int(cfg["brake"]["last"])]
        out[cid] = (sum(1 for _, b in last if b), len(last))
    return out


def braked(view, cfg, data, campaign_names, now=None, log=print, alert=None):
    """The campaign IDs whose brake is on. Updates data["brake"] and emails Amodh when a brake comes on or lifts."""
    rates = campaign_rates(view, cfg, now)
    limit, least = float(cfg["brake"]["rate"]), int(cfg["brake"]["min_sent"])
    was = dict(data.get("brake") or {})
    on, today = {}, uk_today(now)
    for cid, (bounced, emailed) in rates.items():
        if emailed >= least and bounced / emailed >= limit:
            on[cid] = was.get(cid) or {"since": today}
            on[cid].update(rate=round(bounced / emailed, 4), bounced=bounced, emailed=emailed)
    name = {v: k for k, v in (campaign_names or {}).items()}
    for cid, entry in on.items():
        if cid not in was:
            text = (f"{name.get(cid, 'A campaign')}: {entry['bounced']} of its last {entry['emailed']} emails bounced "
                    f"({entry['rate']:.1%}), over our 3% brake. No new introductions go into it until the rate is "
                    "back under 3% (old bounces drop out after 7 days); they wait on GATE2: Approved to send. "
                    "Reminders and the other campaign carry on.")
            log(f"Brake on: {text}")
            if alert:
                alert("Partner outreach: bounce brake on", text)
    for cid in was:
        if cid not in on:
            text = (f"{name.get(cid, 'A campaign')}: its bounce rate is back under 3%, so new introductions go "
                    "into it again.")
            log(f"Brake lifted: {text}")
            if alert:
                alert("Partner outreach: bounce brake lifted", text)
    data["brake"] = on
    return set(on)
