"""Button 4, step 2: add person 1 of each newly approved company to an Instantly campaign.

Only AUTO-OUTREACH contacts whose Lead Status is GATE2: Approved to send are sent (gate 2), only at
AUTO-OUTREACH companies, and only one person per company at a time, most senior first (see
next_in_line.py). The sync job
moves each company on to its next person by itself. Campaigns are created paused; you
press Start in Instantly for each new campaign.
Usage:
    python -m outreach.send --target test --dry-run
    python -m outreach.send --target test
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from . import bond, timeline
from .common import (
    ROOT, PipelineError, channel_of, check_target, load_company_notes, load_settings, market_matches, run_dir, step_summary,
    write_json,
)
from .hubspot_client import HubSpot, HubSpotError
from .instantly_client import Instantly, InstantlyError
from .instantly_timezones import instantly_timezone
from .next_in_line import (
    COMPANY_PROPS, CONTACT_PROPS, annotate, apply_test_gaps, contacts_by_company, decide, instantly_view,
    follow_up_settings, is_company_inbox, last_campaign, lead_for, tagged_company_of,
)
from .schema import COMPANY_NOTE, PERSONAL_LINE
from .stages import COMPANY_STOPPED, LeadStatus, forward


MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def month_label(day=None):
    """Month and year for campaign names, e.g. OCT2026."""
    day = day or dt.date.today()
    return f"{MONTHS[day.month - 1]}{day.year}"


def campaign_name(prefix, month=None):
    """One campaign per month for every Location and Channel (agreed 8 Oct 2026), e.g.
    "Diablo | OCT2026". Location and Channel stay on each lead and in HubSpot."""
    return f"{prefix} {month or month_label()}"


PERSON, INBOX = "person", "company_inbox"
# Channels outside our usual ones (23 Oct 2026, config/bond_channels.json) had their own campaigns in
# October 2026 ("... | Other channels"). Since 26 Oct 2026 (Ariel) there are only two campaigns a month:
# people, and everything else. Those October campaigns are still recognised so their leads can be
# moved into the two (other_channels.merge); nothing new is ever added to them.
PERSON_OTHER, INBOX_OTHER = "person_other", "company_inbox_other"
KINDS = (PERSON, INBOX, PERSON_OTHER, INBOX_OTHER)


def other_suffix(config=None):
    return " | " + ((config if config is not None else bond.load()).get("campaign_suffix") or "Other channels")


def kind_for(inbox, other=False):
    """The campaign kind for a contact: people go to the month's campaign, everything else (company
    inboxes) to the month's company inbox campaign, whatever the channel (26 Oct 2026, Ariel). `other`
    is kept for the October 2026 "Other channels" campaigns only."""
    if other:
        return INBOX_OTHER if inbox else PERSON_OTHER
    return INBOX if inbox else PERSON


def with_bond(lead, company, notes=None, config=None):
    """The lead with its bond paragraph: the heading and the personal line for a channel outside our
    usual ones, empty for every other channel (26 Oct 2026)."""
    channel = channel_of(company or {}, notes)
    line = lead.get("custom_variables", {}).get("personal_line") if bond.bond_channel(channel, config) else ""
    lead.setdefault("custom_variables", {})[bond.VARIABLE] = bond.paragraph(line, config) if line else ""
    return lead


def is_other_campaign(name):
    """True for an October 2026 "Other channels" campaign (no longer used for new leads)."""
    return str(name or "").endswith(other_suffix())


def bond_ready(settings, kind):
    """True when the first email of this kind of campaign has room for the bond paragraph. Until then
    a contact at a channel outside our usual ones waits, so nobody gets the email without it."""
    paths = settings["send"].get("templates") or {}
    which = "first_email_company_inbox" if kind == INBOX else "first_email"
    path = Path(paths.get(which) or "")
    if not path.name:
        return False
    if not path.is_absolute():
        path = ROOT / path if path.parent != Path(".") else ROOT / "templates" / path
    try:
        template = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return "{{" + bond.VARIABLE + "}}" in template.get("body", "")


def name_for_kind(kind, prefix, s, month=None):
    """This month's campaign for a kind, e.g. "Diablo | OCT2026 | Company inboxes | Other channels"."""
    base = inbox_campaign_name(prefix, s, month) if kind in (INBOX, INBOX_OTHER) else campaign_name(prefix, month)
    return base + (other_suffix() if kind in (PERSON_OTHER, INBOX_OTHER) else "")


def inbox_suffix(s):
    return " | " + ((s.get("company_inbox") or {}).get("campaign_suffix") or "Company inboxes")


def inbox_campaign_name(prefix, s, month=None):
    """Company inboxes (agreed 19 Oct 2026) have their own campaign each month, e.g.
    "Diablo | OCT2026 | Company inboxes", with their own first email and a smaller daily limit."""
    return campaign_name(prefix, month) + inbox_suffix(s)


def kind_of_campaign(name, s):
    name = str(name or "")
    other = name.endswith(other_suffix())
    if other:
        name = name[: -len(other_suffix())]
    return kind_for(name.endswith(inbox_suffix(s)), other)


def schedule_for(market, schedules):
    """Most specific schedule whose name matches the market ("Mumbai, India" uses "India"
    unless a "Mumbai" entry exists); falls back to default."""
    best, best_len = schedules["default"], -1
    for key, value in schedules.items():
        if key != "default" and market_matches(key, market) and len(key) > best_len:
            best, best_len = value, len(key)
    return best


DAY_NUMBERS = {"sun": "0", "mon": "1", "tue": "2", "wed": "3", "thu": "4", "fri": "5", "sat": "6"}


def schedule_days(sched):
    """Instantly's day switches (0 = Sunday). Monday to Friday unless the schedule lists days."""
    days = [str(d).lower()[:3] for d in sched.get("days") or ["mon", "tue", "wed", "thu", "fri"]]
    unknown = [d for d in days if d not in DAY_NUMBERS]
    if unknown:
        raise PipelineError(f"Unknown day(s) in send.schedule: {', '.join(unknown)}; use mon, tue ... sun")
    return {num: name in days for name, num in DAY_NUMBERS.items()}


def short_link(url):
    """A web address as people read it: "https://www.example.com/a" gives "example.com/a"."""
    return re.sub(r"^(https?://)?(www\.)?", "", (url or "").strip(), flags=re.I).rstrip("/")


# Instantly's own placeholder for the first name of the mailbox that sends a campaign email.
SENDING_ACCOUNT_FIRST_NAME = "{{sendingAccountFirstName}}"


def sender_name_for(s, mailbox=None):
    """The name in the signature. Normally the fixed signature.name ("Joshua"). With
    signature.name_from_mailbox switched on (provision added 18 Oct 2026, off until Ariel says),
    it follows the mailbox that sends: the forwards and the reminder use signature.names_by_mailbox
    for that mailbox (falling back to signature.name), and the first email, whose mailbox Instantly
    picks when it sends, uses Instantly's own sending-mailbox first name."""
    sig = s.get("signature") or {}
    fixed = sig.get("name") or ""
    if not sig.get("name_from_mailbox"):
        return fixed
    if mailbox:
        names = {str(k).strip().lower(): v for k, v in (sig.get("names_by_mailbox") or {}).items()}
        return names.get(str(mailbox).strip().lower()) or fixed
    return SENDING_ACCOUNT_FIRST_NAME


def _template(path, s, mailbox=None):
    """A template with the same-for-everyone parts filled in: privacy link, catalogue link and
    the signature. Lines left empty (e.g. no phone number) are dropped."""
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path if path.parent != Path(".") else ROOT / "templates" / path
    template = json.loads(path.read_text(encoding="utf-8"))
    sig = s.get("signature") or {}
    link = (s.get("booking_link") or "").strip()
    real_link = link if link.lower().startswith(("http://", "https://")) else ""  # not the "xxx" placeholder
    fixed = {"privacy_url": s["privacy_url"], "catalogue_link": s.get("catalogue_link") or "",
             "booking_sentence": f" You can also book a time directly here: {real_link}" if real_link else "",
             "booking_link": link,
             # The links written short for template 3 (agreed 15 Oct 2026): the same address
             # without https:// or www., so the text shown matches where the link goes.
             "booking_link_text": short_link(link),
             "catalogue_link_text": short_link(s.get("catalogue_link") or ""),
             "sender_name": sender_name_for(s, mailbox), "sender_title": sig.get("title") or "",
             "sender_website": sig.get("website") or "", "sender_phone": sig.get("phone") or ""}
    body = template["body"]
    for key, value in fixed.items():
        if not str(value).strip():
            body = body.replace("<br/>{{" + key + "}}", "").replace("{{" + key + "}}", "")
        body = body.replace("{{" + key + "}}", str(value))
    return template["subject"], body


def first_email_uses(settings, name):
    """True when the first email's template contains {{name}} (template 3 uses company_note)."""
    return template_uses(settings, "first_email", name)


def template_uses(settings, which, name):
    """True when the template set for `which` (first_email, forward, ...) contains {{name}}."""
    s = settings["send"]
    default = {"first_email": "templates/template_1.json", "forward": "templates/forward.json",
               "reminder": "templates/follow_up.json"}.get(which, "templates/template_1.json")
    path = Path((s.get("templates") or {}).get(which) or default)
    if not path.is_absolute():
        path = ROOT / path if path.parent != Path(".") else ROOT / "templates" / path
    try:
        template = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return "{{" + name + "}}" in template.get("body", "") + template.get("subject", "")


def booking_link_problem(settings):
    """Why the first email cannot go out yet, or "". Template 2 ends with "you can do it from the
    link below" followed by the booking link (agreed 14 Oct 2026), so it must never be sent while
    the link is empty or still the placeholder "xxx"."""
    s = settings["send"]
    path = Path((s.get("templates") or {}).get("first_email") or "templates/template_1.json")
    if not path.is_absolute():
        path = ROOT / path if path.parent != Path(".") else ROOT / "templates" / path
    try:
        body = json.loads(path.read_text(encoding="utf-8")).get("body", "")
    except (OSError, ValueError):
        return ""
    link = (s.get("booking_link") or "").strip()
    if "{{booking_link}}" in body and not link.lower().startswith(("http://", "https://")):
        return ("The booking link is missing: the first email ends with \"you can do it from the link "
                f"below\", but send.booking_link in config/settings.yaml is \"{link or 'empty'}\". "
                "Nothing was sent and no campaign was changed. Put the real booking link there first.")
    return ""


GAP = "<div><br></div>"


def html_paragraphs(body):
    """Instantly shows (and sends) an empty email when the body is bare text with <br/> breaks,
    and its editor shows <p> paragraphs with no space between them. So each paragraph (text
    between blank lines) becomes a <div>, with an empty line (<div><br></div>) between
    paragraphs, the same way Instantly's own editor stores a gap (changed 12 Oct 2026)."""
    parts = [part.strip() for part in body.split("<br/><br/>") if part.strip()]
    return GAP.join(part if part.startswith("<ul") else f"<div>{part}</div>" for part in parts)


def sequence_steps(s, kind=PERSON):
    """First email, plus one reminder for anyone who has not replied (Instantly's `delay` is
    the wait before the NEXT email, so it sits on the first step). kind INBOX: the company inbox
    campaign's first email (templates.first_email_company_inbox)."""
    follow = s.get("follow_up") or {}
    paths = s.get("templates") or {}
    first_path = paths.get("first_email") or "templates/template_1.json"
    if kind == INBOX:
        first_path = paths.get("first_email_company_inbox") or "templates/template_no_info_apollo_1.json"
    elif kind == PERSON_OTHER:
        first_path = paths.get("first_email_other_channels") or "templates/template_5.json"
    elif kind == INBOX_OTHER:
        first_path = paths.get("first_email_company_inbox_other_channels") or "templates/template_no_info_apollo_4.json"
    subject, body = _template(first_path, s)
    first = {"type": "email", "delay": 0, "delay_unit": "days",
             "variants": [{"subject": subject, "body": html_paragraphs(body)}]}
    if not follow.get("enabled"):
        return [first]
    first["delay"] = int(follow.get("delay_days", 7))
    f_subject, f_body = _template(paths.get("follow_up") or "templates/follow_up.json", s)
    # Instantly cannot know which colleague was emailed before, so its own reminder leaves that out.
    f_body = f_body.replace("{{colleague_sentence}}<br/><br/>", "").replace("{{colleague_sentence}}", "")
    second = {"type": "email", "delay": 0, "delay_unit": "days",
              "variants": [{"subject": f_subject, "body": html_paragraphs(f_body)}]}
    return [first, second]


def render(text, lead):
    """Fill a template the way Instantly will, for the preview."""
    values = {"firstName": lead.get("first_name") or "", "lastName": lead.get("last_name") or "",
              "companyName": lead.get("company_name") or "", **lead.get("custom_variables", {})}
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    # The hidden inbox preview line (template 4, 19 Oct 2026) is not part of what the reader sees.
    text = re.sub(r'<div style="display:none[^"]*">.*?</div>', "", text)
    text = text.replace("<ul>", "\n\n").replace("</ul>", "\n\n").replace("<li>", "\u2022 ").replace("</li>", "\n")
    text = text.replace(GAP, "\n\n")
    text = re.sub(r'<div style="border-left[^"]*">(.*?)</div>',  # the signature block, shown with a bar
                  lambda m: "\n" + "\n".join("| " + line for line in m.group(1).split("<br/>")), text)
    text = re.sub(r"<hr[^>]*>", "\n" + "-" * 60 + "\n", text)       # the footer's full-width line
    text = re.sub(r'<a href="([^"]*)"[^>]*>(.*?)</a>',                 # links: text, plus the address if different
                  lambda m: m.group(2) if m.group(2) == m.group(1) else f"{m.group(2)} [{m.group(1)}]", text)
    text = text.replace("</div>", "\n").replace("<div>", "")
    text = text.replace("</p><p>", "\n\n").replace("<p>", "").replace("</p>", "")
    text = text.replace("<br/>", "\n").replace("<br>", "\n")
    text = re.sub(r"<[^>]+>", "", text)                                # any other tag (styled blocks)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n") + "\n"


def preview(name, leads, settings, kind=PERSON):
    """The emails exactly as each person will receive them, as plain text."""
    steps = sequence_steps(settings["send"], kind)
    out = []
    for lead in leads:
        out.append(f"=== {name}\nTo: {lead['email']} ({lead.get('job_title') or ''}, {lead.get('company_name') or ''})")
        for i, step in enumerate(steps, start=1):
            v = step["variants"][0]
            subject = render(v["subject"], lead).strip() or "(same thread as email 1)"
            label = "Email 1" if i == 1 else f"Email {i} (sent {steps[i - 2]['delay']} days later if no reply)"
            out.append(f"--- {label}\nSubject: {subject}\n\n{render(v['body'], lead)}")
    return "\n".join(out)


def campaign_body(name, market, settings, kind=None):
    s = settings["send"]
    kind = kind or kind_of_campaign(name, s)
    if not s.get("sending_accounts"):
        raise PipelineError(
            "No sending mailboxes set. Add your warmed mailboxes to send.sending_accounts "
            "in config/settings.yaml first."
        )
    sched = schedule_for(market, s["schedule"])
    steps = sequence_steps(s, kind)
    daily_limit = s["daily_limit"]
    if kind == INBOX:  # at most this many company inbox first emails per mailbox a day (19 Oct 2026)
        cap = int((s.get("company_inbox") or {}).get("daily_cap_per_mailbox", 5))
        daily_limit = cap * max(1, len(s["sending_accounts"]))
    elif kind == PERSON_OTHER:  # 23 Oct 2026: channels outside our usual ones
        daily_limit = int((s.get("other_channels") or {}).get("daily_limit", 15))
    elif kind == INBOX_OTHER:
        daily_limit = int((s.get("other_channels") or {}).get("company_inbox_daily_limit", 5))
    return {
        "name": name,
        "campaign_schedule": {
            "schedules": [{
                "name": f"{market} working hours",
                "timing": {"from": sched["from"], "to": sched["to"]},
                "days": schedule_days(sched),
                "timezone": instantly_timezone(sched["timezone"]),
            }]
        },
        "sequences": [{"steps": steps}],
        "email_list": s["sending_accounts"],
        "daily_limit": daily_limit,
        "stop_on_reply": True,
        # A reply from anyone at a company stops the emails to everyone else there.
        "stop_for_company": True,
        "link_tracking": False,
        "open_tracking": False,
    }


def _content(steps):
    return [[(v.get("subject") or "", v.get("body") or "") for v in step.get("variants") or []]
            for step in steps or []]


def refresh_campaign_content(instantly, settings, log=print):
    """Bring every Diablo campaign's emails in line with the templates, so a template change
    (or a fix such as the empty-body one) also reaches campaigns created earlier."""
    prefix = settings["sync"]["campaign_prefix"]
    by_kind = {k: sequence_steps(settings["send"], k) for k in KINDS}
    fixed = 0
    for camp in instantly.list_campaigns():
        if not str(camp.get("name") or "").startswith(prefix):
            continue
        steps = by_kind[kind_of_campaign(camp.get("name"), settings["send"])]
        current = (camp.get("sequences") or [{}])[0].get("steps")
        if _content(current) != _content(steps):
            instantly.update_campaign(camp["id"], {"sequences": [{"steps": steps}]})
            fixed += 1
            log(f"Updated the emails in campaign: {camp['name']}")
    return fixed


WAIT_REASONS = {
    "stopped": "someone at the company has replied, opted out or been marked, so nobody else there is emailed",
    "waiting": "the company's last email was under 3 days ago (one email every 3 days per company)",
    "forward": "someone at the company was already emailed; Sync sends this person a forward of that email in turn",
    "reminder": "the company's loop is done; Sync sends person 1 their reminder",
    "waiting_same_person": "the company's loop is done; person 1's reminder waits for its week",
    "no_reply": "the company's loop is finished with no reply",
    "waiting_for_reply": "person 1 was emailed and the company is waiting for their reply (no follow-ups)",
    "next": "a more senior approved person at the company goes first",
}


def mask(email):
    """a***@company.com, so logs and files never hold a full address."""
    email = email or ""
    if "@" not in email:
        return "(no email)"
    name, domain = email.split("@", 1)
    return f"{name[:1]}***@{domain}"


def skip_reason(contact, company, company_stage, needs_note=False):
    """Why an GATE2: Approved to send contact cannot be sent at all, or None."""
    p = contact["properties"]
    if not p.get("email"):
        return "it has no email address"
    if not company:
        return ("it is not linked to an AUTO-OUTREACH company in HubSpot (the pipeline only emails people "
                "at companies it added itself)")
    if company_stage in COMPANY_STOPPED:
        return "its company's Lead Status says outreach has ended or a person has taken it over"
    if company_stage not in ("approved", "in_outreach"):
        return "its company is not GATE1: Approved for outreach (gate 1)"
    if not p.get(PERSONAL_LINE):
        return "its Outreach personal line is empty"
    if needs_note and not p.get(COMPANY_NOTE):
        return "its Outreach company note is empty (the first email needs it)"
    return None


def created_emails(results, leads):
    """Emails of the leads Instantly actually created. Instantly may leave `email` empty in
    created_leads, so its `index` (position in what was sent) is used first."""
    created = set()
    offset = 0
    for r in results:
        for item in r.get("created_leads") or []:
            idx = item.get("index")
            if isinstance(idx, int) and 0 <= offset + idx < len(leads):
                created.add(leads[offset + idx]["email"].lower())
            elif item.get("email"):
                created.add(item["email"].lower())
        sent = r.get("total_sent")
        offset += sent if isinstance(sent, int) else min(1000, len(leads) - offset)
    uploaded = sum(r.get("leads_uploaded") or 0 for r in results)
    if not created and uploaded == len(leads):
        created = {l["email"].lower() for l in leads}
    return created


def run(target, settings, hs, instantly, dry_run=False, log=print):
    """instantly may be None in a dry run; it is then not read, so everyone looks not yet emailed."""
    check_target(hs, target)
    statuses = LeadStatus(hs)
    out_dir = run_dir("send")
    missing_link = booking_link_problem(settings)
    test_gaps = bool(settings["send"].get("test_gaps"))
    if missing_link and test_gaps:
        # Test runs (test account only, typed CONFIRM) may send with the placeholder link.
        log("TEST: the booking link is still a placeholder; it is sent as it is in this test run.")
        missing_link = ""
    if missing_link:
        log(f"WARNING: {missing_link}")
    elif not dry_run:
        # 26 Oct 2026 (Ariel): two campaigns a month. In this order: the leads waiting in them get their
        # bond paragraph, then the emails are brought up to date, then the "Other channels" leads move in.
        from .other_channels import fill_waiting, merge
        try:
            fill_waiting(hs, instantly, settings, log)
        except Exception as err:
            log(f"Could not give the waiting leads their bond paragraph: {str(err)[:300]}")
            raise PipelineError("The waiting leads could not be given their bond paragraph, so the campaigns' "
                                "emails were not changed and nothing was sent. It is tried again at the next run.")
        refresh_campaign_content(instantly, settings, log=log)
        try:
            merge(hs, instantly, settings, log)
        except Exception as err:
            log(f'Could not move the leads of the "Other channels" campaigns: {str(err)[:300]}')
    contacts = hs.tagged_search("contacts", [statuses.filter("contacts", "approved")], CONTACT_PROPS,
                                max_results=settings["send"]["contacts_per_run"])
    log(f"{len(contacts)} contacts approved to send")
    if not contacts:
        return {"queued": 0}
    if missing_link and not dry_run:
        raise PipelineError(missing_link)

    owner_of, companies = tagged_company_of(hs, [c["id"] for c in contacts], COMPANY_PROPS)

    prefix = settings["sync"]["campaign_prefix"]
    gap = float(settings["send"].get("next_contact_after_days", 4))
    one_email = follow_up_settings(settings["send"])  # 21 Oct 2026: follow-ups to people off
    in_instantly = instantly_view(instantly, prefix)
    notes = load_company_notes()
    everyone = contacts_by_company(hs, list(companies))
    groups, skipped, waiting = defaultdict(list), [], 0
    needs_note = first_email_uses(settings, "company_note")
    bond_config = bond.load()
    campaign_ids = {} if dry_run else {x["name"]: x["id"] for x in instantly.list_campaigns()}
    for c in contacts:
        company_id = owner_of.get(str(c["id"]))
        company = companies.get(company_id)
        comp = company["properties"] if company else None
        company_stage = statuses.of("companies", company) if company else ""
        p = c["properties"]
        reason = skip_reason(c, comp, company_stage, needs_note)
        if reason:
            skipped.append({"contact_id": c["id"], "email": mask(p.get("email")), "reason": reason})
            log(f"Skipped contact {c['id']} ({mask(p.get('email'))}): {reason}")
            continue
        # One person per company at a time: only the one next in line goes now.
        company_contacts = annotate(everyone.get(company_id) or [c], statuses, in_instantly)
        due, why = decide(company_contacts, company_stage, gap, follow_ups=one_email[0],
                          no_reply_days=one_email[1], inbox_reminder=one_email[2])
        if why != "next" or not due or due["id"] != c["id"]:  # only person 1 goes through the campaign
            waiting += 1
            log(f"Waiting: contact {c['id']} ({mask(p.get('email'))}) at {comp.get('name')}: "
                + WAIT_REASONS.get(why, "a more senior approved person at the company goes first"))
            continue
        if not (comp.get("country") or "").strip():  # 23 Oct 2026: "a direct partner in <country>" needs it
            waiting += 1
            log(f"Waiting: contact {c['id']} ({mask(p.get('email'))}) at {comp.get('name')}: the company has no "
                "Country in HubSpot, so the email could not name the market; fill in its Country")
            continue
        earlier = last_campaign(company_contacts)
        # A company stays in the campaign of its first email, so a reply there stops the others.
        # A company inbox (no people in Apollo, 19 Oct 2026) goes to the month's company inbox campaign.
        # 26 Oct 2026 (Ariel): only those two campaigns a month, whatever the channel. A channel outside
        # our usual ones gets the bond paragraph in the same email, and waits until the email has room for it.
        kind = kind_for(is_company_inbox(c))
        other = bool(bond.bond_channel(channel_of(comp, notes), bond_config))
        if other and not bond_ready(settings, kind):
            waiting += 1
            log(f"Waiting: contact {c['id']} ({mask(p.get('email'))}) at {comp.get('name')}: a channel outside our "
                "usual ones, whose email needs the bond paragraph; the campaign's email does not have room for it yet")
            continue
        if earlier and is_other_campaign(next((n for n, i in campaign_ids.items() if i == earlier), "")):
            earlier = None  # never added to an October "Other channels" campaign again
        key = ("campaign", earlier, kind) if earlier else ("month", kind)
        groups[key].append((c, company_id, comp, company_stage))
    if waiting:
        log(f"{waiting} approved contacts wait their turn (one person per company at a time)")

    existing = campaign_ids
    plan, contact_updates, company_updates, previews, intros = [], [], {}, [], []
    for key, members in groups.items():
        kind = key[-1]
        if key[0] == "campaign":  # the company's earlier contacts went here: keep it together
            campaign_id = key[1]
            name = next((n for n, i in existing.items() if i == campaign_id), f"campaign {campaign_id}")
        else:
            name = name_for_kind(kind, prefix, settings["send"])
            campaign_id = existing.get(name)
        leads = [with_bond(lead_for(c, comp, notes), comp, notes, bond_config) for c, _, comp, _ in members]
        plan.append({"campaign": name, "leads": len(leads), "new_campaign": not campaign_id and key[0] != "campaign"})
        previews.append(preview(name, leads, settings, kind))
        body = campaign_body(name, "", settings, kind) if not campaign_id else None  # a dry run checks it too
        if dry_run:
            continue
        if not campaign_id:
            campaign_id = instantly.create_campaign(body)["id"]
            log(f"Created paused campaign: {name}")
        results = instantly.add_leads(campaign_id, leads)
        uploaded = sum(r.get("leads_uploaded") or 0 for r in results)
        skipped_n = sum(r.get("skipped_count") or 0 for r in results)
        invalid = sum(r.get("invalid_email_count") or 0 for r in results)
        log(f"Instantly: {uploaded} leads added, {skipped_n} skipped (already in your Instantly "
            f"workspace), {invalid} invalid")
        created = created_emails(results, leads)
        try:  # 26 Oct 2026 (Ariel): the introduction is in Instantly, written on the contact's timeline
            timeline.queued(hs, [c["id"] for c, _, _, _ in members
                                 if c["properties"]["email"].lower() in created], name, log)
        except Exception as err:
            log(f"Could not write the timeline notes: {str(err)[:200]}")
        for c, company_id, _, company_stage in members:
            if c["properties"]["email"].lower() not in created:
                log(f"Not added (already in Instantly): {mask(c['properties']['email'])}. "
                    "It stays GATE2: Approved to send in HubSpot.")
                continue
            contact_updates.append((c["id"], statuses.props("contacts", "in_outreach")))
            intros.append(f"| {(companies.get(company_id) or {}).get('properties', {}).get('name') or 'a company'} | "
                          f"{c['properties'].get('jobtitle') or 'person 1'} | Introduction added to the campaign "
                          "(Lead Status: Attempted to Contact) |")
            if forward(company_stage, "in_outreach"):
                company_updates[company_id] = statuses.props("companies", "in_outreach")

    if not dry_run:
        hs.update_tagged("contacts", contact_updates)
        hs.update_tagged("companies", list(company_updates.items()))
        step_summary("## Button 4: introductions this run\n\n" + (
            "| Company | Person (job title) | What happened |\n|---|---|---|\n" + "\n".join(intros)
            if intros else "No new introduction was due this run."))
    write_json(out_dir / "plan.json", {"dry_run": dry_run, "campaigns": plan, "skipped": skipped})
    if previews:
        (out_dir / "email_preview.txt").write_text("\n\n".join(previews), encoding="utf-8")
        log("\nEMAIL PREVIEW (also saved as email_preview.txt under Artifacts)\n")
        shown = "\n\n".join(previews)
        log(shown if len(shown) < 20000 else shown[:20000] + "\n... (see email_preview.txt for the rest)")
    for row in plan:
        log(f"{'[dry run] ' if dry_run else ''}{row['campaign']}: {row['leads']} leads"
            + (" (new campaign, created paused)" if row["new_campaign"] else ""))
    return {"queued": len(contact_updates), "campaigns": plan, "skipped": len(skipped), "waiting": waiting}


def main(argv=None):
    p = argparse.ArgumentParser(description="Add approved contacts to Instantly")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-if-not-configured", action="store_true",
                   help="exit quietly when a key is missing (used by the automatic runs)")
    p.add_argument("--test-gaps", default="", help='type CONFIRM for 15-minute gaps (test account only)')
    args = p.parse_args(argv)
    try:
        settings = load_settings()
        if apply_test_gaps(settings, args.target, args.test_gaps):
            print("TEST GAPS ON: 15 minutes instead of 3 and 7 days, for this run only (test account).")
    except PipelineError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    if args.skip_if_not_configured and not (os.environ.get("HUBSPOT_TOKEN") and os.environ.get("INSTANTLY_API_KEY")):
        print("Send skipped: a key it needs is not added yet.")
        return 0
    try:
        # A dry run still reads Instantly (who was already emailed) when the key is there.
        instantly = Instantly() if (not args.dry_run or os.environ.get("INSTANTLY_API_KEY")) else None
        run(args.target, settings, HubSpot(), instantly, dry_run=args.dry_run)
    except (PipelineError, HubSpotError, InstantlyError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
