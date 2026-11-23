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
     changed is the contact held and named under Initial stages in the daily email.
  2. A first email to an address whose domain cannot receive email (no mail server in DNS) is not sent: the
     contact becomes "Unqualified: Contact corrupt" (Inbox Bounced for a company inbox), with "Outreach stopped
     because" saying why, and the next person at the company moves up (corrupt.close_dead).
  3. Old records (23 Nov 2026, Ariel: contacts created before send.address_checks.old_before, 1 Oct 2026, before the
     automation found its own; about 12 to 15% of them bounce) get their first email at most 20 a UK day
     (send.risky_per_day), mixed in with the others. Someone already emailed (a restart round) does not count. Until
     23 Nov 2026 an old record was a contact with no Outreach contact source, which wrongly caught Apollo people added
     when a company restarted.
  4. The brakes (split in two on 23 Nov 2026, Ariel), over the leads emailed in the last 7 days and only since
     brake.since (the clean start, 23 Nov 2026), the last 200 of them, with at least 50:
     - our own contacts (created from 1 Oct 2026): each campaign at 3% (send.brake). At or over it, no new
       introductions go into that campaign: they wait on GATE2;
     - old records: one brake over every campaign at 5% (send.old_brake). At or over it, no old record gets its
       first email; our own contacts carry on.
     A temporary bounce (inbox full, a temporary problem, a server that did not answer) counts in neither. Amodh is
     emailed when a brake comes on and when it lifts. Reminders carry on. Old bounces drop out after 7 days, so a
     brake lifts by itself once the rate is back under it. Instantly's own pause is at 5%.

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
DEFAULTS = {"risky_per_day": 20, "old_before": "2026-10-01",
            "brake": {"rate": 0.03, "last": 200, "days": 7, "min_sent": 50, "since": ""},
            "old_brake": {"rate": 0.05, "min_sent": 50}}


def settings_of(settings):
    s = dict(DEFAULTS, **((settings or {}).get("send") or {}).get("address_checks", {}) or {})
    s["brake"] = dict(DEFAULTS["brake"], **(s.get("brake") or {}))
    s["old_brake"] = dict(DEFAULTS["old_brake"], **(s.get("old_brake") or {}))
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

def is_old(contact, cfg=None):
    """23 Nov 2026 (Ariel): an old record is a contact created before old_before (1 Oct 2026). A record whose creation
    date is not known counts as old when it has no Outreach contact source (the rule before 23 Nov 2026)."""
    p = contact.get("properties", contact) or {}
    created = str(p.get("createdate") or "").strip()
    if created:
        return created[:10] < str((cfg or DEFAULTS).get("old_before") or DEFAULTS["old_before"])
    return not str(p.get(CONTACT_SOURCE) or "").strip()


def risky(contact, emailed_before, cfg=None):
    """True for a first email to an old record (see is_old)."""
    return not emailed_before and is_old(contact, cfg)


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

def _start(cfg, now, clean_start=False):
    """The earliest send that counts: `days` days back, and with clean_start never before brake.since."""
    since = now - dt.timedelta(days=float(cfg["brake"]["days"]))
    if clean_start and cfg["brake"].get("since"):
        start = dt.datetime.fromisoformat(str(cfg["brake"]["since"])).replace(tzinfo=UK).astimezone(dt.timezone.utc)
        since = max(since, start)
    return since


def campaign_rates(view, cfg, now=None, groups=None, group=None, clean_start=False):
    """{campaign id: (bounced, emailed)} over each campaign's last `last` leads emailed in the last `days` days.
    23 Nov 2026: with `groups` ({email: {"old": bool, "temporary": bool}}, from lead_groups) only the leads of
    `group` ("own" or "old") count, and a temporary bounce is not counted as a bounce; with clean_start only the
    sends since brake.since count."""
    from .next_in_line import parse_time
    now = now or dt.datetime.now(dt.timezone.utc)
    since = _start(cfg, now, clean_start)
    by_campaign = {}
    for email, lead in (view or {}).items():
        when = parse_time(lead.get("timestamp_last_contact"))
        if not (when and when >= since and lead.get("_campaign_id")):
            continue
        bounced = lead.get("status") == -1
        if groups is not None:
            about = groups.get(str(email).lower()) or {}
            if group and ("old" if about.get("old") else "own") != group:
                continue
            bounced = bounced and not about.get("temporary")
        by_campaign.setdefault(lead["_campaign_id"], []).append((when, bounced))
    out = {}
    for cid, items in by_campaign.items():
        last = sorted(items, key=lambda x: x[0], reverse=True)[:int(cfg["brake"]["last"])]
        out[cid] = (sum(1 for _, b in last if b), len(last))
    return out


TEMPORARY_REASONS = ("Bounced: inbox full", "Bounced: temporary problem")
TEMPORARY_CODE = re.compile(r"\b4\.\d{1,3}\.\d{1,3}\b")


def lead_groups(hs, view, cfg, now=None):
    """23 Nov 2026 (Ariel): {email: {"old": bool, "temporary": bool}} for the leads emailed since the brakes' start,
    read from HubSpot: old records by their creation date (is_old); a temporary bounce is a full inbox, a temporary
    problem or a 4.x.x code (a server that did not answer), or one button 4 keeps in the loop (corrupt.py)."""
    from .corrupt import load_temporary
    from .next_in_line import parse_time
    from .schema import STOP_REASON
    now = now or dt.datetime.now(dt.timezone.utc)
    since = _start(cfg, now, clean_start=True)
    emails = sorted({str(e).lower() for e, lead in (view or {}).items()
                     if (parse_time(lead.get("timestamp_last_contact")) or since - dt.timedelta(1)) >= since})
    if not emails:
        return {}
    temporary = set(load_temporary())
    out = {}
    for rec in hs.batch_read("contacts", emails, ["email", "createdate", CONTACT_SOURCE, STOP_REASON],
                             id_property="email"):
        p = rec.get("properties") or {}
        reason = str(p.get(STOP_REASON) or "")
        out[str(p.get("email") or "").lower()] = {
            "old": is_old(rec, cfg),
            "temporary": str(rec.get("id")) in temporary or reason.startswith(TEMPORARY_REASONS)
            or (reason.startswith("Bounced: other reason") and bool(TEMPORARY_CODE.search(reason)))}
    return out


def clears_at(view, cfg, campaign_id, limit, now=None):
    """22 Nov 2026 (Ariel): when a paused campaign's bounce rate (as campaign_rates counts it) is back under `limit`,
    if it sends nothing more: `now` when it already is, else the moment enough old emails leave the count."""
    from .next_in_line import parse_time
    now = now or dt.datetime.now(dt.timezone.utc)

    def under(when):
        bounced, emailed = campaign_rates(view, cfg, when).get(campaign_id, (0, 0))
        return not emailed or bounced / emailed < limit
    if under(now):
        return now
    keep = dt.timedelta(days=float(cfg["brake"]["days"]))
    leaving = sorted({when + keep for lead in (view or {}).values() if lead.get("_campaign_id") == campaign_id
                      for when in [parse_time(lead.get("timestamp_last_contact"))] if when and now - keep <= when <= now})
    for moment in leaving:
        later = moment + dt.timedelta(seconds=1)
        if under(later):
            return later
    return None


def braked(view, cfg, data, campaign_names, now=None, log=print, alert=None, groups=None):
    """The campaign IDs whose brake is on. Updates data["brake"] and emails Amodh when a brake comes on or lifts.
    23 Nov 2026: with `groups` only our own contacts count, since the clean start (brake.since)."""
    if groups is not None:
        rates = campaign_rates(view, cfg, now, groups, "own", clean_start=True)
    else:
        rates = campaign_rates(view, cfg, now, clean_start=True)
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
            text = (f"{name.get(cid, 'A campaign')}: {entry['bounced']} of the last {entry['emailed']} emails to our own "
                    f"contacts bounced ({entry['rate']:.1%}), over our 3% brake. No new introductions go into it "
                    "until the rate is back under 3% (old bounces drop out after 7 days); they wait on GATE2: "
                    "Approved to send. Reminders and the other campaigns carry on.")
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


def old_braked(view, cfg, data, groups, now=None, log=print, alert=None):
    """23 Nov 2026 (Ariel): True when the old records' own brake is on: at least old_brake.min_sent of the last `last`
    old records emailed since the clean start, over every campaign, and old_brake.rate (5%) or more of them bounced.
    Updates data["old_brake"] and emails Amodh when it comes on or lifts. Without `groups` (HubSpot could not be read)
    it keeps its last state."""
    was = data.get("old_brake") or {}
    if groups is None:
        return bool(was)
    from .next_in_line import parse_time
    now = now or dt.datetime.now(dt.timezone.utc)
    since = _start(cfg, now, clean_start=True)
    items = []
    for email, lead in (view or {}).items():
        when = parse_time(lead.get("timestamp_last_contact"))
        about = groups.get(str(email).lower()) or {}
        if when and when >= since and about.get("old"):
            items.append((when, lead.get("status") == -1 and not about.get("temporary")))
    last = sorted(items, key=lambda x: x[0], reverse=True)[:int(cfg["brake"]["last"])]
    bounced, emailed = sum(1 for _, b in last if b), len(last)
    limit, least = float(cfg["old_brake"]["rate"]), int(cfg["old_brake"]["min_sent"])
    if emailed >= least and bounced / emailed >= limit:
        entry = dict(was or {"since": uk_today(now)}, rate=round(bounced / emailed, 4), bounced=bounced,
                     emailed=emailed)
        if not was:
            text = (f"Old records (created before October 2026): {bounced} of the last {emailed} emailed bounced "
                    f"({bounced / emailed:.1%}), over their own {limit:.0%} brake. No old record gets its first email "
                    f"until the rate is back under {limit:.0%} (old bounces drop out after 7 days). Our own "
                    "contacts carry on.")
            log(f"Brake on: {text}")
            if alert:
                alert("Partner outreach: old records' bounce brake on", text)
        data["old_brake"] = entry
        return True
    if was:
        text = f"Old records: their bounce rate is back under {limit:.0%}, so they get first emails again."
        log(f"Brake lifted: {text}")
        if alert:
            alert("Partner outreach: old records' bounce brake lifted", text)
    data["old_brake"] = {}
    return False
