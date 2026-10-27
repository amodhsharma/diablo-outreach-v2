"""The daily summary email (agreed 27 Oct 2026, Ariel).

Every morning at 9 AM India time a short summary of the day before goes to three colleagues, from
admin@diablosnosugar.com (a mailbox that sends no campaigns) through Google's own mail server. It is
written for executives: no internal words such as gates or buttons. HubSpot and Instantly are only
read; nothing is changed anywhere.

The figures, for the India day before:
  Prospecting (HubSpot)
    - new prospective partners identified, by country (AUTO-OUTREACH companies created that day)
    - prospects approved for contact research (companies whose Lead Status became GATE1 that day)
    - companies where named contacts were found / only a general inbox (contacts added that day)
    - companies where no contact was found, with their names (Missing Info with "No contact found
      anywhere" that day)
    - new prospects awaiting approval for contact research (companies on New now)
    - introductions written, awaiting approval to send (contacts on "New, Personal line filled" now)
    - companies marked unqualified after no response (Lead Status became "Contacted, but no
      response, unqualified" that day)
  Outreach (Instantly)
    - introductory emails sent (Instantly's send time), to named contacts and to company inboxes
    - responses (positive, negative, neutral), positive ones by company, automatic replies,
      undelivered emails and opt-outs (data/daily_log.json, written by button 4)
    - the sending accounts: one line, naming any mailbox or campaign that needs attention
  Month to date: prospects identified, introductory emails sent, responses (of which positive)

The recipients (GitHub secret DAILY_REPORT_TO, separated by commas) and the mailbox's Google app
password (DAILY_REPORT_APP_PASSWORD) are never written in the repository.
Usage:
    python -m outreach.daily_report --target live [--preview] [--day 2026-10-26]
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
from .next_in_line import instantly_view, is_company_inbox, tagged_company_of
from .schema import CONTACT_SOURCE, LEAD_STATUS, SOURCE_WEBSITE, STOP_REASON
from .stages import LeadStatus

INDIA = daily_log.INDIA
DEFAULTS = {"sender": "admin@diablosnosugar.com", "sender_name": "Diablo Partner Outreach",
            "smtp_host": "smtp.gmail.com", "smtp_port": 587}


def yesterday(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now.astimezone(INDIA).date() - dt.timedelta(days=1)).isoformat()


def window(first, last=None):
    """(start, end) in UTC of the India dates first to last (inclusive)."""
    start = dt.datetime.fromisoformat(first).replace(tzinfo=INDIA)
    end = dt.datetime.fromisoformat(last or first).replace(tzinfo=INDIA) + dt.timedelta(days=1)
    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def _ms(when):
    return str(int(when.timestamp() * 1000))


def _between(prop, start, end):
    return [{"propertyName": prop, "operator": "GTE", "value": _ms(start)},
            {"propertyName": prop, "operator": "LT", "value": _ms(end)}]


def _entered(past, value, start, end):
    """True when the field became this value between start and end (past: newest first)."""
    from .next_in_line import parse_time
    for i, (v, t) in enumerate(past):
        when = parse_time(t)
        if v == value and when and start <= when < end:
            before = past[i + 1][0] if i + 1 < len(past) else None
            if before != value:
                return True
    return False


def _value(statuses, obj, stage):
    return statuses.props(obj, stage)[LEAD_STATUS] if statuses.has(obj, stage) else None


def prospecting(hs, statuses, date, month_first):
    start, end = window(date)
    created = hs.tagged_search("companies", _between("createdate", start, end), ["name", "country"], max_results=5000)
    countries = Counter(((r.get("properties") or {}).get("country") or "other countries").strip() for r in created)
    changed = hs.tagged_search("companies", _between("hs_lastmodifieddate", start, end)[:1], ["name"],
                               max_results=10000)
    past = hs.history("companies", [r["id"] for r in changed], LEAD_STATUS, ["name", STOP_REASON]) if changed else {}
    approved, no_response, missing = (_value(statuses, "companies", s) for s in ("approved", "no_response", "missing_info"))
    out = {"new": len(created), "countries": countries.most_common()}
    out["approved"] = sum(1 for _, h in past.values() if approved and _entered(h, approved, start, end))
    out["no_response"] = sum(1 for _, h in past.values() if no_response and _entered(h, no_response, start, end))
    out["nowhere"] = sorted(((p.get("name") or "A company") for p, h in past.values()
                             if missing and _entered(h, missing, start, end)
                             and str(p.get(STOP_REASON) or "").startswith(NOWHERE)), key=str.lower)
    contacts = hs.tagged_search("contacts", _between("createdate", start, end), ["jobtitle", CONTACT_SOURCE],
                                max_results=5000)
    owner_of, _ = tagged_company_of(hs, [c["id"] for c in contacts], ["name"]) if contacts else ({}, {})
    kinds = {}
    for c in contacts:
        company = owner_of.get(str(c["id"]))
        if not company:
            continue
        inbox = is_company_inbox(c) or (c.get("properties") or {}).get(CONTACT_SOURCE) == SOURCE_WEBSITE
        kinds[company] = kinds.get(company, False) or not inbox  # True: a named person was found
    out["named"] = sum(1 for v in kinds.values() if v)
    out["inbox_only"] = sum(1 for v in kinds.values() if not v)
    out["awaiting_research"] = hs.tagged_count("companies", [statuses.filter("companies", "found")])
    out["awaiting_send"] = hs.tagged_count("contacts", [statuses.filter("contacts", "copy_ready")])
    first_start, _ = window(month_first)
    out["month_new"] = hs.tagged_count("companies", _between("createdate", first_start, end))
    return out


def _company_names(hs, contact_ids):
    if not contact_ids:
        return []
    owner_of, companies = tagged_company_of(hs, contact_ids, ["name"])
    names = {(companies.get(owner_of.get(str(c))) or {}).get("properties", {}).get("name") for c in contact_ids}
    return sorted((n for n in names if n), key=str.lower)


def outreach(hs, instantly, settings, date, month_first, log_data=None):
    from .send import INBOX, INBOX_OTHER, kind_of_campaign
    prefix = settings["sync"]["campaign_prefix"]
    names = {c["id"]: c.get("name") for c in instantly.list_campaigns()}
    leads = instantly_view(instantly, prefix)
    sent = {"person": 0, "inbox": 0}
    month_sent = 0
    for lead in leads.values():
        when = lead.get("timestamp_last_contact")
        if not when:
            continue
        day = daily_log.india_day(when)
        if month_first <= day <= date:
            month_sent += 1
        if day == date:
            kind = kind_of_campaign(names.get(lead.get("_campaign_id")), settings["send"])
            sent["inbox" if kind in (INBOX, INBOX_OTHER) else "person"] += 1
    data = daily_log.load() if log_data is None else log_data
    today = daily_log.day(data, date)
    month = daily_log.month_counts(data, month_first, date)
    return {"sent": sent, "day": {k: len(v) for k, v in today.items()},
            "positive_names": _company_names(hs, today["positive"]),
            "month_sent": month_sent,
            "month_responses": month["positive"] + month["negative"] + month["neutral"],
            "month_positive": month["positive"]}


def health(instantly, settings, accounts_api=None):
    """Plain sentences for anything about the sending accounts that needs attention ([] when all is
    well), or None when Instantly could not be read."""
    from .check_instantly import CAMPAIGN_STATUS, diablo_campaigns, mailbox_verdict
    from .send import INBOX, campaign_name, kind_of_campaign
    try:
        current = campaign_name(settings["sync"]["campaign_prefix"])
        campaigns = [c for c in diablo_campaigns(instantly, settings["sync"]["campaign_prefix"])
                     if str(c.get("name") or "").startswith(current)]
        issues, used = [], set()
        for camp in campaigns:
            label = ("the campaign for general company inboxes"
                     if kind_of_campaign(camp.get("name"), settings["send"]) == INBOX else "the campaign for named contacts")
            mailboxes = [m.lower() for m in camp.get("email_list") or []]
            used.update(mailboxes)
            connected = None
            try:
                status = instantly.request("GET", f"/campaigns/{camp['id']}/sending-status")
                connected = (((status or {}).get("diagnostics") or {}).get("accounts_summary") or {}).get("total_connected")
            except (InstantlyError, AttributeError):
                pass
            if not mailboxes or connected == 0:
                issues.append(f"{label} has no sending account connected; please assign one in Instantly")
            elif camp.get("status") not in (1, None):
                waiting = sum(1 for l in instantly.list_leads(camp["id"]) if not l.get("timestamp_last_contact"))
                if waiting:
                    state = CAMPAIGN_STATUS.get(camp.get("status"), "not running").lower()
                    issues.append(f"{label} is {state}, with {waiting} introductions waiting; please start it in Instantly")
        for acc in (accounts_api or instantly).list_accounts():
            email = (acc.get("email") or "").lower()
            if email in used:
                verdict, reasons = mailbox_verdict(acc)
                if verdict != "Ready":
                    reason = (reasons[0] if reasons else verdict).split(":")[0].rstrip(".")
                    issues.append(f"{email} needs attention ({reason.lower()})")
        return issues
    except (InstantlyError, AttributeError, KeyError):
        return None


def _long_date(date):
    d = dt.date.fromisoformat(date)
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B %Y')}"


def _period(first, last):
    a, b = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    return f"{a.day} {b.strftime('%B %Y')}" if a == b else f"{a.day} to {b.day} {b.strftime('%B %Y')}"


def _plural(n, one, many=None):
    return one if n == 1 else (many or one + "s")


def compose(date, p, o, issues, month_first, sender_name):
    """(subject, [(heading or None, [(line, [names])])]) as agreed with Ariel on 27 Oct 2026."""
    sent = o["sent"]["person"] + o["sent"]["inbox"]
    day = o["day"]
    responses = day["positive"] + day["negative"] + day["neutral"]
    countries = ", ".join(f"{c} {n}" for c, n in p["countries"])
    rate = f" (delivery failure rate {day['bounced'] / sent:.1%})" if sent and day["bounced"] else ""
    if issues is None:
        accounts = "Sending accounts: could not be checked this morning"
    elif not issues:
        accounts = "Sending accounts: all healthy"
    else:
        accounts = "Sending accounts: " + "; ".join(issues)
    prospecting = [
        (f"New prospective partners identified: {p['new']}" + (f" ({countries})" if p["new"] else ""), []),
        (f"Prospects approved for contact research: {p['approved']}", []),
        (f"Companies where named contacts were found: {p['named']}", []),
        (f"Companies where only a general inbox was found (from their website): {p['inbox_only']}", []),
        (f"Companies where no contact was found, sales team input required: {len(p['nowhere'])}", p["nowhere"]),
        (f"New prospects awaiting approval for contact research: {p['awaiting_research']}", []),
        (f"Introductions written, awaiting approval to send: {p['awaiting_send']}", []),
        (f"Companies marked unqualified after no response within 7 days: {p['no_response']}", []),
    ]
    out = [
        (f"Introductory emails sent: {sent}" + (f" ({o['sent']['person']} to named contacts, {o['sent']['inbox']} to "
                                                f"general company inboxes)" if sent else ""), []),
        (f"Responses received: {responses}" + (f" ({day['positive']} positive, {day['negative']} negative, "
                                               f"{day['neutral']} neutral)" if responses else ""), []),
        (f"Positive responses requiring follow-up: {day['positive']}", o["positive_names"]),
        (f"Automatic replies, such as out of office: {day['auto']}" + (" (not counted as responses)" if day["auto"] else ""), []),
        (f"Undelivered emails: {day['bounced']}{rate}", []),
        (f"Opt-out requests: {day['opted_out']}", []),
        (accounts, []),
    ]
    month = [
        (f"Prospects identified: {p['month_new']}", []),
        (f"Introductory emails sent: {o['month_sent']}", []),
        (f"Responses received: {o['month_responses']}" + (f" ({o['month_positive']} positive)" if o["month_responses"] else ""), []),
    ]
    subject = f"Partner outreach: daily summary, {_long_date(date)}"
    return subject, [("Prospecting", prospecting), ("Outreach", out),
                     (f"Month to date ({_period(month_first, date)})", month)]


def as_text(date, sections, sender_name):
    lines = ["Good morning,", "", f"Here is the summary of partner outreach for {_long_date(date)}.", ""]
    for heading, items in sections:
        lines.append(heading)
        for line, names in items:
            lines.append(f"- {line}")
            lines += [f"  - {n}" for n in names]
        lines.append("")
    return "\n".join(lines + ["Kind regards,", sender_name, ""])


def as_html(date, sections, sender_name):
    e = html.escape
    parts = ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#222">',
             "<p>Good morning,</p>", f"<p>Here is the summary of partner outreach for {e(_long_date(date))}.</p>"]
    for heading, items in sections:
        parts.append(f'<p style="margin:16px 0 4px"><b>{e(heading)}</b></p><ul style="margin:0;padding-left:20px">')
        for line, names in items:
            sub = "".join(f"<li>{e(n)}</li>" for n in names)
            parts.append(f"<li>{e(line)}" + (f'<ul style="margin:0">{sub}</ul>' if sub else "") + "</li>")
        parts.append("</ul>")
    parts.append(f"<p>Kind regards,<br>{e(sender_name)}</p></div>")
    return "".join(parts)


def recipients(value=None):
    value = os.environ.get("DAILY_REPORT_TO", "") if value is None else value
    return [a.strip() for a in re.split(r"[,;\s]+", value) if "@" in a]


def send_mail(subject, text, html_body, cfg, to, password, smtp=None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{cfg['sender_name']} <{cfg['sender']}>"
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    if smtp is None:
        smtp = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=60)
        smtp.starttls(context=ssl.create_default_context())
    with smtp:
        smtp.login(cfg["sender"], password)
        smtp.send_message(msg)


def run(target, settings, hs, instantly, accounts_api=None, date=None, preview=False, log=print, smtp=None,
        log_data=None):
    check_target(hs, target)
    cfg = dict(DEFAULTS, **(settings.get("daily_report") or {}))
    date = date or yesterday()
    month_first = date[:8] + "01"
    statuses = LeadStatus(hs)
    p = prospecting(hs, statuses, date, month_first)
    o = outreach(hs, instantly, settings, date, month_first, log_data)
    issues = health(instantly, settings, accounts_api)
    subject, sections = compose(date, p, o, issues, month_first, cfg["sender_name"])
    text = as_text(date, sections, cfg["sender_name"])
    step_summary(f"## Daily summary email\n\n**Subject:** {subject}\n\n" + text.replace("\n- ", "\n- "))
    log(f"Subject: {subject}\n\n{text}")
    if preview:
        log("Preview only: nothing was sent.")
        return {"subject": subject, "text": text, "sent": False}
    to = recipients()
    password = os.environ.get("DAILY_REPORT_APP_PASSWORD", "")
    if not to or not password:
        raise PipelineError("The daily summary was not sent: add the GitHub secrets DAILY_REPORT_TO (the addresses) "
                            "and DAILY_REPORT_APP_PASSWORD (the Google app password of the sending mailbox).")
    send_mail(subject, text, as_html(date, sections, cfg["sender_name"]), cfg, to, password, smtp)
    log(f"Sent to {len(to)} {_plural(len(to), 'recipient')} from {cfg['sender']}.")
    return {"subject": subject, "text": text, "sent": True}


def main(argv=None):
    ap = argparse.ArgumentParser(description="The daily summary email")
    ap.add_argument("--target", default="test", choices=["test", "live"])
    ap.add_argument("--preview", action="store_true", help="show the email, send nothing")
    ap.add_argument("--day", default="", help="the India date to report on (default: yesterday)")
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
        accounts_key = os.environ.get("INSTANTLY_ACCOUNTS_KEY")
        run(args.target, settings, HubSpot(), Instantly(),
            accounts_api=Instantly(api_key=accounts_key) if accounts_key else None,
            date=args.day or None, preview=args.preview)
    except (PipelineError, HubSpotError, InstantlyError, smtplib.SMTPException, OSError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
