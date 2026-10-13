"""Job 5: copy Instantly lead statuses back to HubSpot. Runs every 3 hours.

Statuses only move forward (Sent never goes back to Queued, Interested never back to
Replied). An opt-out also stops all outreach to that company.

It then moves companies on in turn (see next_in_line.py): one email per company every 3 days,
Person 1 to 4 first, then back to Person 1 for a reminder in their own thread, for 3 rounds.
First emails: the next approved contact is added to the company's campaign. Later emails: sent
here as a reply in the person's thread (needs INSTANTLY_EMAILS_KEY). A company that gets no
reply after the last round is marked "No reply".
Usage:
    python -m outreach.sync --target test
"""

import argparse
import os
import sys

from .common import PipelineError, check_target, load_settings, now_iso, run_dir, write_json
from .hubspot_client import HubSpot, HubSpotError
from .instantly_client import Instantly, InstantlyError
import datetime as dt
import html as html_lib

from .next_in_line import NOT_YET_APPROVED, contacts_by_company, decide, last_campaign, lead_for, parse_time

# Higher number wins.
RANK = {
    "": 0, "contact_found": 0, "copy_ready": 0, "approved_to_send": 0,
    "queued": 1, "sent": 2, "replied": 3, "not_interested": 4, "interested": 4,
    "bounced": 5, "opted_out": 6,
}
COMPANY_RANK = {"in_outreach": 1, "replied": 2, "not_interested": 3, "interested": 3, "suppressed": 9}


def lead_status(lead):
    """Map an Instantly lead to our contact status and a short event name."""
    status = lead.get("status")
    interest = lead.get("lt_interest_status")
    if status == -2:
        return "opted_out", "unsubscribed"
    if status == -1:
        return "bounced", "bounced"
    if interest in (1, 2, 3, 4):
        return "interested", "marked_interested"
    if interest in (-1, -2, -3):
        return "not_interested", "marked_not_interested"
    if (lead.get("email_reply_count") or 0) > 0:
        return "replied", "reply_received"
    if lead.get("timestamp_last_contact"):
        return "sent", "email_sent"
    return "queued", "queued"


def run(target, settings, hs, instantly, log=print, emails_api=None):
    check_target(hs, target)
    prefix = settings["sync"]["campaign_prefix"]
    campaigns = [c for c in instantly.list_campaigns() if (c.get("name") or "").startswith(prefix)]
    leads = []
    for c in campaigns:
        for lead in instantly.list_leads(c["id"]):
            lead["_campaign_id"] = c["id"]
            leads.append(lead)
    log(f"{len(campaigns)} campaigns, {len(leads)} leads in Instantly")
    if not leads:
        return {"updated": 0}

    by_email = {l["email"].lower(): l for l in leads if l.get("email")}
    rows = hs.batch_read("contacts", list(by_email), ["email", "diablo_contact_status"], id_property="email")
    contact_updates, changed = [], []
    for r in rows:
        p = r.get("properties", {})
        lead = by_email.get((p.get("email") or "").lower())
        if not lead:
            continue
        new, event = lead_status(lead)
        old = p.get("diablo_contact_status") or ""
        if RANK.get(new, 0) <= RANK.get(old, 0):
            continue
        when = lead.get("timestamp_last_reply") or lead.get("timestamp_last_contact") or now_iso()
        contact_updates.append((r["id"], {
            "diablo_contact_status": new,
            "diablo_last_event": event,
            "diablo_last_event_at": when,
            "diablo_instantly_lead_id": lead.get("id") or "",
        }))
        changed.append({"contact_id": r["id"], "email": p.get("email"), "from": old, "to": new})
    hs.batch_update("contacts", contact_updates)

    # Roll contact changes up to their companies.
    company_updates = {}
    if changed:
        links = hs.associated_ids("contacts", "companies", [c["contact_id"] for c in changed])
        targets = {}
        for ch in changed:
            for company_id in links.get(ch["contact_id"], [])[:1]:
                if ch["to"] == "opted_out":
                    targets[company_id] = {"diablo_outreach_status": "suppressed",
                                           "diablo_suppress_reason": "opted_out"}
                elif ch["to"] in ("replied", "interested", "not_interested"):
                    cur = targets.get(company_id, {}).get("diablo_outreach_status", "")
                    if COMPANY_RANK.get(ch["to"], 0) > COMPANY_RANK.get(cur, 0):
                        targets[company_id] = {"diablo_outreach_status": ch["to"]}
        if targets:
            current = {c["id"]: c["properties"] for c in hs.batch_read(
                "companies", list(targets), ["diablo_outreach_status"])}
            for company_id, props in targets.items():
                cur = (current.get(company_id) or {}).get("diablo_outreach_status") or ""
                if COMPANY_RANK.get(props["diablo_outreach_status"], 0) > COMPANY_RANK.get(cur, 0):
                    company_updates[company_id] = props
            hs.batch_update("companies", list(company_updates.items()))

    moved = advance(hs, instantly, settings, log, emails_api=emails_api)
    out_dir = run_dir("sync")
    write_json(out_dir / "changes.json", {"contacts": changed, "companies": company_updates,
                                          "next_in_line": moved})
    log(f"Updated {len(contact_updates)} contacts and {len(company_updates)} companies in HubSpot")
    return {"updated": len(contact_updates), "companies": len(company_updates), **moved}


def _sent_time(email):
    return parse_time(email.get("timestamp_email") or email.get("timestamp_created"))


def follow_up_email(round_no, person, company, settings):
    """(html, text) of a later-round email for one person, filled in."""
    from . import send
    rot = settings["send"].get("rotation") or {}
    paths = rot.get("follow_up_templates") or ["templates/follow_up.json"]
    path = paths[min(round_no - 2, len(paths) - 1)]
    _, body = send._template(path, settings["send"])
    lead = lead_for(person, company, company.get("diablo_market") or "Unknown")
    values = {"firstName": lead.get("first_name") or "", "lastName": lead.get("last_name") or "",
              "companyName": lead.get("company_name") or "", **lead["custom_variables"]}
    html = send.html_paragraphs(body)
    for key, value in values.items():
        html = html.replace("{{" + key + "}}", html_lib.escape(str(value)))
    return html, send.render(html, {})


def advance(hs, instantly, settings, log=print, now=None, emails_api=None):
    """Move each company in outreach on to its next email when it is due."""
    gap = int(settings["send"].get("next_contact_after_days", 3))
    rot = settings["send"].get("rotation") or {}
    rounds, min_same = int(rot.get("rounds", 1)), int(rot.get("min_days_same_person", 7))
    companies = hs.search(
        "companies", [{"propertyName": "diablo_outreach_status", "operator": "EQ", "value": "in_outreach"}],
        ["name", "domain", "diablo_market", "diablo_channel_category", "diablo_outreach_status",
         "diablo_suppress_reason"],
        max_results=5000)
    if not companies:
        return {"next_contacts_added": 0, "follow_ups_sent": 0, "no_reply": 0}
    everyone = contacts_by_company(hs, [c["id"] for c in companies])
    added, sent, no_reply, need_key, contact_updates, company_updates = 0, 0, 0, 0, [], []
    for company in companies:
        props = company.get("properties", {})
        if props.get("diablo_suppress_reason"):
            continue
        contacts = everyone.get(company["id"]) or []
        statuses = [c["properties"].get("diablo_contact_status") or "" for c in contacts]
        later_rounds = (rounds > 1 and "sent" in statuses and "queued" not in statuses
                        and not any(s in NOT_YET_APPROVED or s == "approved_to_send" for s in statuses))
        touches, history = None, {}
        if later_rounds and emails_api is not None:
            touches = {}
            for c in contacts:
                if (c["properties"].get("diablo_contact_status") or "") == "sent":
                    history[c["id"]] = emails_api.sent_emails(c["properties"].get("email") or "")
                    touches[c["id"]] = [t for t in (_sent_time(e) for e in history[c["id"]]) if t]
        due, why = decide(contacts, props.get("diablo_outreach_status"), gap, now,
                          touches=touches, rounds=rounds, min_same_days=min_same)
        if why == "no_reply":
            if not company_updates and hs.ensure_option("companies", "diablo_outreach_status", "No reply", "no_reply"):
                log("Added 'No reply' to the Outreach company status dropdown")
            company_updates.append((company["id"], {"diablo_outreach_status": "no_reply"}))
            no_reply += 1
            continue
        if why == "waiting_for_emails_key":
            need_key += 1
            continue
        if why == "follow_up":
            past = history.get(due["id"]) or []
            if not past:
                log(f"{props.get('name')}: could not find the earlier email to reply to; will try again next run")
                continue
            round_no = len(past) + 1
            html, text = follow_up_email(round_no, due, props, settings)
            emails_api.reply(past[-1], past[0].get("subject") or "", html, text)
            contact_updates.append((due["id"], {"diablo_last_event": f"email_{round_no}_sent",
                                                "diablo_last_event_at": (now or dt.datetime.now(dt.timezone.utc)).isoformat()}))
            sent += 1
            log(f"{props.get('name')}: round {round_no} email sent to {due['properties'].get('jobtitle') or 'the contact'}, "
                "as a reply in their thread")
            continue
        campaign = last_campaign(contacts)
        if not due or why != "next" or not campaign or not due["properties"].get("diablo_personal_line"):
            continue
        lead = lead_for(due, props, props.get("diablo_market") or "Unknown")
        results = instantly.add_leads(campaign, [lead])
        if sum(r.get("leads_uploaded") or 0 for r in results):
            contact_updates.append((due["id"], {"diablo_contact_status": "queued",
                                                "diablo_instantly_campaign_id": campaign}))
            added += 1
            log(f"{props.get('name')}: no reply yet, next in line is {due['properties'].get('jobtitle') or 'the next contact'}")
        else:
            log(f"{props.get('name')}: {lead['email']} is already in Instantly; not added again")
    hs.batch_update("contacts", contact_updates)
    hs.batch_update("companies", company_updates)
    if need_key:
        log(f"{need_key} companies are ready for their next round, but the GitHub secret INSTANTLY_EMAILS_KEY "
            "(Instantly key with scope emails:all) is not set, so those emails wait")
    if added or sent or no_reply:
        log(f"Next in line: {added} first emails added, {sent} later-round emails sent, "
            f"{no_reply} companies marked No reply")
    return {"next_contacts_added": added, "follow_ups_sent": sent, "no_reply": no_reply,
            "waiting_for_emails_key": need_key}


def main(argv=None):
    p = argparse.ArgumentParser(description="Sync Instantly statuses to HubSpot")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--skip-if-not-configured", action="store_true",
                   help="exit quietly when keys are missing (used by the timer)")
    args = p.parse_args(argv)
    if args.skip_if_not_configured and not (os.environ.get("HUBSPOT_TOKEN") and os.environ.get("INSTANTLY_API_KEY")):
        print("Sync skipped: HubSpot or Instantly key not added yet.")
        return 0
    try:
        key = os.environ.get("INSTANTLY_EMAILS_KEY")
        run(args.target, load_settings(), HubSpot(), Instantly(), emails_api=Instantly(api_key=key) if key else None)
    except (PipelineError, HubSpotError, InstantlyError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
