"""Job 4b: add approved contacts to an Instantly campaign.

Only contacts whose Outreach contact status is Approved to send are sent (gate 2).
Campaigns are created paused; you press Start in Instantly for each new campaign.
Usage:
    python -m outreach.send --target test --dry-run
    python -m outreach.send --target test
"""

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict

from .common import ROOT, PipelineError, category_label, check_target, load_settings, market_matches, run_dir, write_json
from .hubspot_client import HubSpot, HubSpotError
from .instantly_client import Instantly, InstantlyError

CONTACT_PROPS = ["email", "firstname", "lastname", "jobtitle", "diablo_subject_line", "diablo_personal_line"]
COMPANY_PROPS = ["name", "domain", "diablo_market", "diablo_channel_category", "diablo_suppress_reason"]


MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def month_label(day=None):
    """Month and year for campaign names, e.g. OCT2026."""
    day = day or dt.date.today()
    return f"{MONTHS[day.month - 1]}{day.year}"


def campaign_name(prefix, market, category_value, month=None, labels=None):
    """e.g. "Diablo | Delhi, India | Health food distributor | OCT2026"."""
    month = month or month_label()
    label = category_label(category_value, labels) or "Other"
    return f"{prefix} {market} | {label} | {month}"


def schedule_for(market, schedules):
    """Most specific schedule whose name matches the market ("Mumbai, India" uses "India"
    unless a "Mumbai" entry exists); falls back to default."""
    best, best_len = schedules["default"], -1
    for key, value in schedules.items():
        if key != "default" and market_matches(key, market) and len(key) > best_len:
            best, best_len = value, len(key)
    return best


def _template(name, s):
    template = json.loads((ROOT / "templates" / name).read_text(encoding="utf-8"))
    return template["subject"], template["body"].replace("{{privacy_url}}", s["privacy_url"])


def sequence_steps(s):
    """First email, plus one reminder for anyone who has not replied (Instantly's `delay` is
    the wait before the NEXT email, so it sits on the first step)."""
    follow = s.get("follow_up") or {}
    subject, body = _template("first_email.json", s)
    first = {"type": "email", "delay": 0, "delay_unit": "days",
             "variants": [{"subject": subject, "body": body}]}
    if not follow.get("enabled"):
        return [first]
    first["delay"] = int(follow.get("delay_days", 7))
    f_subject, f_body = _template("follow_up.json", s)
    second = {"type": "email", "delay": 0, "delay_unit": "days",
              "variants": [{"subject": f_subject, "body": f_body}]}
    return [first, second]


def render(text, lead):
    """Fill a template the way Instantly will, for the preview."""
    values = {"firstName": lead.get("first_name") or "", "lastName": lead.get("last_name") or "",
              "companyName": lead.get("company_name") or "", **lead.get("custom_variables", {})}
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
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
                "days": {"0": False, "1": True, "2": True, "3": True, "4": True, "5": True, "6": False},
                "timezone": sched["timezone"],
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


def run(target, settings, hs, instantly, dry_run=False, log=print):
    check_target(hs, target)
    out_dir = run_dir("send")
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
    labels = hs.option_labels("companies", "diablo_channel_category")
    groups, skipped = defaultdict(list), []
    for c in contacts:
        company_id = (links.get(c["id"]) or [None])[0]
        comp = companies.get(company_id)
        p = c["properties"]
        if not comp or comp.get("diablo_suppress_reason") or not p.get("diablo_personal_line"):
            skipped.append(c["id"])
            continue
        market = comp.get("diablo_market") or "Unknown"
        groups[(market, comp.get("diablo_channel_category") or "")].append((c, company_id, comp))

    existing = {} if dry_run else {x["name"]: x["id"] for x in instantly.list_campaigns()}
    plan, contact_updates, company_updates, previews = [], [], {}, []
    for (market, category), members in groups.items():
        name = campaign_name(prefix, market, category, labels=labels)
        leads = [{
            "email": c["properties"]["email"],
            "first_name": c["properties"].get("firstname") or "",
            "last_name": c["properties"].get("lastname") or "",
            "company_name": comp.get("name") or "",
            "job_title": c["properties"].get("jobtitle") or "",
            "website": comp.get("domain") or "",
            "custom_variables": {
                "subject_line": c["properties"]["diablo_subject_line"],
                "personal_line": c["properties"]["diablo_personal_line"],
                "market": market,
            },
        } for c, _, comp in members]
        plan.append({"campaign": name, "leads": len(leads), "new_campaign": name not in existing})
        previews.append(preview(name, leads, settings))
        if dry_run:
            continue
        campaign_id = existing.get(name)
        if not campaign_id:
            campaign_id = instantly.create_campaign(campaign_body(name, market, settings))["id"]
            log(f"Created paused campaign: {name}")
        results = instantly.add_leads(campaign_id, leads)
        uploaded = sum(r.get("leads_uploaded") or 0 for r in results)
        skipped_n = sum(r.get("skipped_count") or 0 for r in results)
        invalid = sum(r.get("invalid_email_count") or 0 for r in results)
        log(f"Instantly: {uploaded} leads added, {skipped_n} skipped (already in your Instantly "
            f"workspace), {invalid} invalid")
        created = {(l.get("email") or "").lower() for r in results for l in (r.get("created_leads") or [])}
        if not created and uploaded == len(leads):
            created = {l["email"].lower() for l in leads}
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
    return {"queued": len(contact_updates), "campaigns": plan, "skipped": len(skipped)}


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
