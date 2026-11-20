"""The daily summary email (agreed 27 Oct 2026, Ariel; its content since 20 Nov 2026).

Every night at 00:05 UK time (cron-job.org starts the button "R - Daily summary email"; 10 AM UK until 20 Nov
2026) one email goes to Amodh, Rafi and Ariel (the GitHub secret DAILY_REPORT_TO), from admin@diablosnosugar.com
(a mailbox that sends no campaigns) through Google's own mail server. It reports the UK day that has just ended,
midnight to midnight UK time. HubSpot and Instantly are only read; nothing is changed anywhere. The old written
summary is gone (20 Nov 2026, Ariel).

One cut-off for everything (20 Nov 2026, Ariel): the charts and every part of Key numbers describe the same
moment, midnight UK at the end of the day reported. "Initial stages" (and every list in it) is worked out as it
stood at that midnight (AtCutoff), not read when the email goes, so a change made at 00:02 never shows in one
place and not the other. Before sending, the companies under "Your input needed" in the day chart are checked
against Key numbers; any the Key numbers do not list are named in one red line.

The email (20 Nov 2026, Ariel):
  1. The three Sankey charts (flow_charts.py): the UK day, the week so far and the month so far. A chart that
     cannot be drawn is written out instead, with exactly its words, numbers, %, arrows and notes. When HubSpot
     cannot be read at all, one line says the charts could not be produced, and why.
  2. "Key numbers", in four columns (Yesterday, Day before with an arrow as on the day chart, Week so far from
     Monday, added 21 Nov 2026, and Month so far):
       Sending: introductions sent, reminders sent (button 4's memory), Instantly uploads used of the plan's
         allowance (daily_report.instantly_allowance in settings). The aim of 240 introductions a day is not shown.
       Delivery: undelivered (with the bounce rate; Instantly pauses at 5%; under it, which sending account each
         bounce came from and at which company, with the reason written on the contact, for example "address does
         not exist"; 20 Nov 2026), asked not to be emailed, automatic replies (data/daily_log.json, written by
         button 4)
       Sending accounts: one green line when all are healthy, a red line naming each problem
       Positive replies to follow up: every company that replied that day tagged Positive, plus Neutral and
         Referral replies marked as such; Negative replies to convert into possible leads: the rest. No cap.
       Referrals handled automatically: only on days the automation handled some (21 Nov 2026, Ariel).
       Initial stages - your input needed or not (at midnight UK): what the chart's Initial stages box holds,
         with the names of everything waiting for a person (GATE1 and GATE2 approval, contacts not yet tagged,
         contacts held because their record could not be put right, companies whose channel is not known). The
         separate "Waiting for you" section was merged into it on 21 Nov 2026 (Ariel). What needs no input is one
         green line, "No input needed (automatic)", without a breakdown (21 Nov 2026, Ariel).
       Companies where nobody could be found (need sales people input): only on days there are some.

The recipients and the mailbox's Google app password (DAILY_REPORT_APP_PASSWORD) are never written in the
repository.
Usage:
    python -m outreach.daily_report --target live [--preview] [--day 2026-11-19]
"""

import argparse
import datetime as dt
import html
import os
import re
import smtplib
import ssl
import sys
from collections import Counter
from email.message import EmailMessage

from . import daily_log
from .apollo_status import NOWHERE
from .common import PipelineError, check_target, load_settings, step_summary
from .hubspot_client import HubSpot, HubSpotError
from .instantly_client import Instantly, InstantlyError
from .next_in_line import instantly_view, tagged_company_of
from .schema import LEAD_STATUS, STOP_REASON
from .stages import LeadStatus

INDIA = daily_log.INDIA
DAY_ZONE = daily_log.UK  # 20 Nov 2026 (Ariel): the day reported is the UK day, midnight to midnight
DEFAULTS = {"sender": "admin@diablosnosugar.com", "sender_name": "Diablo Partner Outreach",
            "smtp_host": "smtp.gmail.com", "smtp_port": 587}


def yesterday(now=None):
    """The UK date before today (UK time)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now.astimezone(DAY_ZONE).date() - dt.timedelta(days=1)).isoformat()


def window(first, last=None):
    """(start, end) in UTC of the UK dates first to last (inclusive), midnight to midnight UK time."""
    start = dt.datetime.combine(dt.date.fromisoformat(first), dt.time(), DAY_ZONE)
    end = dt.datetime.combine(dt.date.fromisoformat(last or first) + dt.timedelta(days=1), dt.time(), DAY_ZONE)
    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def _ms(when):
    return str(int(when.timestamp() * 1000))


def _between(prop, start, end):
    return [{"propertyName": prop, "operator": "GTE", "value": _ms(start)},
            {"propertyName": prop, "operator": "LT", "value": _ms(end)}]


def _entered(past, value, start, end):
    """True when the field became this value between start and end (past: newest first). value may be a list of
    values that mean the same (19 Nov 2026: the two labels of "no response"); moving between them does not count."""
    from .next_in_line import parse_time
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    for i, (v, t) in enumerate(past):
        when = parse_time(t)
        if v in values and when and start <= when < end:
            before = past[i + 1][0] if i + 1 < len(past) else None
            if before not in values:
                return True
    return False


def _value(statuses, obj, stage):
    return statuses.props(obj, stage)[LEAD_STATUS] if statuses.has(obj, stage) else None


def _days(first, last):
    d, end = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    while d <= end:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def sending(instantly, settings, dates, memory=None):
    """{date: {"intros": n, "reminders": n or None}} for each UK date: from button 4's memory where it covers the whole
    day (17 Nov 2026), otherwise the introductions from Instantly's last send time (reminders then unknown)."""
    from . import send_memory
    memory = send_memory.load() if memory is None else memory
    out, leads = {}, None
    for date in dates:
        counted = send_memory.day_counts(memory, date, DAY_ZONE)
        if counted is not None:
            out[date] = {"intros": counted["person"] + counted["inbox"], "reminders": counted["reminders"]}
            continue
        if leads is None:
            leads = instantly_view(instantly, settings["sync"]["campaign_prefix"])
        out[date] = {"intros": sum(1 for lead in leads.values() if lead.get("timestamp_last_contact")
                                   and daily_log.uk_day(lead["timestamp_last_contact"]) == date), "reminders": None}
    return out


def uploads(instantly, cfg):
    """(contacts in Instantly, the plan's allowance) or None when Instantly could not be read (20 Nov 2026)."""
    try:
        emails = {str(lead.get("email") or "").lower() for c in instantly.list_campaigns()
                  for lead in instantly.list_leads(c["id"]) if lead.get("email")}
    except (InstantlyError, AttributeError, KeyError):
        return None
    return len(emails), int(cfg.get("instantly_allowance") or 25000)


class AtCutoff:
    """20 Nov 2026 (Ariel): the AUTO-OUTREACH companies and contacts at a stage as they stood at the cut-off (midnight
    UK at the end of the day reported), so Key numbers and the charts describe the same moment. The records at the
    stage now, corrected with the Lead Status history of every record changed since the cut-off. A day not over yet
    (a sample of today so far) is read as it stands now."""

    PROPS = {"companies": ["name", "domain", "industry_type", "country"], "contacts": ["email", "firstname", "lastname"]}

    def __init__(self, hs, statuses, cutoff, now=None):
        self.hs, self.statuses, self.cutoff = hs, statuses, cutoff
        self.live = cutoff >= (now or dt.datetime.now(dt.timezone.utc))
        self._changed = {}

    def changed(self, obj):
        """{id: (properties, Lead Status history)} for the records changed since the cut-off."""
        if self.live:
            return {}
        if obj not in self._changed:
            ms = str(int(self.cutoff.timestamp() * 1000))
            rows = self.hs.tagged_search(obj, [{"propertyName": "hs_lastmodifieddate", "operator": "GTE", "value": ms}],
                                         ["name"], max_results=10000)
            ids = [str(r["id"]) for r in rows]
            self._changed[obj] = self.hs.history(obj, ids, LEAD_STATUS, self.PROPS[obj]) if ids else {}
        return self._changed[obj]

    def value(self, past, props):
        """The stored Lead Status at the cut-off (None when the record did not have one yet)."""
        from .flow_charts import end_value
        if not past:  # no history to go by: as it is now
            return props.get(LEAD_STATUS)
        return end_value(past, self.cutoff)

    def records(self, obj, stage):
        """[{"id", "properties"}] at that stage at the cut-off."""
        if not self.statuses.has(obj, stage):
            return []
        changed = self.changed(obj)
        out = [r for r in self.hs.tagged_search(obj, [self.statuses.filter(obj, stage)], self.PROPS[obj], max_results=5000)
               if str(r["id"]) not in changed]
        for rid, (props, past) in changed.items():
            value = self.value(past, props)
            if value not in (None, "") and self.statuses.stage(obj, value) == stage:
                out.append({"id": rid, "properties": dict(props)})
        return out


def nobody_found(hs, statuses, date):
    """The companies set to Missing Info with "No contact found anywhere" on that UK day, by name."""
    missing = _value(statuses, "companies", "missing_info")
    if not missing:
        return []
    start, end = window(date)
    changed = hs.tagged_search("companies", _between("hs_lastmodifieddate", start, end)[:1], ["name"], max_results=10000)
    past = hs.history("companies", [r["id"] for r in changed], LEAD_STATUS, ["name", STOP_REASON]) if changed else {}
    return sorted(((p.get("name") or "A company") for p, h in past.values() if _entered(h, missing, start, end)
                   and str(p.get(STOP_REASON) or "").startswith(NOWHERE)), key=str.lower)


# The tag a company's replies count as, strongest first, as on the Sankey chart (Positive over Negative over
# Neutral; a referral is Neutral on the chart). Neutral and referrals go in the follow-up list, marked as such
# (20 Nov 2026, Ariel), so every company that replied that day is named.
_ORDER = ("Positive", "Negative", "Referral", "Neutral")
_FROM_LOG = {"positive": "Positive", "negative": "Negative", "neutral": "Neutral"}


def replies(hs, day_entry, date, forwarded=None):
    """(follow up, negative): [(company name, country, mark or None)] for every company that replied on that UK day."""
    from . import reply_forward
    from .countries import uniform
    forwarded = reply_forward.load() if forwarded is None else forwarded
    kinds = {}
    for kind, tag in _FROM_LOG.items():
        for cid in day_entry.get(kind) or []:
            kinds.setdefault(str(cid), set()).add(tag)
    if not kinds:
        return [], []
    owner_of, companies = tagged_company_of(hs, list(kinds), ["name", "country"])
    tags = {}
    for cid, from_log in kinds.items():
        company = owner_of.get(cid)
        if company:
            tags.setdefault(company, set()).update(set(forwarded.get(cid) or []) or from_log)
    follow, negative = [], []
    for company, have in tags.items():
        props = (companies.get(company) or {}).get("properties") or {}
        tag = next((t for t in _ORDER if t in have), "Neutral")
        row = (props.get("name") or "A company", uniform(props.get("country")) or "country not known",
               None if tag in ("Positive", "Negative") else tag.lower())
        (negative if tag == "Negative" else follow).append(row)
    return sorted(follow, key=lambda r: r[0].lower()), sorted(negative, key=lambda r: r[0].lower())


def bounce_detail(hs, instantly, settings, contact_ids, date, emails_api=None):
    """20 Nov 2026 (Ariel): where the day's bounces came from. {"accounts": [(sending account, bounced, sent that
    day)], "companies": [(company, country, [reasons])]}, or None when it could not be read. The reason is the
    one written on the contact ("Bounced: address does not exist ...", 20 Nov 2026), when there is one."""
    from .countries import uniform
    if not contact_ids:
        return {"accounts": [], "companies": []}
    try:
        records = hs.tagged_read("contacts", [str(c) for c in contact_ids], ["email", STOP_REASON])
        view = instantly_view(instantly, settings["sync"]["campaign_prefix"])
        owner_of, companies = tagged_company_of(hs, [str(c) for c in contact_ids], ["name", "country"])
    except (HubSpotError, InstantlyError, KeyError, AttributeError):
        return None

    def mailbox(lead):
        return str((lead or {}).get("last_step_from") or (lead or {}).get("eaccount") or "").lower() or None
    bounced, sent = Counter(), Counter()
    for r in records:
        email = str((r.get("properties") or {}).get("email") or "").lower()
        box = mailbox(view.get(email))
        if not box and emails_api is not None:  # the last email we sent them, from Instantly's emails
            try:
                ours = emails_api.sent_emails(email)
                box = str((ours[-1] if ours else {}).get("eaccount") or "").lower() or None
            except (InstantlyError, AttributeError):
                box = None
        bounced[box or "sending account not known"] += 1
    start, end = window(date)
    try:  # every email each account sent that UK day (introductions and reminders)
        emails = emails_api.emails_since(start.isoformat()) if emails_api is not None else None
    except (InstantlyError, AttributeError):
        emails = None
    if emails is not None:
        from .next_in_line import parse_time
        for e in emails:
            when = parse_time(e.get("timestamp_created") or e.get("timestamp_email"))
            if e.get("ue_type") in (1, 3) and when and start <= when < end:
                sent[str(e.get("eaccount") or "").lower()] += 1
    else:
        sent = Counter(mailbox(lead) for lead in view.values() if lead.get("timestamp_last_contact")
                       and daily_log.uk_day(lead["timestamp_last_contact"]) == date)
    why = {str(r["id"]): _bounce_label((r.get("properties") or {}).get(STOP_REASON)) for r in records}
    names = {}
    for cid in contact_ids:
        company = companies.get(owner_of.get(str(cid)))
        if company:
            p = company.get("properties") or {}
            name, country, reasons = names.get(str(company["id"])) or (
                p.get("name") or "A company", uniform(p.get("country")) or "country not known", [])
            if why.get(str(cid)) and why[str(cid)] not in reasons:
                reasons.append(why[str(cid)])
            names[str(company["id"])] = (name, country, reasons)
    return {"accounts": sorted(((box, n, sent.get(box, 0)) for box, n in bounced.items()), key=lambda x: (-x[1], x[0])),
            "companies": sorted(names.values(), key=lambda x: x[0].lower())}


BOUNCE_LABEL = re.compile(r"^Bounced:\s*(.+?)\s*\(")


def _bounce_label(reason):
    """ "address does not exist" from "Bounced: address does not exist (20 Nov 2026). ...", or None."""
    m = BOUNCE_LABEL.match(str(reason or ""))
    return m.group(1) if m else None


def held_records(hs, statuses, at):
    """20 Nov 2026 (Ariel): the approved contacts held because their record is broken, as "Company (why)"."""
    from . import address_checks
    held = [(c, address_checks.broken(c)) for c in at.records("contacts", "approved")]
    held = [(c, why) for c, why in held if why]
    if not held:
        return []
    owner_of, companies = tagged_company_of(hs, [str(c["id"]) for c, _ in held], ["name"])
    out = []
    for c, why in held:
        company = companies.get(owner_of.get(str(c["id"]))) or {}
        out.append(f"{(company.get('properties') or {}).get('name') or 'A company'} ({why})")
    return sorted(out, key=str.lower)


def unknown_channel_companies(hs, statuses, notes=None, at=None):
    """{company id: name} for the open companies whose channel is not known, at the cut-off when `at` is given."""
    from . import channels
    from .common import load_company_notes
    notes = load_company_notes() if notes is None else notes
    at = at or AtCutoff(hs, statuses, dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    out = {}
    for stage in ("approved", "located", "no_response"):
        for c in at.records("companies", stage):
            if channels.verdict(c.get("properties") or {}, notes) is None:
                out[str(c["id"])] = (c.get("properties") or {}).get("name") or "A company"
    return out


def unknown_channels(hs, statuses, notes=None, at=None):
    """20 Nov 2026 (Ariel, HARD RULE): the open companies whose channel is not known, by name: nobody there is
    emailed until it is set (outreach/channels.py)."""
    return sorted(set(unknown_channel_companies(hs, statuses, notes, at).values()), key=str.lower)


def initial_stages(hs, statuses, unknown_names, at=None, unknown_ids=()):
    """20 Nov 2026 (Ariel): the companies not yet emailed, at the cut-off (midnight UK; `at`), split by whether
    Ariel's input is needed. {"input": [(label, count, [names])], "auto": [(label, count)], "ids": {company ids
    under Your input needed}}."""
    from .countries import uniform
    at = at or AtCutoff(hs, statuses, dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))

    def names(rows):
        return sorted(((r.get("properties") or {}).get("name") or "A company" for r in rows), key=str.lower)
    new, exists = at.records("companies", "found"), at.records("companies", "contact_exists")
    gate2 = at.records("contacts", "copy_ready")
    owner_of, owners = tagged_company_of(hs, [str(c["id"]) for c in gate2], ["name", "country"]) if gate2 else ({}, {})
    gate2_names = sorted({f"{(owners[k].get('properties') or {}).get('name') or 'A company'} "
                          f"({uniform((owners[k].get('properties') or {}).get('country')) or 'country not known'})"
                          for k in set(owner_of.values()) if k in owners}, key=str.lower)
    unknown = set(unknown_names)
    gate1 = [c for c in at.records("companies", "approved") if ((c.get("properties") or {}).get("name") or "") not in unknown]
    from . import address_checks  # 20 Nov 2026: a broken record is held until a person fixes it
    approved = at.records("contacts", "approved")
    held = [c for c in approved if address_checks.broken(c)]
    held_of, held_cos = tagged_company_of(hs, [str(c["id"]) for c in held], ["name"]) if held else ({}, {})
    held_names = sorted({(held_cos.get(k, {}).get("properties") or {}).get("name") or "A company"
                         for k in held_of.values()}, key=str.lower)
    ids = ({str(c["id"]) for c in new + exists} | {str(k) for k in owner_of.values()} | {str(i) for i in unknown_ids}
           | {str(k) for k in held_of.values()})
    return {"input": [("New companies waiting for your GATE1 approval", len(new), names(new)),
                      ("Introductions waiting for your GATE2 approval", len(gate2), gate2_names),
                      ("Contacts not yet tagged AUTO-OUTREACH", len(exists), names(exists)),
                      ("Companies whose channel is not known", len(unknown), sorted(unknown, key=str.lower))]
            + ([("Contacts held: broken record", len(held), held_names)] if held else []),
            "auto": [("Approved, Apollo search at the next button 3 run", len(gate1)),
                     ("People found, introduction lines being written", len(at.records("contacts", "found"))),
                     ("Introductions approved, waiting their turn to send", len(approved) - len(held))],
            "ids": ids}


def key_numbers(hs, instantly, settings, date, cfg, accounts_api=None, log_data=None, statuses=None, emails_api=None,
                now=None):
    """Everything the "Key numbers" section shows (agreed 20 Nov 2026, Ariel), for the UK day `date`."""
    before = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
    month_first = date[:8] + "01"
    statuses = statuses or LeadStatus(hs)
    # 20 Nov 2026 (Ariel): one cut-off for the whole email, midnight UK at the end of the day reported
    at = AtCutoff(hs, statuses, window(date)[1], now)
    unknown = unknown_channel_companies(hs, statuses, at=at)
    data = daily_log.load() if log_data is None else log_data
    month_days = list(_days(month_first, date))
    # 21 Nov 2026 (Ariel): a "Week so far" column too, Monday to the day reported, as on the week chart
    monday = (dt.date.fromisoformat(date) - dt.timedelta(days=dt.date.fromisoformat(date).weekday())).isoformat()
    week_days = list(_days(monday, date))
    sent = sending(instantly, settings, sorted(set(month_days) | set(week_days) | {before}))
    month = daily_log.month_counts(data, month_first, date, uk=True)
    today, previous = daily_log.day(data, date, uk=True), daily_log.day(data, before, uk=True)
    reminders_known = [sent[d]["reminders"] for d in month_days if sent[d]["reminders"] is not None]
    week = daily_log.month_counts(data, monday, date, uk=True, before=False)
    week_reminders = [sent[d]["reminders"] for d in week_days if sent[d]["reminders"] is not None]
    follow, negative = replies(hs, today, date)
    out = {
        "date": date, "before": before,
        "intros": (sent[date]["intros"], sent[before]["intros"], sum(sent[d]["intros"] for d in month_days)),
        "reminders": (sent[date]["reminders"], sent[before]["reminders"], sum(reminders_known) if reminders_known else None),
        "sent_total": (sum(x or 0 for x in (sent[date]["intros"], sent[date]["reminders"])),
                       sum(sent[d]["intros"] + (sent[d]["reminders"] or 0) for d in month_days)),
        "uploads": uploads(instantly, cfg),
        "bounced": (len(today["bounced"]), len(previous["bounced"]), month["bounced"]),
        "opted_out": (len(today["opted_out"]), len(previous["opted_out"]), month["opted_out"]),
        "auto": (len(today["auto"]), len(previous["auto"]), month["auto"]),
        "week": {"intros": sum(sent[d]["intros"] for d in week_days),
                 "reminders": sum(week_reminders) if week_reminders else None,
                 "sent": sum(sent[d]["intros"] + (sent[d]["reminders"] or 0) for d in week_days),
                 "bounced": week["bounced"], "opted_out": week["opted_out"], "auto": week["auto"]},
        "accounts": health(instantly, settings, accounts_api, day=date),
        "follow": follow, "negative": negative,
        "gate1": len(at.records("companies", "found")),
        "gate2": len(at.records("contacts", "copy_ready")),
        "nowhere": nobody_found(hs, statuses, date),
        "bounces": bounce_detail(hs, instantly, settings, today["bounced"], date, emails_api),
        "unknown_channel": sorted(set(unknown.values()), key=str.lower),
        "held": held_records(hs, statuses, at),  # 20 Nov 2026: broken records, not sent
        "at_midnight": not at.live,
    }
    out["initial"] = initial_stages(hs, statuses, out["unknown_channel"], at, unknown)
    # 21 Nov 2026 (Ariel): the replies that named someone else (until then a separate email to Amodh) and the
    # replies from people who are not AUTO-OUTREACH contacts, both for the UK day
    from . import outside_replies, referrals
    try:
        out["referrals"] = referrals.report_data(hs, emails_api, statuses, date) or {}
    except Exception:  # never stops the email: the section says it could not be read
        out["referrals"] = None
    start, end = window(date)
    out["outside"] = outside_replies.read(hs, emails_api, start, end)
    return out


def health(instantly, settings, accounts_api=None, view=None, day=None):
    """21 Nov 2026 (Ariel): the Health section. {"campaigns": [(colour, full name, state, bounce rate text)],
    "accounts": {"healthy": n, "total": n, "problems": [(address, reason)]}}, or None when Instantly could not be
    read. Only this month's Diablo campaigns and the sending accounts they use. Straight to the point.
    21 Nov 2026 (Ariel): "this month" is the month of the UK day the email reports (`day`), so the email sent just
    after midnight on the 1st still shows last month's campaigns, never the new month's."""
    from . import address_checks
    from .check_instantly import CAMPAIGN_STATUS, diablo_campaigns, mailbox_verdict
    from .send import month_label
    try:
        prefix = settings["sync"]["campaign_prefix"]
        month = month_label(dt.date.fromisoformat(day) if isinstance(day, str) else day)
        campaigns = [c for c in diablo_campaigns(instantly, prefix) if month in str(c.get("name") or "")]
        cfg = address_checks.settings_of(settings)
        rates = address_checks.campaign_rates(view if view is not None else instantly_view(instantly, prefix), cfg)
        limit, least = float(cfg["brake"]["rate"]), int(cfg["brake"]["min_sent"])
        rows, used = [], set()
        for camp in sorted(campaigns, key=lambda c: str(c.get("name") or "")):
            mailboxes = [m.lower() for m in camp.get("email_list") or []]
            used.update(mailboxes)
            connected = None
            try:
                status = instantly.request("GET", f"/campaigns/{camp['id']}/sending-status")
                connected = (((status or {}).get("diagnostics") or {}).get("accounts_summary") or {}).get("total_connected")
            except (InstantlyError, AttributeError):
                pass
            code = camp.get("status")
            waiting = sum(1 for lead in instantly.list_leads(camp["id"]) if not lead.get("timestamp_last_contact")) \
                if code not in (1, None) else 0
            bounced, emailed = rates.get(camp["id"], (0, 0))
            rate = f"{bounced / emailed:.1%} bounced" if emailed else ""
            braked = emailed >= least and bounced / emailed >= limit
            wait = f", {waiting} introductions waiting" if waiting else ""
            if not mailboxes or connected == 0:
                colour, state = BAD, "No sending account connected" + wait
            elif code == -2:
                colour, state = BAD, "Paused by Instantly (Bounce Protect)" + wait
            elif code == -1:
                colour, state = BAD, "Paused: a sending account has a problem" + wait
            elif code == -99:
                colour, state = BAD, "Suspended by Instantly" + wait
            elif code == 2:
                colour, state = BAD, "Paused" + wait
            elif code == 0:
                colour, state = WARN, "Not started (Draft)" + wait
            elif braked:
                colour, state = WARN, "Running; our 3% brake is on, new introductions wait"
            elif code in (1, None, 4):
                colour, state = GOOD, "Running"
            else:
                colour, state = SAME, CAMPAIGN_STATUS.get(code, "Unknown")
            rows.append((colour, camp.get("name") or "A campaign", state, rate))
        problems, total = [], 0
        for acc in (accounts_api or instantly).list_accounts():
            email = (acc.get("email") or "").lower()
            if email not in used:
                continue
            total += 1
            verdict, reasons = mailbox_verdict(acc)
            if verdict != "Ready":
                problems.append((email, (reasons[0] if reasons else verdict).split(":")[0].rstrip(".")))
        return {"campaigns": rows, "accounts": {"healthy": total - len(problems), "total": total,
                                                "problems": sorted(problems)}}
    except (InstantlyError, AttributeError, KeyError):
        return None


def _long_date(date):
    d = dt.date.fromisoformat(date)
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B %Y')}"


def _plural(n, one, many=None):
    return one if n == 1 else (many or one + "s")


GOOD, BAD, SAME = "#0F6E56", "#C0392B", "#888780"
WARN = "#BA7517"  # 21 Nov 2026: a campaign held by our own brake, or not started


def _n(value):
    return "-" if value is None else f"{value:,}"


def _arrow(day, before, rise_is_good):
    """(symbol, good): as on the day chart, ▲ or ▼ against the day before, coloured good or bad; = when the same."""
    if day is None or before is None:
        return None, None
    if day == before:
        return "=", None
    up = day > before
    return ("▲" if up else "▼"), (None if rise_is_good is None else up == rise_is_good)


def _rate(n, sent):
    return f"{_n(n)} ({n / sent:.1%})" if sent and n else _n(n)


def _at(name, country, reasons=()):
    """ "Kadac (Australia: address does not exist)": the company and, since 20 Nov 2026, why it bounced."""
    return f"{name} ({country}" + (f": {'; '.join(reasons)}" if reasons else "") + ")"


def bounce_lines(detail, bounced):
    """20 Nov 2026 (Ariel): under "Undelivered", which sending accounts the day's bounces came from and at which
    companies."""
    if not bounced:
        return []
    if detail is None:
        return [("line", "Where they came from could not be read this morning", SAME)]
    parts = [f"{box} {n}" + (f" ({n / sent:.0%} of its {sent} emails)" if sent else "")
             for box, n, sent in detail["accounts"]]
    out = [("line", "By sending account: " + ", ".join(parts), None)] if parts else []
    if detail["companies"]:
        out.append(("line", "At: " + ", ".join(_at(*c) for c in detail["companies"]), None))
    return out


# 21 Nov 2026 (Ariel): a coloured label before each heading says what kind of section it is.
PARAMETER, HEALTH, SALES = "Parameter", "Health", "For sales team"
AMODH, INFO = "Need Amodh's input", "For information"
TAGS = {PARAMETER: ("#E6F1FB", "#0C447C"), HEALTH: ("#EEEDFE", "#3C3489"), SALES: ("#EAF3DE", "#27500A"),
        AMODH: ("#FAEEDA", "#854F0B"), INFO: ("#F1EFE8", "#444441")}


def reply_blocks(k):
    """21 Nov 2026 (Ariel): three sections after the negative replies. Headings are (text, tag, count); a
    ("table", headers or None, rows) item holds rows of cells, a cell being text or (text, link)."""
    if "referrals" not in k and "outside" not in k:
        return []
    ref, outside = k.get("referrals"), k.get("outside")
    unsure, auto = [], []
    if ref is None:
        unsure = [("line", "Could not be read this time", SAME)]
    else:
        rows = [((f"{u['company']}" + (f" ({u['country']})" if u.get("country") else ""), u["link"]), u["job"], u["why"],
                 f'"{u["reply"]}"' if u.get("reply") else "") for u in ref.get("unsure") or []]
        unsure = [("table", ["Company", "Who replied", "Why it wasn't sure", "Their reply"], rows)] if rows else \
            [("line", "None", SAME)]
        if ref.get("waiting"):
            unsure.append(("line", f"Still waiting from earlier days: {len(ref['waiting'])} ("
                           + ", ".join(ref["waiting"]) + ")", None))
    if outside is None:
        outs = [("line", "Could not be read this time (Instantly's emails)", SAME)]
    elif outside:
        outs = [("table", ["Company", "Arrived in", "In HubSpot", "Their reply"],
                 [(o["company"] + (f" ({o['country']})" if o.get("country") else ""), o["mailbox"], o["hubspot"],
                   f'"{o["reply"]}"' if o.get("reply") else "") for o in outside])]
    else:
        outs = [("line", "None", SAME)]
    if ref is not None:  # one row each, its count under "Yesterday" like the rest, the companies under it
        auto = []
        for label, names in (("Switched to the new person",
                              [f"{c}: {j} to {n}" for c, j, n in ref.get("switched") or []]),
                             ("Stand-ins added from an out-of-office",
                              [f"{c}: {j} away, {n} added" for c, j, n in ref.get("added") or []]),
                             ("Back in the loop", [c for c, _ in ref.get("resumed") or []])):
            if names:  # 21 Nov 2026 (Ariel): a line with nothing in it is left out
                auto.append(("row", "  " + label, _n(len(names)), "", None, None, ""))
                auto += [("name", n) for n in names]
    else:
        auto = [("line", "Could not be read this time", SAME)]
    n_unsure = len((ref or {}).get("unsure") or [])
    n_auto = sum(len((ref or {}).get(x) or []) for x in ("switched", "added", "resumed"))
    blocks = [(("Referrals the automation wasn't sure about", [AMODH], n_unsure), unsure),
              (("Replies not AUTO-OUTREACH", [AMODH], len(outside or [])), outs)]
    if n_auto:  # 21 Nov 2026 (Ariel): shown only when referrals were handled automatically, with the companies
        blocks.append((("Referrals handled automatically", [INFO], n_auto), auto))
    return blocks


def _heading(h):
    """(text, [labels], count or None) for a heading written as text, (text, labels) or (text, labels, count)."""
    if not isinstance(h, tuple):
        return h, [], None
    text, tags, count = (h + (None,))[:3]
    return text, ([tags] if isinstance(tags, str) else list(tags or [])), count


def key_rows(k):
    """(title, [(heading, [item])]) for the "Key numbers" section. item: ("row", label, day, before, arrow, good,
    month), ("line", text, colour) or ("name", text)."""
    weekly = k.get("week") or {}

    def row(label, values, rise_is_good, day_text=None, month_text=None, key=None, week_text=None):
        day, before, month = values
        symbol, good = _arrow(day, before, rise_is_good)
        week = week_text or (_n(weekly.get(key)) if key in weekly else "")  # 21 Nov 2026: Week so far
        return ("row", label, day_text or _n(day), _n(before), symbol, good, month_text or _n(month), None, week)

    sending_ = [row("Introductions sent", k["intros"], True, key="intros"),
                row("Reminders sent", k["reminders"], True, key="reminders")]
    if k["uploads"]:
        used, allowed = k["uploads"]
        sending_.append(("line", f"Instantly uploads used: {used:,} of {allowed:,} ({used / allowed:.0%})",
                         BAD if used >= 0.9 * allowed else None))
    else:
        sending_.append(("line", "Instantly uploads used: Instantly could not be read this morning", SAME))
    day_sent, month_sent = k["sent_total"]
    delivery = [row("Undelivered (bounced; Instantly pauses at 5%)", k["bounced"], False,
                    _rate(k["bounced"][0], day_sent), _rate(k["bounced"][2], month_sent), key="bounced",
                    week_text=_rate(weekly["bounced"], weekly.get("sent")) if "bounced" in weekly else None),
                *bounce_lines(k.get("bounces"), k["bounced"][0]),
                row("Asked not to be emailed", k["opted_out"], False, key="opted_out"),
                row("Automatic replies (out of office)", k["auto"], None, key="auto")]
    h = k.get("accounts")
    if h is None:
        campaigns = accounts = [("line", "Instantly could not be read this time", SAME)]
    else:
        campaigns = [("health", colour, name, state, rate) for colour, name, state, rate in h["campaigns"]] or \
            [("line", "No campaign this month yet", SAME)]
        if any(rate for *_, rate in h["campaigns"]):
            campaigns.append(("line", "% = bounces over each campaign's last 200 emails of the last 7 days", SAME))
        a = h["accounts"]
        accounts = [("health", GOOD if not a["problems"] else BAD, f"{a['healthy']} of {a['total']} healthy", "", "")]
        accounts += [("health", BAD, email, reason, "") for email, reason in a["problems"]]
    when = dt.date.fromisoformat(k["date"])
    replied = f"replied {when.strftime('%a')} {when.day} {when.strftime('%b')}"

    def names(rows):
        if not rows:
            return [("line", "None", SAME)]
        return [("name", f"{name} ({country}), {replied}" + (f" ({mark})" if mark else "")) for name, country, mark in rows]
    # 21 Nov 2026 (Ariel): a line with 0 is left out; the heading always shows, with its total
    blocks = [(("Sending", [PARAMETER]), sending_), (("Delivery", [PARAMETER]), delivery),
              (("Campaigns", [HEALTH]), campaigns), (("Sending accounts", [HEALTH]), accounts),
              (("Positive replies to follow up", [SALES]), names(k["follow"])),
              (("Negative replies to convert into possible leads", [SALES]), names(k["negative"])),
              *reply_blocks(k)]
    if k.get("initial"):  # 20 Nov 2026 (Ariel): what the chart's Initial stages box holds, at midnight UK
        # 21 Nov 2026 (Ariel): "Waiting for you" is merged in here; it named the same companies twice
        shown = {"Contacts held: broken record": ("Contacts held: broken record", k.get("held")),
                 "Companies whose channel is not known": ("Companies whose channel is not known (nobody is emailed "
                                                          "until it is set)", None)}
        need = sum(n for _, n, _ in k["initial"]["input"])
        auto = sum(n for _, n in k["initial"]["auto"])
        rows = [("line", k["check"], BAD)] if k.get("check") else []
        rows.append(("row", "Your input needed", _n(need), "", None, None, ""))
        for label, n, who in k["initial"]["input"]:
            if n:  # 21 Nov 2026 (Ariel): a line with 0 is left out
                text, detail = shown.get(label, (label, None))
                rows.append(("row", "  " + text, _n(n), "", None, None, ""))
                rows += [("name", w) for w in (detail or who)]
        # 21 Nov 2026 (Ariel): one green line, without the breakdown
        rows.append(("row", "No input needed (automatic)", _n(auto), "", None, None, "", GOOD))
        moment = "at midnight UK" if k.get("at_midnight", True) else "right now"
        blocks.append(((f"Initial stages - your input needed or not ({moment})", [AMODH], need + auto), rows))
    else:  # Initial stages could not be worked out: the same things, the short way
        waiting = [("row", label, _n(n), "", None, None, "") for label, n in
                   (("Companies waiting for GATE1 approval", k["gate1"]),
                    ("Introductions waiting for GATE2 approval", k["gate2"])) if n]
        for label, who in (("Contacts held: broken record", k.get("held") or []),
                           ("Companies whose channel is not known (nobody is emailed until it is set)",
                            k.get("unknown_channel") or [])):
            if who:
                waiting += [("row", label, _n(len(who)), "", None, None, "")] + [("name", w) for w in who]
        n_waiting = k["gate1"] + k["gate2"] + len(k.get("held") or []) + len(k.get("unknown_channel") or [])
        blocks.append((("Your input needed", [AMODH], n_waiting), waiting or [("line", "None", SAME)]))
    if k["nowhere"]:  # 21 Nov 2026 (Ariel): past the initial stages (Unqualified on the charts), so on its own
        blocks.append((("Companies where nobody could be found (need sales people input)", [AMODH],
                        len(k["nowhere"])), [("name", n) for n in k["nowhere"]]))
    return f"Key numbers - {_long_date(k['date'])}", blocks


def key_text(k):
    title, blocks = key_rows(k)
    width = max(len(i[1]) for _, items in blocks for i in items if i[0] == "row") + 4
    out = [title, f"{'':{width + 2}}{'Yesterday':<16}{'Day before':<16}{'Week so far':<16}Month so far"]
    for heading, items in blocks:
        text, tags, count = _heading(heading)
        label = "".join(f"[{t}] " for t in tags) + text
        out.append(f"{label:<{width + 1}} {count}" if count is not None else label)
        for item in items:
            if item[0] == "row":
                _, label, day, before, symbol, _good, month = item[:7]
                week = item[8] if len(item) > 8 else ""
                out.append(f"  {label:<{width}}{day:<16}{(before + (' ' + symbol if symbol else '')):<16}{week:<16}{month}"
                           .rstrip())
            elif item[0] == "line":
                out.append(f"  {item[1]}")
            elif item[0] == "health":
                _, colour, name, state, rate = item
                mark = {GOOD: "OK", BAD: "!!", WARN: "!"}.get(colour, "-")
                out.append(f"  {mark:<3}{name}" + (f": {state}" if state else "") + (f" ({rate})" if rate else ""))
            elif item[0] == "table":
                for row in item[2]:
                    cells = [c[0] if isinstance(c, tuple) else c for c in row]
                    out.append("  - " + " | ".join(c for c in cells if c))
            else:
                out.append(f"    {item[1]}")
    return out


def key_html(k):
    e = html.escape
    title, blocks = key_rows(k)
    cell = 'style="padding:2px 10px;text-align:right;white-space:nowrap"'
    parts = [f'<p style="margin:24px 0 6px;font-size:16px"><b>{e(title)}</b></p>',
             '<table style="border-collapse:collapse;font-size:14px"><tr><td></td>'
             + "".join(f'<td {cell}><span style="color:{SAME}">{h}</span></td>'
                       for h in ("Yesterday", "Day before", "Week so far", "Month so far")) + "</tr>"]
    for heading, items in blocks:
        text, tags, count = _heading(heading)
        tag_html = "".join(f'<span style="background:{TAGS[t][0]};color:{TAGS[t][1]};padding:1px 8px;border-radius:6px;'
                           f'font-weight:normal;font-size:12px;margin-right:6px">{e(t)}</span>' for t in tags)
        if count is None:
            parts.append(f'<tr><td colspan="5" style="padding:10px 0 2px">{tag_html}<b>{e(text)}</b></td></tr>')
        else:
            parts.append(f'<tr><td style="padding:10px 0 2px">{tag_html}<b>{e(text)}</b></td>'
                         f'<td {cell}><b>{count}</b></td><td></td><td></td><td></td></tr>')
        for item in items:
            if item[0] == "health":
                _, colour, name, state, rate = item
                parts.append(f'<tr><td colspan="5" style="padding:2px 10px 2px 14px"><span style="color:{colour}">&#9679;</span> '
                             f'{e(name)}' + (f': <span style="color:{colour if colour != GOOD else "inherit"}">{e(state)}</span>'
                                             if state else "") + (f' <span style="color:{SAME}">({e(rate)})</span>'
                                                                  if rate else "") + "</td></tr>")
                continue
            if item[0] == "table":
                parts.append(f'<tr><td colspan="5" style="padding:2px 10px 6px 14px">{_table_html(item[1], item[2])}</td></tr>')
                continue
            if item[0] == "row":
                _, label, day, before, symbol, good, month = item[:7]
                colour = SAME if good is None else (GOOD if good else BAD)
                arrow = f' <span style="color:{colour};font-weight:bold">{symbol}</span>' if symbol else ""
                indent = 28 if label.startswith("  ") else 14
                tint = f"color:{item[7]};" if len(item) > 7 and item[7] else ""  # 21 Nov 2026: own colour
                week = item[8] if len(item) > 8 else ""
                parts.append(f'<tr><td style="padding:2px 10px 2px {indent}px;{tint}">{e(label.strip())}</td>'
                             f'<td {cell}><b style="{tint}">{e(day)}</b></td>'
                             f"<td {cell}>{e(before)}{arrow}</td><td {cell}>{e(week)}</td><td {cell}>{e(month)}</td></tr>")
            elif item[0] == "line":
                dot = f'<span style="color:{item[2]}">&#9679;</span> ' if item[2] in (GOOD, BAD) else ""
                style = f"color:{item[2]};" if item[2] else ""
                parts.append(f'<tr><td colspan="5" style="padding:2px 10px 2px 14px;{style}">{dot}{e(item[1])}</td></tr>')
            else:
                parts.append(f'<tr><td colspan="5" style="padding:1px 10px 1px 28px">{e(item[1])}</td></tr>')
    return "".join(parts) + "</table>"


def _table_html(headers, rows):
    """A small table inside a Key numbers section (21 Nov 2026)."""
    e = html.escape
    td = 'style="padding:4px 8px 4px 0;vertical-align:top;border-top:1px solid #e5e5e5"'

    def cell(c):
        if isinstance(c, tuple):
            return f'<a href="{e(c[1])}">{e(c[0])}</a>'
        return e(c)
    head = ("<tr>" + "".join(f'<td style="padding:2px 8px 2px 0;color:{SAME};font-size:12px">{e(h)}</td>'
                             for h in headers) + "</tr>") if headers else ""
    body = "".join("<tr>" + "".join(f"<td {td}>{cell(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table style="border-collapse:collapse;font-size:13px;width:100%">{head}{body}</table>'


def chart_html(spec):
    """A chart that could not be drawn, written out (flow_charts.chart_lines), with the arrows coloured as on the chart."""
    from .flow_charts import chart_lines
    e = html.escape
    parts = [f'<p style="margin:18px 0 2px"><b>{e(spec.get("title", ""))}</b><br>'
             f'<span style="color:{SAME}">{e(spec.get("subtitle", ""))}</span>'
             + (f'<br><span style="color:#854F0B">{e(spec["flag"])}</span>' if spec.get("flag") else "") + '</p><div>']
    for r in chart_lines(spec):
        pad = 18 * r["level"]
        text = e(r["label"])
        if r["value"] is not None:
            text = f"{text}: <b>{r['value']}</b>" + (f" ({r['pct']}%)" if r["pct"] is not None else "")
            if r["arrow"] == "=":
                text += f' <span style="color:{SAME}">= {r["was"]}%</span>'
            elif r["arrow"]:
                text += (f' <span style="color:{GOOD if r["good"] else BAD};font-weight:bold">{r["arrow"]}</span>'
                         f'<span style="color:{SAME}"> was {r["was"]}%</span>')
        parts.append(f'<div style="padding-left:{pad}px">{text}</div>')
        if r["note"]:
            parts.append(f'<div style="padding-left:{pad + 18}px;color:#854F0B">{e(r["note"])}</div>')
    return "".join(parts) + "</div>"


def recipients(value=None):
    value = os.environ.get("DAILY_REPORT_TO", "") if value is None else value
    return [a.strip() for a in re.split(r"[,;\s]+", value) if "@" in a]


def send_mail(subject, text, html_body, cfg, to, password, smtp=None, images=()):
    """images: [(content id, png path)] shown inside the HTML (the Sankey charts)."""
    from pathlib import Path
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{cfg['sender_name']} <{cfg['sender']}>"
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    if images:
        html_part = msg.get_payload()[1]
        for cid, png in images:
            html_part.add_related(Path(png).read_bytes(), maintype="image", subtype="png", cid=cid,
                                  filename=Path(png).name)
    if smtp is None:
        smtp = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=60)
        smtp.starttls(context=ssl.create_default_context())
    with smtp:
        smtp.login(cfg["sender"], password)
        smtp.send_message(msg)


def charts_for(hs, settings, date, log=print, draw=None, out_dir="flow_charts", log_data=None):
    """20 Nov 2026 (Ariel): the three Sankey charts (the UK day, the week so far, the month so far) for this email:
    [(spec, content id or None, png or None, state)], state "drawn", "empty" (no company changed status) or "text"
    (it could not be drawn, so the email writes it out). Raises when the figures cannot be read at all."""
    from email.utils import make_msgid
    from . import flow_charts
    failed = []
    real = draw or flow_charts.render

    def safe(spec, png):
        try:
            return real(spec, png)
        except Exception as err:  # never stops the email: the chart is written out instead
            failed.append(str(err)[:200])
            return None
    drawn, specs = flow_charts.draw_all(hs, settings, dt.date.fromisoformat(date), out_dir, log, draw=safe, zone=DAY_ZONE,
                                        log_data=log_data)
    if failed:
        log(f"The Sankey charts could not be drawn, so the email writes them out: {failed[0]}")
    out = []
    for (_title, png), spec in zip(drawn, specs):
        state = "drawn" if png else ("text" if spec["total"] else "empty")
        out.append((spec, make_msgid(domain="diablo-outreach") if png else None, png, state))
    return out


WRITTEN_OUT = "The charts could not be drawn today, so they are written out below."
NO_CHANGE = "no AUTO-OUTREACH company changed status."


def compose(date, charts, key, problem=None, key_problem=None):
    """(subject, text, html, images) of the email (20 Nov 2026, Ariel): the three charts, then Key numbers. When the
    figures could not be read at all, one line says so and why."""
    e = html.escape
    subject = f"Partner outreach: daily summary, {_long_date(date)}"
    text, parts, images = [], ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#222">'], []
    if problem:
        line = f"Today's charts could not be produced: {problem}."
        text.append(line)
        parts.append(f"<p>{e(line)}</p>")
    elif any(state == "text" for *_x, state in charts):
        text += [WRITTEN_OUT, ""]
        parts.append(f"<p>{e(WRITTEN_OUT)}</p>")
    for spec, cid, png, state in charts:
        if state == "drawn":
            images.append((cid, png))
            text.append(f"{spec['title']} (chart in the HTML version of this email)")
            parts.append(f'<p><img src="cid:{cid[1:-1]}" alt="{e(spec["title"])}" style="max-width:100%;height:auto"></p>')
        elif state == "empty":
            text.append(f"{spec['title']}: {NO_CHANGE}")
            parts.append(f"<p>{e(spec['title'])}: {NO_CHANGE}</p>")
        else:
            from .flow_charts import chart_text
            text += chart_text(spec) + [""]
            parts.append(chart_html(spec))
    if key is not None:
        text += [""] + key_text(key)
        parts.append(key_html(key))
    elif key_problem and not problem:
        line = f"The key numbers could not be read this morning: {key_problem}."
        text += ["", line]
        parts.append(f"<p>{e(line)}</p>")
    return subject, "\n".join(text).strip() + "\n", "".join(parts) + "</div>", images


def sync_check(day_spec, key):
    """20 Nov 2026 (Ariel): every company under "Your input needed" in the day chart must be listed under Your input
    needed in Key numbers (both are at midnight UK). A line naming any that are not, or None when they match."""
    ids = (key.get("initial") or {}).get("ids")
    if ids is None:
        return None
    missing = {cid: name for cid, name in (day_spec.get("input") or {}).items() if str(cid) not in ids}
    if not missing:
        return None
    n = len(missing)
    return (f"Check: the day chart shows {n} {_plural(n, 'company', 'companies')} needing your input that this list "
            f"does not: {', '.join(sorted(missing.values(), key=str.lower))}")


def run(target, settings, hs, instantly, accounts_api=None, date=None, preview=False, log=print, smtp=None,
        log_data=None, charts=True, draw=None, emails_api=None, to=None, subject_prefix=""):
    """to: other recipients (20 Nov 2026: the Sankey button's Sample box sends this email to Amodh only, with
    subject_prefix "SAMPLE: ")."""
    cfg = dict(DEFAULTS, **(settings.get("daily_report") or {}))
    date = date or yesterday()
    problem = key_problem = None
    shown, key = [], None
    try:
        check_target(hs, target)
    except HubSpotError as err:
        problem = f"HubSpot could not be read ({str(err)[:200]})"
    if problem is None:
        if charts:
            try:
                shown = charts_for(hs, settings, date, log, draw, log_data=log_data)
            except Exception as err:
                problem = f"the figures could not be read from HubSpot ({str(err)[:200]})"
                log(f"The Sankey charts could not be produced: {err}")
        if problem is None:
            try:
                key = key_numbers(hs, instantly, settings, date, cfg, accounts_api, log_data, emails_api=emails_api)
            except (HubSpotError, InstantlyError, KeyError, OSError) as err:
                key_problem = str(err)[:200]
                log(f"The key numbers could not be read: {err}")
            if key and shown:
                key["check"] = sync_check(shown[0][0], key)
                if key["check"]:
                    log(key["check"])
    subject, text, body, images = compose(date, shown, key, problem, key_problem)
    subject = subject_prefix + subject
    step_summary(f"## Daily summary email\n\n**Subject:** {subject}\n\n```\n{text}```\n")
    log(f"Subject: {subject}\n\n{text}")
    if preview:
        log("Preview only: nothing was sent.")
        return {"subject": subject, "text": text, "html": body, "sent": False}
    to = to if to is not None else recipients()
    password = os.environ.get("DAILY_REPORT_APP_PASSWORD", "")
    if not to or not password:
        raise PipelineError("The daily summary was not sent: add the GitHub secrets DAILY_REPORT_TO (the addresses) "
                            "and DAILY_REPORT_APP_PASSWORD (the Google app password of the sending mailbox).")
    send_mail(subject, text, body, cfg, to, password, smtp, images)
    log(f"Sent to {len(to)} {_plural(len(to), 'recipient')} from {cfg['sender']}.")
    return {"subject": subject, "text": text, "html": body, "sent": True}


def main(argv=None):
    ap = argparse.ArgumentParser(description="The daily summary email")
    ap.add_argument("--target", default="test", choices=["test", "live"])
    ap.add_argument("--preview", action="store_true", help="show the email, send nothing")
    ap.add_argument("--day", default="", help="the UK date to report on (default: yesterday)")
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
        accounts_key = os.environ.get("INSTANTLY_ACCOUNTS_KEY")
        emails_key = os.environ.get("INSTANTLY_EMAILS_KEY")  # 20 Nov 2026: which account each bounce came from
        run(args.target, settings, HubSpot(), Instantly(),
            accounts_api=Instantly(api_key=accounts_key) if accounts_key else None,
            date=args.day or None, preview=args.preview,
            emails_api=Instantly(api_key=emails_key) if emails_key else None)
    except (PipelineError, HubSpotError, InstantlyError, smtplib.SMTPException, OSError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
