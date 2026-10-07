"""Job 5: copy Instantly lead statuses back to HubSpot. Runs every 3 hours.

Statuses only move forward (Sent never goes back to Queued, Interested never back to
Replied). An opt-out also stops all outreach to that company.
Usage:
    python -m outreach.sync --target test
"""

import argparse
import os
import sys

from .common import PipelineError, check_target, load_settings, now_iso, run_dir, write_json
from .hubspot_client import HubSpot, HubSpotError
from .instantly_client import Instantly, InstantlyError

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


def run(target, settings, hs, instantly, log=print):
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

    out_dir = run_dir("sync")
    write_json(out_dir / "changes.json", {"contacts": changed, "companies": company_updates})
    log(f"Updated {len(contact_updates)} contacts and {len(company_updates)} companies in HubSpot")
    return {"updated": len(contact_updates), "companies": len(company_updates)}


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
        run(args.target, load_settings(), HubSpot(), Instantly())
    except (PipelineError, HubSpotError, InstantlyError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
