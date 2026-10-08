"""Job 4b: add approved contacts to an Instantly campaign.

Only contacts whose Outreach contact status is Approved to send are sent (gate 2), and only
one person per company at a time, most senior first (see next_in_line.py). The sync job
moves each company on to its next person by itself. Campaigns are created paused; you
press Start in Instantly for each new campaign.
Usage:
    python -m outreach.send --target test --dry-run
    python -m outreach.send --target test
"""

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict

from .common import ROOT, PipelineError, check_target, load_settings, market_matches, run_dir, write_json
from .hubspot_client import HubSpot, HubSpotError
from .instantly_client import Instantly, InstantlyError
from .instantly_timezones import instantly_timezone
from .next_in_line import contacts_by_company, decide, last_campaign, lead_for

CONTACT_PROPS = ["email", "firstname", "lastname", "jobtitle", "diablo_subject_line", "diablo_personal_line"]
COMPANY_PROPS = ["name", "domain", "diablo_market", "diablo_channel_category", "diablo_suppress_reason",
                 "diablo_outreach_status"]


MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def month_label(day=None):
    """Month and year for campaign names, e.g. OCT2026."""
    day = day or dt.date.today()
    return f"{MONTHS[day.month - 1]}{day.year}"


def campaign_name(prefix, month=None):
    """One campaign per month for every Location and Channel (agreed 8 Oct 2026), e.g.
    "Diablo | OCT2026". Location and Channel stay on each lead and in HubSpot."""
    return f"{prefix} {month or month_label()}"


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


def _template(name, s):
    template = json.loads((ROOT / "templates" / name).read_text(encoding="utf-8"))
    return template["subject"], template["body"].replace("{{privacy_url}}", s["privacy_url"])


def html_paragraphs(body):
    """Instantly shows (and sends) an empty email when the body is bare text with <br/> breaks,
    so each paragraph (text between blank lines) is wrapped in <p>...</p>."""
    parts = [part.strip() for part in body.split("<br/><br/>") if part.strip()]
    return "".join(f"<p>{part}</p>" for part in parts)


def sequence_steps(s):
    """First email, plus one reminder for anyone who has not replied (Instantly's `delay` is
    the wait before the NEXT email, so it sits on the first step)."""
    follow = s.get("follow_up") or {}
    subject, body = _template("first_email.json", s)
    first = {"type": "email", "delay": 0, "delay_unit": "days",
             "variants": [{"subject": subject, "body": html_paragraphs(body)}]}
    if not follow.get("enabled"):
        return [first]
    first["delay"] = int(follow.get("delay_days", 7))
    f_subject, f_body = _template("follow_up.json", s)
    second = {"type": "email", "delay": 0, "delay_unit": "days",
              "variants": [{"subject": f_subject, "body": html_paragraphs(f_body)}]}
    return [first, second]


def render(text, lead):
    """Fill a template the way Instantly will, for the preview."""
    values = {"firstName": lead.get("first_name") or "", "lastName": lead.get("last_name") or "",
              "companyName": lead.get("company_name") or "", **lead.get("custom_variables", {})}
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    text = text.replace("</p><p>", "\n\n").replace("<p>", "").replace("</p>", "")
    return text.replace("<br/>", "\n")


def preview(name, leads, settings):
    """The emails exactly as each person will receive them, as plain text."""
    steps = sequence_steps(settings["send"])
    out = []
    for lead in leads:
        out.append(f"=== {name}\nTo: {lead['email']} ({lead.get('job_title') or ''}, {lead.get('company_name') or ''})")
        for i, step in enumerate(steps, start=1):
            v = step["variants"][0]
            subject = render(v["subject"], lead) or "(same thread as email 1)"
            label = "Email 1" if i == 1 else f"Email {i} (sent {steps[i - 2]['delay']} days later if no reply)"
            out.append(f"--- {label}\nSubject: {subject}\n\n{render(v['body'], lead)}\n")
    return "\n".join(out)


def campaign_body(name, market, settings):
    s = settings["send"]
    if not s.get("sending_accounts"):
        raise PipelineError(
            "No sending mailboxes set. Add your warmed mailboxes to send.sending_accounts "
            "in config/settings.yaml first."
        )
    sched = schedule_for(market, s["schedule"])
    steps = sequence_steps(s)
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
        "daily_limit": s["daily_limit"],
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
    steps = sequence_steps(settings["send"])
    fixed = 0
    for camp in instantly.list_campaigns():
        if not str(camp.get("name") or "").startswith(prefix):
            continue
        current = (camp.get("sequences") or [{}])[0].get("steps")
        if _content(current) != _content(steps):
            instantly.update_campaign(camp["id"], {"sequences": [{"steps": steps}]})
            fixed += 1
            log(f"Updated the emails in campaign: {camp['name']}")
    return fixed


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
    check_target(hs, target)
    out_dir = run_dir("send")
    if not dry_run:
        refresh_campaign_content(instantly, settings, log=log)
    contacts = hs.search(
        "contacts",
        [{"propertyName": "diablo_contact_status", "operator": "EQ", "value": "approved_to_send"}],
        CONTACT_PROPS,
        max_results=settings["send"]["contacts_per_run"],
    )
    log(f"{len(contacts)} contacts approved to send")
    if not contacts:
        return {"queued": 0}

    links = hs.associated_ids("contacts", "companies", [c["id"] for c in contacts])
    company_ids = sorted({ids[0] for ids in links.values() if ids})
    companies = {c["id"]: c["properties"] for c in hs.batch_read("companies", company_ids, COMPANY_PROPS)}

    prefix = settings["sync"]["campaign_prefix"]
    gap = int(settings["send"].get("next_contact_after_days", 4))
    everyone = contacts_by_company(hs, company_ids)
    groups, skipped, waiting = defaultdict(list), [], 0
    for c in contacts:
        company_id = (links.get(c["id"]) or [None])[0]
        comp = companies.get(company_id)
        p = c["properties"]
        if not comp or comp.get("diablo_suppress_reason") or not p.get("diablo_personal_line"):
            skipped.append(c["id"])
            continue
        # One person per company at a time: only the one next in line goes now.
        company_contacts = everyone.get(company_id) or [c]
        due, _ = decide(company_contacts, comp.get("diablo_outreach_status"), gap)
        if not due or due["id"] != c["id"]:
            waiting += 1
            continue
        earlier = last_campaign(company_contacts)
        # A company stays in the campaign of its first email, so a reply there stops the others.
        key = ("campaign", earlier) if earlier else ("month",)
        groups[key].append((c, company_id, comp))
    if waiting:
        log(f"{waiting} approved contacts wait their turn (one person per company at a time)")

    existing = {} if dry_run else {x["name"]: x["id"] for x in instantly.list_campaigns()}
    plan, contact_updates, company_updates, previews = [], [], {}, []
    for key, members in groups.items():
        if key[0] == "campaign":  # the company's earlier contacts went here: keep it together
            campaign_id = key[1]
            name = next((n for n, i in existing.items() if i == campaign_id), f"campaign {campaign_id}")
        else:
            name = campaign_name(prefix)
            campaign_id = existing.get(name)
        leads = [lead_for(c, comp, comp.get("diablo_market") or "Unknown") for c, _, comp in members]
        plan.append({"campaign": name, "leads": len(leads), "new_campaign": not campaign_id and key[0] != "campaign"})
        previews.append(preview(name, leads, settings))
        body = campaign_body(name, "", settings) if not campaign_id else None  # a dry run checks it too
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
        for c, company_id, _ in members:
            if c["properties"]["email"].lower() not in created:
                log(f"Not added (already in Instantly): {c['properties']['email']}. "
                    "It stays Approved to send in HubSpot.")
                continue
            contact_updates.append((c["id"], {
                "diablo_contact_status": "queued",
                "diablo_instantly_campaign_id": campaign_id,
            }))
            company_updates[company_id] = {"diablo_outreach_status": "in_outreach"}

    if not dry_run:
        hs.batch_update("contacts", contact_updates)
        hs.batch_update("companies", list(company_updates.items()))
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
    args = p.parse_args(argv)
    try:
        instantly = None if args.dry_run else Instantly()
        run(args.target, load_settings(), HubSpot(), instantly, dry_run=args.dry_run)
    except (PipelineError, HubSpotError, InstantlyError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
