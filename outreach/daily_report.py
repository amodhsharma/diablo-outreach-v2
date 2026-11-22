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
       Delivery: undelivered (with the bounce rate; Instantly pauses at 5%; the "By sending account" and "At" lines
         under it were dropped on 22 Nov 2026, Ariel), asked not to be emailed, automatic replies
         (data/daily_log.json, written by button 4)
       Sending, Delivery and Campaigns are each a proper table with lines between rows and columns (22 Nov 2026)
       Campaigns: a table of this month's campaigns, laid out for a desktop screen (22 Nov 2026, Ariel): Campaign,
         Status with its coloured dot (short: Running, Running brake on, Paused: Bounce Protect, ...), Bounce rate
         (3%), the benchmark in the heading (green under 3%, amber
         3% to 5%, red over 5%), Your input (green "Resume now", amber "Wait until ...", red "Resume when ready",
         "Connect a sending account" or "Contact Instantly support"; grey "None" when nothing is needed), then the
         emails it sent in the same four columns
       Sending accounts: one green line when all are healthy, a red line naming each problem
       Positive replies to follow up: every company that replied that day tagged Positive, plus Neutral and
         Referral replies marked as such; Negative replies to convert into possible leads: the rest. No cap.
       Referrals handled automatically: only on days the automation handled some (21 Nov 2026, Ariel).
       Initial stages - your input needed or not (at midnight UK): what the chart's Initial stages box holds,
         with the names of everything waiting for a person (GATE1 and GATE2 approval, contacts not yet tagged,
         contacts held because their record could not be put right, companies whose channel is not known). The
         separate "Waiting for you" section was merged into it on 21 Nov 2026 (Ariel). What needs no input is one
         green line, "No input needed (automatic)", without a breakdown (21 Nov 2026, Ariel). From 22 Nov 2026
         (Ariel) the companies stand in round brackets in the same row, and the first row is the companies made
         AUTO-OUTREACH that day from Apollo or no Lead Source (one number, not added to the section's total).
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
    """20 Nov 2026 (Ariel): the approved contacts held because their record is broken, as "Company: why"."""
    from . import address_checks
    held = [(c, address_checks.broken(c)) for c in at.records("contacts", "approved")]
    held = [(c, why) for c, why in held if why]
    if not held:
        return []
    owner_of, companies = tagged_company_of(hs, [str(c["id"]) for c, _ in held], ["name"])
    out = []
    for c, why in held:
        company = companies.get(owner_of.get(str(c["id"]))) or {}
        # 22 Nov 2026: "Company: why", as it now stands inside round brackets with the other companies
        out.append(f"{(company.get('properties') or {}).get('name') or 'A company'}: {why}")
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
        "unknown_channel": sorted(set(unknown.values()), key=str.lower),
        "held": held_records(hs, statuses, at),  # 20 Nov 2026: broken records, not sent
        "at_midnight": not at.live,
    }
    out["initial"] = initial_stages(hs, statuses, out["unknown_channel"], at, unknown)
    out["tagged"] = newly_tagged(hs, date)  # 22 Nov 2026 (Ariel): companies made AUTO-OUTREACH that day
    # 22 Nov 2026 (Ariel): each campaign's emails sent, in the same four columns as Sending
    if out["accounts"]:
        days = sorted(set(month_days) | set(week_days) | {date, before})
        sends = campaign_sends(instantly, emails_api, [r[5] for r in out["accounts"]["campaigns"]], days)
        out["campaign_sent"] = None if sends is None else {
            cid: (per.get(date, 0), per.get(before, 0), sum(per.get(d, 0) for d in week_days),
                  sum(per.get(d, 0) for d in month_days)) for cid, per in sends.items()}
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
        view = view if view is not None else instantly_view(instantly, prefix)
        rates = address_checks.campaign_rates(view, cfg)
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
            bounced, emailed = rates.get(camp["id"], (0, 0))
            rate = f"{bounced / emailed:.1%}" if emailed else ""
            braked = emailed >= least and bounced / emailed >= limit
            # 22 Nov 2026 (Ariel): a short status, and in "Your input" what a person must do, if anything
            if not mailboxes or connected == 0:
                colour, state, advice = BAD, "No sending account", ("Connect a sending account", BAD)
            elif code == -2:
                colour, state = BAD, "Paused: Bounce Protect"
                advice = resume_advice(view, cfg, camp["id"], bounced, emailed)
            elif code == -1:
                colour, state = BAD, "Paused: sending account problem"
                advice = ("None: resumes by itself once the mailboxes are healthy", SAME)
            elif code == -99:
                colour, state, advice = BAD, "Suspended", ("Contact Instantly support", BAD)
            elif code == 2:
                colour, state, advice = BAD, "Paused by hand", ("Resume when ready", BAD)
            elif code == 0:
                colour, state, advice = WARN, "Not started", ("None", SAME)
            elif braked:
                colour, state = WARN, "Running, brake on"
                advice = ("None: new introductions start again by themselves under 3%", SAME)
            elif code in (1, None, 4):
                colour, state, advice = GOOD, "Running", ("None", SAME)
            else:
                colour, state, advice = SAME, CAMPAIGN_STATUS.get(code, "Unknown"), ("None", SAME)
            share = bounced / emailed if emailed else None
            rate_colour = None if share is None else (GOOD if share < limit else WARN if share <= INSTANTLY_PAUSE_RATE else BAD)
            rows.append((colour, camp.get("name") or "A campaign", state, rate, advice, camp["id"], rate_colour))
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


INSTANTLY_PAUSE_RATE = 0.05  # Instantly's Bounce Protect pauses a campaign above 5%


def resume_advice(view, cfg, campaign_id, bounced, emailed, now=None):
    """22 Nov 2026 (Ariel): for a campaign paused by Bounce Protect, ("Resume now", green) once its bounce rate is back
    under Instantly's 5% (every bounced person is already stopped), else ("Wait until Tue 24 Nov, 14:00 UK", amber):
    the moment enough old emails leave the 7-day count, if nothing more is sent."""
    from . import address_checks
    now = now or dt.datetime.now(dt.timezone.utc)
    when = address_checks.clears_at(view, cfg, campaign_id, INSTANTLY_PAUSE_RATE, now)
    if when is not None and when <= now:
        return "Resume now", GOOD
    if when is None:
        return "Wait", WARN
    uk = when.astimezone(DAY_ZONE)  # 22 Nov 2026: the rate itself is in the Bounce rate column
    return f"Wait until {uk.strftime('%a')} {uk.day} {uk.strftime('%b')}, {uk.strftime('%H:00')} UK", WARN


def campaign_sends(instantly, emails_api, campaign_ids, dates):
    """22 Nov 2026 (Ariel): {campaign id: {UK date: emails sent}} (introductions and reminders together) for the
    dates given, from Instantly's list of sent emails (each has its campaign and time, so the days run midnight to
    midnight UK); Instantly's daily totals per campaign when that list cannot be read; None when neither can."""
    if not campaign_ids or not dates:
        return {}
    ids, dates = {str(c) for c in campaign_ids}, set(dates)
    out = {cid: {} for cid in ids}
    emails = None
    if emails_api is not None:
        try:
            emails = emails_api.emails_since(window(min(dates))[0].isoformat(), max_pages=300)
        except Exception:
            emails = None
    if emails is not None:
        for mail in emails:
            cid = str(mail.get("campaign_id") or "")
            when = mail.get("timestamp_email") or mail.get("timestamp_created")
            if mail.get("ue_type") != 1 or cid not in ids or not when:
                continue
            day = daily_log.uk_day(when)
            if day in dates:
                out[cid][day] = out[cid].get(day, 0) + 1
        return out
    try:  # Instantly's own daily totals (UTC days: the same as UK days in winter, an hour off in summer)
        for cid in ids:
            data = instantly.request("GET", "/campaigns/analytics/daily",
                                     params={"campaign_id": cid, "start_date": min(dates), "end_date": max(dates)})
            rows = data if isinstance(data, list) else (data or {}).get("items") or (data or {}).get("data") or []
            for row in rows:
                day = str(row.get("date") or "")[:10]
                if day in dates:
                    out[cid][day] = out[cid].get(day, 0) + int(row.get("sent") or 0)
        return out
    except Exception:
        return None


def newly_tagged(hs, date):
    """22 Nov 2026 (Ariel): the companies whose Lead Source became AUTO-OUTREACH on that UK day, from Apollo or from
    no value at all, by name; companies research creates (AUTO-OUTREACH from the start) do not count. None when
    HubSpot's history cannot be read."""
    from .next_in_line import parse_time
    from .schema import TAG, TAG_PROPERTY
    start, end = window(date)
    try:
        rows = hs.tagged_search("companies", _between("hs_lastmodifieddate", start, end)[:1], ["name"],
                                max_results=10000)
        past = hs.history("companies", [r["id"] for r in rows], TAG_PROPERTY, ["name", "createdate"]) if rows else {}
    except Exception:
        return None
    names = []
    for props, history in past.values():
        for i, (value, stamp) in enumerate(history):
            when = parse_time(stamp)
            if value != TAG or not when or not start <= when < end:
                continue
            before = history[i + 1][0] if i + 1 < len(history) else None
            if str(before or "").strip().lower() not in ("", "apollo"):
                break
            created = parse_time(props.get("createdate"))
            if before is None and (not created or when - created < dt.timedelta(minutes=10)):
                break  # created as AUTO-OUTREACH (research), not tagged later
            names.append(props.get("name") or "A company")
            break
    return sorted(names, key=str.lower)


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
OWN_TABLES = ("Sending", "Delivery", "Campaigns")  # 22 Nov 2026 (Ariel): each its own table in the email
# 22 Nov 2026 (Ariel): the label saying when to unpause a campaign: green resume now, amber wait, grey nothing to
# do, red needs a person
PILLS = {"#0F6E56": ("#EAF3DE", "#27500A"), "#BA7517": ("#FAEEDA", "#854F0B"), "#888780": ("#F1EFE8", "#444441"),
         "#C0392B": ("#FCEBEB", "#A32D2D")}
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
        # 22 Nov 2026 (Ariel): a row of the Sending table, its words in the first column
        sending_.append(("row", f"Instantly uploads used: {used:,} of {allowed:,} ({used / allowed:.0%})", "", "",
                         None, None, "", BAD if used >= 0.9 * allowed else None, ""))
    else:
        sending_.append(("row", "Instantly uploads used: Instantly could not be read this morning", "", "", None, None,
                         "", SAME, ""))
    day_sent, month_sent = k["sent_total"]
    delivery = [row("Undelivered (bounced; Instantly pauses at 5%)", k["bounced"], False,
                    _rate(k["bounced"][0], day_sent), _rate(k["bounced"][2], month_sent), key="bounced",
                    week_text=_rate(weekly["bounced"], weekly.get("sent")) if "bounced" in weekly else None),
                # 22 Nov 2026 (Ariel): the "By sending account" and "At" lines are no longer shown (bounces are
                # forwarded and handled; asked about in the chat when needed)
                row("Asked not to be emailed", k["opted_out"], False, key="opted_out"),
                row("Automatic replies (out of office)", k["auto"], None, key="auto")]
    h = k.get("accounts")
    if h is None:
        campaigns = accounts = [("line", "Instantly could not be read this time", SAME)]
    else:
        sent = k.get("campaign_sent")
        # 22 Nov 2026 (Ariel): a table: Campaign | Status | Bounce rate (3%) | Your input | the four columns
        campaigns = [("campaign_head",)] if h["campaigns"] else []
        for colour, name, state, rate, *more in h["campaigns"]:
            advice, cid, rate_colour = (more + [None, None, None])[:3]
            if "campaign_sent" not in k:
                numbers = None
            elif sent is None:
                numbers = ("-", "-", None, None, "-", "-")
            else:
                day, before, week, month = sent.get(str(cid)) or (0, 0, 0, 0)
                numbers = (_n(day), _n(before), *_arrow(day, before, True), _n(week), _n(month))
            campaigns.append(("campaign", colour, name, state, rate, rate_colour, advice, numbers))
        campaigns = campaigns or [("line", "No campaign this month yet", SAME)]
        if "campaign_sent" in k and sent is None:
            campaigns.append(("line", "Emails sent per campaign: Instantly could not be read this time", SAME))
        if any(c[4] for c in campaigns if c[0] == "campaign"):
            campaigns.append(("line", "Bounce rate = bounces over each campaign's last 200 emails of the last 7 days "
                                      "(green under 3%; amber 3% to 5%, our brake is on; red over 5%, Instantly pauses)",
                              SAME))
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
        if k.get("tagged"):  # 22 Nov 2026 (Ariel): one number and the names; not added to the heading's total
            rows.append(("row", "Companies now AUTO-OUTREACH (from Apollo or no Lead Source)", _n(len(k["tagged"])),
                         "", None, None, "", None, "", ", ".join(k["tagged"])))
        rows.append(("row", "Your input needed", _n(need), "", None, None, ""))
        for label, n, who in k["initial"]["input"]:
            if n:  # 21 Nov 2026 (Ariel): a line with 0 is left out
                text, detail = shown.get(label, (label, None))
                # 22 Nov 2026 (Ariel): the companies in round brackets, comma separated, in the same row
                rows.append(("row", "  " + text, _n(n), "", None, None, "", None, "", ", ".join(detail or who)))
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
    columns = f"{'':{width + 2}}{'Yesterday':<16}{'Day before':<16}{'Week so far':<16}Month so far"
    out, current = [title], None
    for heading, items in blocks:
        text, tags, count = _heading(heading)
        group = text if text in OWN_TABLES else "rest"  # 22 Nov 2026 (Ariel): their own headings, as in the HTML
        if group != current:
            if group in OWN_TABLES:  # 22 Nov 2026 (Ariel): the column headings over the three tables only
                out.append(columns)
            current = group
        label = "".join(f"[{t}] " for t in tags) + text
        out.append(f"{label:<{width + 1}} {count}" if count is not None else label)
        for item in items:
            if item[0] == "row":
                _, label, day, before, symbol, _good, month = item[:7]
                week = item[8] if len(item) > 8 else ""
                names = f"  ({item[9]})" if len(item) > 9 and item[9] else ""
                out.append(f"  {label:<{width}}{day:<16}{(before + (' ' + symbol if symbol else '')):<16}{week:<16}{month}"
                           .rstrip() + names)
            elif item[0] == "campaign_head":
                out.append("  Campaign | Status | Bounce rate (3%) | Your input")
            elif item[0] == "campaign":
                _, colour, name, state, rate, _rate_colour, advice, numbers = item
                mark = {GOOD: "OK", BAD: "!!", WARN: "!"}.get(colour, "-")
                out.append(f"  {name} | {mark} {state} | {rate or '-'} | {advice[0] if advice else 'None'}")
                if numbers:
                    day, before, symbol, _good, week, month = numbers
                    out.append(f"  {'     Emails sent':<{width}}{day:<16}{(before + (' ' + symbol if symbol else '')):<16}"
                               f"{week:<16}{month}".rstrip())
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
    """22 Nov 2026 (Ariel): laid out for a desktop screen. Sending, Delivery and Campaigns are each a proper table of
    their own (_own_table); the other sections share one table, as before."""
    e = html.escape
    title, blocks = key_rows(k)
    cell = 'style="padding:2px 10px;text-align:right;white-space:nowrap"'
    parts = [f'<p style="margin:24px 0 6px;font-size:16px"><b>{e(title)}</b></p>']

    def open_table(left):
        # 22 Nov 2026 (Ariel): no Yesterday, Day before, Week so far, Month so far headings over the other sections
        first = f'<td colspan="{left}"></td>' if left > 1 else '<td style="min-width:380px"></td>'
        return ('<table style="border-collapse:collapse;font-size:14px;margin:0 0 6px"><tr>' + first
                + f"<td {cell}></td>" * 4 + "</tr>")
    current = None

    def numbers_html(day, before, symbol, good, week, month, tint=""):
        tone = SAME if good is None else (GOOD if good else BAD)
        arrow = f' <span style="color:{tone};font-weight:bold">{symbol}</span>' if symbol else ""
        return (f'<td {cell}><b style="{tint}">{e(day)}</b></td><td {cell}>{e(before)}{arrow}</td>'
                f"<td {cell}>{e(week)}</td><td {cell}>{e(month)}</td>")
    for heading, items in blocks:
        text, tags, count = _heading(heading)
        tag_html = "".join(f'<span style="background:{TAGS[t][0]};color:{TAGS[t][1]};padding:1px 8px;border-radius:6px;'
                           f'font-weight:normal;font-size:12px;margin-right:6px">{e(t)}</span>' for t in tags)
        group = text if text in OWN_TABLES else "rest"
        if group in OWN_TABLES:  # 22 Nov 2026 (Ariel): a proper table, with lines between rows and columns
            parts.append(("</table>" if current else "") + _own_table(text, tag_html, count, items))
            current = None
            continue
        left, wide, full = 1, "", 5
        if group != current:
            parts.append(("</table>" if current else "") + open_table(left))
            current = group
        if count is None:
            parts.append(f'<tr><td colspan="{full}" style="padding:10px 0 2px">{tag_html}<b>{e(text)}</b></td></tr>')
        else:
            parts.append(f'<tr><td {wide} style="padding:10px 0 2px">{tag_html}<b>{e(text)}</b></td>'
                         f'<td {cell}><b>{count}</b></td><td></td><td></td><td></td></tr>')
        for item in items:
            if item[0] == "health":
                _, colour, name, state, rate = item
                parts.append(f'<tr><td colspan="{full}" style="padding:2px 10px 2px 14px"><span style="color:{colour}">&#9679;</span> '
                             f'{e(name)}' + (f': <span style="color:{colour if colour != GOOD else "inherit"}">{e(state)}</span>'
                                             if state else "") + (f' <span style="color:{SAME}">({e(rate)})</span>'
                                                                  if rate else "") + "</td></tr>")
                continue
            if item[0] == "table":
                parts.append(f'<tr><td colspan="{full}" style="padding:2px 10px 6px 14px">{_table_html(item[1], item[2])}</td></tr>')
                continue
            if item[0] == "row":
                _, label, day, before, symbol, good, month = item[:7]
                indent = 28 if label.startswith("  ") else 14
                tint = f"color:{item[7]};" if len(item) > 7 and item[7] else ""  # 21 Nov 2026: own colour
                week = item[8] if len(item) > 8 else ""
                names = (f' <span style="color:{SAME};font-size:12px;font-weight:normal">({e(item[9])})</span>'
                         if len(item) > 9 and item[9] else "")  # 22 Nov 2026 (Ariel): the companies, same row
                parts.append(f'<tr><td {wide} style="padding:2px 10px 2px {indent}px;{tint}">{e(label.strip())}{names}</td>'
                             + numbers_html(day, before, symbol, good, week, month, tint) + "</tr>")
            elif item[0] == "line":
                dot = f'<span style="color:{item[2]}">&#9679;</span> ' if item[2] in (GOOD, BAD) else ""
                style = f"color:{item[2]};" if item[2] else ""
                parts.append(f'<tr><td colspan="{full}" style="padding:2px 10px 2px 14px;{style}">{dot}{e(item[1])}</td></tr>')
            else:
                parts.append(f'<tr><td colspan="{full}" style="padding:1px 10px 1px 28px">{e(item[1])}</td></tr>')
    return "".join(parts) + ("</table>" if current else "")


def _own_table(text, tag_html, count, items):
    """22 Nov 2026 (Ariel): Sending, Delivery or Campaigns as a proper table: the heading above it, a grey header row
    (Campaigns: Campaign, Status, Bounce rate (3%), Your input; the others: the row's topic), then Yesterday, Day
    before, Week so far and Month so far, with lines between every row and column. Notes go under the table."""
    e = html.escape
    line = "border:1px solid #d9d9d9;padding:4px 10px"
    words, num = f'style="{line};vertical-align:top"', f'style="{line};text-align:right;white-space:nowrap;vertical-align:top"'
    head = f'style="{line};background:#f5f5f5;color:#5f5e5a;font-size:12px;white-space:nowrap;text-align:left"'
    campaigns = text == "Campaigns"
    firsts = ("Campaign", "Status", "Bounce rate (3%)", "Your input") if campaigns else ("",)
    total = f' <b>{count}</b>' if count is not None else ""
    out = [f'<p style="margin:16px 0 4px">{tag_html}<b>{e(text)}</b>{total}</p>',
           '<table style="border-collapse:collapse;font-size:14px;margin:0 0 4px">',
           "<tr>" + "".join(f"<th {head}>{h}</th>" for h in firsts)
           + "".join(f"<th {head}>{h}</th>" for h in ("Yesterday", "Day before", "Week so far", "Month so far")) + "</tr>"]
    notes = []

    def numbers(day, before, symbol, good, week, month, tint=""):
        tone = SAME if good is None else (GOOD if good else BAD)
        arrow = f' <span style="color:{tone};font-weight:bold">{symbol}</span>' if symbol else ""
        return (f'<td {num}><b style="{tint}">{e(day)}</b></td><td {num}>{e(before)}{arrow}</td>'
                f"<td {num}>{e(week)}</td><td {num}>{e(month)}</td>")
    for item in items:
        if item[0] == "campaign":
            _, colour, name, state, rate, rate_colour, advice, nums = item
            if advice and advice[1] != SAME:
                bg, fg = PILLS.get(advice[1], PILLS[SAME])
                said = (f'<span style="background:{bg};color:{fg};padding:1px 8px;border-radius:6px;font-size:12px;'
                        f'font-weight:bold;white-space:nowrap">{e(advice[0])}</span>')
            else:
                said = f'<span style="color:{SAME}">{e(advice[0])}</span>' if advice else ""
            status = (f'<span style="white-space:nowrap"><span style="color:{colour}">&#9679;</span> '
                      f'<span style="color:{colour if colour != GOOD else "inherit"}">{e(state)}</span></span>')
            out.append(f"<tr><td {words}>{e(name)}</td><td {words}>{status}</td>"
                       f'<td {words}><span style="color:{rate_colour or "inherit"};font-weight:bold">{e(rate or "-")}</span></td>'
                       f"<td {words}>{said}</td>" + (numbers(*nums) if nums else f"<td {num}></td>" * 4) + "</tr>")
        elif item[0] == "row":
            _, label, day, before, symbol, good, month = item[:7]
            tint = f"color:{item[7]};" if len(item) > 7 and item[7] else ""
            week = item[8] if len(item) > 8 else ""
            out.append(f'<tr><td {words[:-1]};min-width:360px;{tint}">{e(label.strip())}</td>'
                       + numbers(day, before, symbol, good, week, month, tint) + "</tr>")
        elif item[0] == "line":
            notes.append(f'<p style="margin:0 0 2px;font-size:12px;color:{item[2] or SAME}">{e(item[1])}</p>')
    return "".join(out) + "</table>" + "".join(notes)


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
