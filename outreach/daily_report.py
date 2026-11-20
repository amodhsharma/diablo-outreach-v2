"""The daily summary email (agreed 27 Oct 2026, Ariel; its content since 20 Nov 2026).

Every morning at 10 AM UK time (cron-job.org starts the button "R - Daily summary email") one email goes to
Amodh, Rafi and Ariel (the GitHub secret DAILY_REPORT_TO), from admin@diablosnosugar.com (a mailbox that sends no
campaigns) through Google's own mail server. It reports the UK day before, midnight to midnight UK time. HubSpot
and Instantly are only read; nothing is changed anywhere. The old written summary is gone (20 Nov 2026, Ariel).

The email (20 Nov 2026, Ariel):
  1. The three Sankey charts (flow_charts.py): the UK day, the week so far and the month so far. A chart that
     cannot be drawn is written out instead, with exactly its words, numbers, %, arrows and notes. When HubSpot
     cannot be read at all, one line says the charts could not be produced, and why.
  2. "Key numbers", in three columns (Yesterday, Day before with an arrow as on the day chart, Month so far):
       Sending: introductions sent, reminders sent (button 4's memory), Instantly uploads used of the plan's
         allowance (daily_report.instantly_allowance in settings). The aim of 240 introductions a day is not shown.
       Delivery: undelivered (with the bounce rate; Instantly pauses at 5%; under it, which sending account each
         bounce came from and at which company), asked not to be emailed, automatic replies (data/daily_log.json,
         written by button 4)
       Sending accounts: one green line when all are healthy, a red line naming each problem
       Positive replies to follow up: every company that replied that day tagged Positive, plus Neutral and
         Referral replies marked as such; Negative replies to convert into possible leads: the rest. No cap.
       Waiting for you: companies waiting for GATE1 approval, introductions waiting for GATE2 approval, and
         Companies where nobody could be found (need sales people input), with their names; and, when there are
         any, the companies whose channel is not known (nobody is emailed until it is set; outreach/channels.py).

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
    day)], "companies": [(company, country)]}, or None when it could not be read."""
    from .countries import uniform
    if not contact_ids:
        return {"accounts": [], "companies": []}
    try:
        records = hs.tagged_read("contacts", [str(c) for c in contact_ids], ["email"])
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
    names = {}
    for cid in contact_ids:
        company = companies.get(owner_of.get(str(cid)))
        if company:
            p = company.get("properties") or {}
            names[str(company["id"])] = (p.get("name") or "A company", uniform(p.get("country")) or "country not known")
    return {"accounts": sorted(((box, n, sent.get(box, 0)) for box, n in bounced.items()), key=lambda x: (-x[1], x[0])),
            "companies": sorted(names.values(), key=lambda x: x[0].lower())}


def unknown_channels(hs, statuses, notes=None):
    """20 Nov 2026 (Ariel, HARD RULE): the open companies whose channel is not known, by name: nobody there is
    emailed until it is set (outreach/channels.py)."""
    from . import channels
    from .common import load_company_notes
    notes = load_company_notes() if notes is None else notes
    out = set()
    for stage in ("approved", "located", "no_response"):
        if not statuses.has("companies", stage):
            continue
        for c in hs.tagged_search("companies", [statuses.filter("companies", stage)],
                                  ["name", "domain", "industry_type"], max_results=5000):
            if channels.verdict(c.get("properties") or {}, notes) is None:
                out.add((c.get("properties") or {}).get("name") or "A company")
    return sorted(out, key=str.lower)


def key_numbers(hs, instantly, settings, date, cfg, accounts_api=None, log_data=None, statuses=None, emails_api=None):
    """Everything the "Key numbers" section shows (agreed 20 Nov 2026, Ariel), for the UK day `date`."""
    before = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
    month_first = date[:8] + "01"
    statuses = statuses or LeadStatus(hs)
    data = daily_log.load() if log_data is None else log_data
    month_days = list(_days(month_first, date))
    sent = sending(instantly, settings, sorted(set(month_days) | {before}))
    month = daily_log.month_counts(data, month_first, date, uk=True)
    today, previous = daily_log.day(data, date, uk=True), daily_log.day(data, before, uk=True)
    reminders_known = [sent[d]["reminders"] for d in month_days if sent[d]["reminders"] is not None]
    follow, negative = replies(hs, today, date)
    return {
        "date": date, "before": before,
        "intros": (sent[date]["intros"], sent[before]["intros"], sum(sent[d]["intros"] for d in month_days)),
        "reminders": (sent[date]["reminders"], sent[before]["reminders"], sum(reminders_known) if reminders_known else None),
        "sent_total": (sum(x or 0 for x in (sent[date]["intros"], sent[date]["reminders"])),
                       sum(sent[d]["intros"] + (sent[d]["reminders"] or 0) for d in month_days)),
        "uploads": uploads(instantly, cfg),
        "bounced": (len(today["bounced"]), len(previous["bounced"]), month["bounced"]),
        "opted_out": (len(today["opted_out"]), len(previous["opted_out"]), month["opted_out"]),
        "auto": (len(today["auto"]), len(previous["auto"]), month["auto"]),
        "accounts": health(instantly, settings, accounts_api),
        "follow": follow, "negative": negative,
        "gate1": hs.tagged_count("companies", [statuses.filter("companies", "found")])
        if statuses.has("companies", "found") else 0,
        "gate2": hs.tagged_count("contacts", [statuses.filter("contacts", "copy_ready")])
        if statuses.has("contacts", "copy_ready") else 0,
        "nowhere": nobody_found(hs, statuses, date),
        "bounces": bounce_detail(hs, instantly, settings, today["bounced"], date, emails_api),
        "unknown_channel": unknown_channels(hs, statuses),
    }


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


def _plural(n, one, many=None):
    return one if n == 1 else (many or one + "s")


GOOD, BAD, SAME = "#0F6E56", "#C0392B", "#888780"


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
        out.append(("line", "At: " + ", ".join(f"{name} ({country})" for name, country in detail["companies"]), None))
    return out


def key_rows(k):
    """(title, [(heading, [item])]) for the "Key numbers" section. item: ("row", label, day, before, arrow, good,
    month), ("line", text, colour) or ("name", text)."""
    def row(label, values, rise_is_good, day_text=None, month_text=None):
        day, before, month = values
        symbol, good = _arrow(day, before, rise_is_good)
        return ("row", label, day_text or _n(day), _n(before), symbol, good, month_text or _n(month))

    sending_ = [row("Introductions sent", k["intros"], True), row("Reminders sent", k["reminders"], True)]
    if k["uploads"]:
        used, allowed = k["uploads"]
        sending_.append(("line", f"Instantly uploads used: {used:,} of {allowed:,} ({used / allowed:.0%})",
                         BAD if used >= 0.9 * allowed else None))
    else:
        sending_.append(("line", "Instantly uploads used: Instantly could not be read this morning", SAME))
    day_sent, month_sent = k["sent_total"]
    delivery = [row("Undelivered (bounced; Instantly pauses at 5%)", k["bounced"], False,
                    _rate(k["bounced"][0], day_sent), _rate(k["bounced"][2], month_sent)),
                *bounce_lines(k.get("bounces"), k["bounced"][0]),
                row("Asked not to be emailed", k["opted_out"], False),
                row("Automatic replies (out of office)", k["auto"], None)]
    if k["accounts"] is None:
        accounts = [("line", "The sending accounts could not be checked this morning", SAME)]
    elif not k["accounts"]:
        accounts = [("line", "All sending accounts healthy", GOOD)]
    else:
        accounts = [("line", issue[:1].upper() + issue[1:], BAD) for issue in k["accounts"]]
    when = dt.date.fromisoformat(k["date"])
    replied = f"replied {when.strftime('%a')} {when.day} {when.strftime('%b')}"

    def names(rows):
        if not rows:
            return [("line", "None", SAME)]
        return [("name", f"{name} ({country}), {replied}" + (f" ({mark})" if mark else "")) for name, country, mark in rows]
    waiting = [("row", "Companies waiting for GATE1 approval", _n(k["gate1"]), "", None, None, ""),
               ("row", "Introductions waiting for GATE2 approval", _n(k["gate2"]), "", None, None, ""),
               ("row", "Companies where nobody could be found (need sales people input)", _n(len(k["nowhere"])), "",
                None, None, "")] + [("name", n) for n in k["nowhere"]]
    if k.get("unknown_channel"):  # 20 Nov 2026 (Ariel, HARD RULE): nobody there is emailed until it is set
        waiting += [("row", "Companies whose channel is not known (nobody is emailed until it is set)",
                     _n(len(k["unknown_channel"])), "", None, None, "")] + [("name", n) for n in k["unknown_channel"]]
    return f"Key numbers - {_long_date(k['date'])}", [
        ("Sending", sending_), ("Delivery", delivery), ("Sending accounts", accounts),
        ("Positive replies to follow up", names(k["follow"])),
        ("Negative replies to convert into possible leads", names(k["negative"])),
        ("Waiting for you", waiting)]


def key_text(k):
    title, blocks = key_rows(k)
    width = max(len(i[1]) for _, items in blocks for i in items if i[0] == "row") + 4
    out = [title, f"{'':{width + 2}}{'Yesterday':<16}{'Day before':<16}Month so far"]
    for heading, items in blocks:
        out.append(heading)
        for item in items:
            if item[0] == "row":
                _, label, day, before, symbol, _good, month = item
                out.append(f"  {label:<{width}}{day:<16}{(before + (' ' + symbol if symbol else '')):<16}{month}".rstrip())
            elif item[0] == "line":
                out.append(f"  {item[1]}")
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
                       for h in ("Yesterday", "Day before", "Month so far")) + "</tr>"]
    for heading, items in blocks:
        parts.append(f'<tr><td colspan="4" style="padding:10px 0 2px"><b>{e(heading)}</b></td></tr>')
        for item in items:
            if item[0] == "row":
                _, label, day, before, symbol, good, month = item
                colour = SAME if good is None else (GOOD if good else BAD)
                arrow = f' <span style="color:{colour};font-weight:bold">{symbol}</span>' if symbol else ""
                parts.append(f'<tr><td style="padding:2px 10px 2px 14px">{e(label)}</td><td {cell}><b>{e(day)}</b></td>'
                             f"<td {cell}>{e(before)}{arrow}</td><td {cell}>{e(month)}</td></tr>")
            elif item[0] == "line":
                dot = f'<span style="color:{item[2]}">&#9679;</span> ' if item[2] in (GOOD, BAD) else ""
                style = f"color:{item[2]};" if item[2] else ""
                parts.append(f'<tr><td colspan="4" style="padding:2px 10px 2px 14px;{style}">{dot}{e(item[1])}</td></tr>')
            else:
                parts.append(f'<tr><td colspan="4" style="padding:1px 10px 1px 28px">{e(item[1])}</td></tr>')
    return "".join(parts) + "</table>"


def chart_html(spec):
    """A chart that could not be drawn, written out (flow_charts.chart_lines), with the arrows coloured as on the chart."""
    from .flow_charts import chart_lines
    e = html.escape
    parts = [f'<p style="margin:18px 0 2px"><b>{e(spec.get("title", ""))}</b><br>'
             f'<span style="color:{SAME}">{e(spec.get("subtitle", ""))}</span></p><div>']
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


def charts_for(hs, settings, date, log=print, draw=None, out_dir="flow_charts"):
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
    drawn, specs = flow_charts.draw_all(hs, settings, dt.date.fromisoformat(date), out_dir, log, draw=safe, zone=DAY_ZONE)
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


def run(target, settings, hs, instantly, accounts_api=None, date=None, preview=False, log=print, smtp=None,
        log_data=None, charts=True, draw=None, emails_api=None):
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
                shown = charts_for(hs, settings, date, log, draw)
            except Exception as err:
                problem = f"the figures could not be read from HubSpot ({str(err)[:200]})"
                log(f"The Sankey charts could not be produced: {err}")
        if problem is None:
            try:
                key = key_numbers(hs, instantly, settings, date, cfg, accounts_api, log_data, emails_api=emails_api)
            except (HubSpotError, InstantlyError, KeyError, OSError) as err:
                key_problem = str(err)[:200]
                log(f"The key numbers could not be read: {err}")
    subject, text, body, images = compose(date, shown, key, problem, key_problem)
    step_summary(f"## Daily summary email\n\n**Subject:** {subject}\n\n```\n{text}```\n")
    log(f"Subject: {subject}\n\n{text}")
    if preview:
        log("Preview only: nothing was sent.")
        return {"subject": subject, "text": text, "html": body, "sent": False}
    to = recipients()
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
