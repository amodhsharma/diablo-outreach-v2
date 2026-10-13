"""Job 5: copy Instantly results back to HubSpot's Lead Status. Runs every 3 hours.

Only AUTO-OUTREACH companies and contacts are ever changed (hubspot_client.TagGuard); an
Instantly lead whose HubSpot contact lacks the tag is ignored. Statuses only move forward
(Attempted to Contact, then In Progress, then Unqualified) and a Lead Status set by a person
(for example Emailed or Won) is never changed.

    Instantly                          Contact               Company
    replied or marked interested       In Progress           In Progress
    marked not interested              Unqualified           Unqualified
    unsubscribed (opted out)           Unqualified           Unqualified (nobody else is emailed)
    bounced                            Unqualified           unchanged (the others carry on)

It then moves companies on in turn (see next_in_line.py): one email per company every 3 days,
Person 1 to 4 first, then back to Person 1 for a reminder in their own thread, for 3 rounds.
First emails: the next approved contact is added to the company's campaign. Later emails: sent
here as a reply in the person's thread (needs INSTANTLY_EMAILS_KEY). A company that gets no
reply after the last round becomes Unqualified.
Usage:
    python -m outreach.sync --target test
"""

import argparse
import html as html_lib
import os
import sys

from .common import PipelineError, check_target, load_company_notes, load_settings, run_dir, write_json
from .hubspot_client import HubSpot, HubSpotError
from .instantly_client import Instantly, InstantlyError
from .next_in_line import (
    COMPANY_PROPS, annotate, contacts_by_company, decide, instantly_view, last_campaign, lead_for, parse_time,
    tagged_company_of,
)
from .schema import LEAD_STATUS, PERSONAL_LINE
from .stages import LeadStatus, forward


def lead_result(lead):
    """(contact stage, company stage or None, short event) for an Instantly lead."""
    status = lead.get("status")
    interest = lead.get("lt_interest_status")
    if status == -2:
        return "closed", "closed", "unsubscribed"
    if status == -1:
        return "closed", None, "bounced"
    if interest in (1, 2, 3, 4):
        return "replied", "replied", "marked interested"
    if interest in (-1, -2, -3):
        return "closed", "closed", "marked not interested"
    if (lead.get("email_reply_count") or 0) > 0:
        return "replied", "replied", "replied"
    return "in_outreach", None, "emailed" if lead.get("timestamp_last_contact") else "queued"


def run(target, settings, hs, instantly, log=print, emails_api=None):
    check_target(hs, target)
    statuses = LeadStatus(hs)
    leads = instantly_view(instantly, settings["sync"]["campaign_prefix"])
    log(f"{len(leads)} leads in the Diablo campaigns in Instantly")
    if not leads:
        return {"updated": 0}

    # Only AUTO-OUTREACH contacts come back from tagged_read; any other email is ignored.
    rows = hs.tagged_read("contacts", list(leads), ["email", LEAD_STATUS], id_property="email")
    contact_updates, changed = [], []
    for r in rows:
        p = r.get("properties", {})
        lead = leads.get((p.get("email") or "").lower())
        if not lead:
            continue
        new, company_stage, event = lead_result(lead)
        old = statuses.of("contacts", r)
        if not forward(old, new):
            continue
        contact_updates.append((r["id"], statuses.props("contacts", new)))
        changed.append({"contact_id": r["id"], "from": old, "to": new, "event": event,
                        "company_to": company_stage})
    hs.update_tagged("contacts", contact_updates)

    # Roll replies and opt-outs up to their companies.
    company_updates = {}
    ups = [c for c in changed if c["company_to"]]
    if ups:
        owner_of, current = tagged_company_of(hs, [c["contact_id"] for c in ups], [LEAD_STATUS])
        targets = {}
        for ch in ups:
            company_id = owner_of.get(str(ch["contact_id"]))
            if not company_id:
                continue
            cur = targets.get(company_id)
            if cur is None or forward(cur, ch["company_to"]):
                targets[company_id] = ch["company_to"]
        for company_id, stage in targets.items():
            now_stage = statuses.of("companies", current[company_id])
            # Someone else at the company has replied and is still talking to us: a colleague
            # unsubscribing does not make the company Unqualified.
            closing = {str(c["contact_id"]) for c in ups
                       if owner_of.get(str(c["contact_id"])) == company_id and c["company_to"] == "closed"}
            if now_stage == "replied" and stage == "closed" and all(
                    c["event"] == "unsubscribed" for c in ups if str(c["contact_id"]) in closing):
                others = contacts_by_company(hs, [company_id]).get(company_id) or []
                if any(str(o["id"]) not in closing and statuses.of("contacts", o) == "replied" for o in others):
                    continue
            if forward(now_stage, stage):
                company_updates[company_id] = statuses.props("companies", stage)
        hs.update_tagged("companies", list(company_updates.items()))

    moved = advance(hs, instantly, settings, log, emails_api=emails_api, statuses=statuses, leads=leads)
    out_dir = run_dir("sync")
    write_json(out_dir / "changes.json", {"contacts": changed, "companies": company_updates,
                                          "next_in_line": moved})
    log(f"Updated {len(contact_updates)} contacts and {len(company_updates)} companies in HubSpot")
    return {"updated": len(contact_updates), "companies": len(company_updates), **moved}


def _sent_time(email):
    return parse_time(email.get("timestamp_email") or email.get("timestamp_created"))


def follow_up_email(round_no, person, company, settings, notes=None):
    """(html, text) of a later-round email for one person, filled in."""
    from . import send
    rot = settings["send"].get("rotation") or {}
    paths = rot.get("follow_up_templates") or ["templates/follow_up.json"]
    path = paths[min(round_no - 2, len(paths) - 1)]
    _, body = send._template(path, settings["send"])
    lead = lead_for(person, company, notes)
    values = {"firstName": lead.get("first_name") or "", "lastName": lead.get("last_name") or "",
              "companyName": lead.get("company_name") or "", **lead["custom_variables"]}
    html = send.html_paragraphs(body)
    for key, value in values.items():
        html = html.replace("{{" + key + "}}", html_lib.escape(str(value)))
    return html, send.render(html, {})


def advance(hs, instantly, settings, log=print, now=None, emails_api=None, statuses=None, leads=None):
    """Move each AUTO-OUTREACH company in outreach on to its next email when it is due."""
    statuses = statuses or LeadStatus(hs)
    if leads is None:
        leads = instantly_view(instantly, settings["sync"]["campaign_prefix"])
    gap = int(settings["send"].get("next_contact_after_days", 3))
    rot = settings["send"].get("rotation") or {}
    rounds, min_same = int(rot.get("rounds", 1)), int(rot.get("min_days_same_person", 7))
    companies = hs.tagged_search("companies", [statuses.filter("companies", "in_outreach")],
                                 COMPANY_PROPS, max_results=5000)
    if not companies:
        return {"next_contacts_added": 0, "follow_ups_sent": 0, "no_reply": 0}
    everyone = contacts_by_company(hs, [c["id"] for c in companies])
    notes = load_company_notes()
    added, sent, no_reply, need_key, contact_updates, company_updates = 0, 0, 0, 0, [], []
    for company in companies:
        props = company.get("properties", {})
        contacts = annotate(everyone.get(company["id"]) or [], statuses, leads)
        states = [c["state"] for c in contacts]
        later_rounds = (rounds > 1 and "sent" in states and "queued" not in states
                        and not any(s in ("pending", "approved") for s in states))
        touches, history = None, {}
        if later_rounds and emails_api is not None:
            touches = {}
            for c in contacts:
                if c["state"] == "sent":
                    history[c["id"]] = emails_api.sent_emails(c["properties"].get("email") or "")
                    touches[c["id"]] = [t for t in (_sent_time(e) for e in history[c["id"]]) if t]
        due, why = decide(contacts, statuses.of("companies", company), gap, now,
                          touches=touches, rounds=rounds, min_same_days=min_same)
        if why == "no_reply":
            company_updates.append((company["id"], statuses.props("companies", "closed")))
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
            html, text = follow_up_email(round_no, due, props, settings, notes)
            emails_api.reply(past[-1], past[0].get("subject") or "", html, text)
            sent += 1
            log(f"{props.get('name')}: round {round_no} email sent to {due['properties'].get('jobtitle') or 'the contact'}, "
                "as a reply in their thread")
            continue
        campaign = last_campaign(contacts)
        if not due or why != "next" or not campaign or not due["properties"].get(PERSONAL_LINE):
            continue
        lead = lead_for(due, props, notes)
        results = instantly.add_leads(campaign, [lead])
        if sum(r.get("leads_uploaded") or 0 for r in results):
            contact_updates.append((due["id"], statuses.props("contacts", "in_outreach")))
            added += 1
            log(f"{props.get('name')}: no reply yet, next in line is {due['properties'].get('jobtitle') or 'the next contact'}")
        else:
            log(f"{props.get('name')}: {lead['email']} is already in Instantly; not added again")
    hs.update_tagged("contacts", contact_updates)
    hs.update_tagged("companies", company_updates)
    if need_key:
        log(f"{need_key} companies are ready for their next round, but the GitHub secret INSTANTLY_EMAILS_KEY "
            "(Instantly key with scope emails:all) is not set, so those emails wait")
    if added or sent or no_reply:
        log(f"Next in line: {added} first emails added, {sent} later-round emails sent, "
            f"{no_reply} companies with no reply after the last round set to Unqualified")
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
