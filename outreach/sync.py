"""Button 4, step 1: copy Instantly results back to HubSpot's Lead Status. Runs every 3 hours.

Only AUTO-OUTREACH companies and contacts are ever changed (hubspot_client.TagGuard); an
Instantly lead whose HubSpot contact lacks the tag is ignored. Statuses only move forward
(Attempted to Contact, then In Progress, then Unqualified) and a Lead Status set by a person
(for example Emailed or Won) is never changed.

    Instantly                          Contact               Company
    replied or marked interested       In Progress           In Progress
    marked not interested              Unqualified           Unqualified
    unsubscribed (opted out)           Unqualified           Unqualified (nobody else is emailed)
    bounced                            Unqualified           unchanged (the others carry on)

It then moves companies on in turn (see next_in_line.py), one loop per company (agreed 14 Oct
2026): person 1's introduction goes through the Instantly campaign; every 3 days the next
approved person gets a forward of the latest email in the chain, naming the colleague before
them; then person 1 gets one reminder as a reply in their own thread, at least a week after
their introduction. 3 days after that with no reply the company becomes Unqualified. Forwards
and the reminder need INSTANTLY_EMAILS_KEY. A reply from anyone, also to a forward, stops the
company at once.
Usage:
    python -m outreach.sync --target test
"""

import argparse
import html as html_lib
import os
import re
import sys

from .common import PipelineError, check_target, ist, load_company_notes, load_settings, run_dir, step_summary, write_json
from .hubspot_client import HubSpot, HubSpotError
from .instantly_client import Instantly, InstantlyError
from .next_in_line import (
    COMPANY_PROPS, annotate, apply_test_gaps, contacts_by_company, decide, instantly_view, last_campaign,
    lead_for, mark_sent, parse_time, rank_of, tagged_company_of, touch_times,
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


def _name(contact):
    p = contact.get("properties") or {}
    return " ".join(x.strip() for x in (p.get("firstname") or "", p.get("lastname") or "") if x and x.strip())


def previous_colleague(person, contacts, touches):
    """The colleague at the same company who was emailed most recently and has not replied
    (agreed 14 Oct 2026), or None. Only people whose state is "sent" count: anyone who replied or
    opted out stops the whole company, and a bounced or skipped person is never named."""
    best, best_time = None, None
    for c in contacts:
        if str(c["id"]) == str(person["id"]) or c.get("state") != "sent":
            continue
        times = (touches or {}).get(c["id"]) or []
        if times and (best_time is None or max(times) > best_time):
            best, best_time = c, max(times)
    return best


def _addresses(value):
    return [a.strip().lower() for a in re.split(r"[,;\s]+", str(value or "")) if "@" in a]


def company_mail(emails_api, contacts):
    """What Instantly holds for a company's people: ({contact id: [times emailed]},
    {contact id: [emails sent to them, oldest first]}, {contact ids that replied}).
    A forward may be filed under the address it was forwarded from, so every email is matched to
    a person by its own To or From address."""
    by_addr = {(c["properties"].get("email") or "").lower(): c for c in contacts
               if c.get("state") in ("queued", "sent", "bounced") and c["properties"].get("email")}
    seen = {}
    for addr in by_addr:
        for e in emails_api.thread_emails(addr):
            seen.setdefault(e.get("id") or id(e), (e, addr))
    sent, replied = {}, set()
    for e, asked in seen.values():
        kind = e.get("ue_type")
        if kind == 2:  # received: a reply from one of them (out-of-office answers do not count)
            if e.get("is_auto_reply"):
                continue
            sender = _addresses(e.get("from_address_email"))
            who = by_addr.get(sender[0]) if sender else by_addr.get(asked)
            if who:
                replied.add(who["id"])
            continue
        if kind not in (1, 3):
            continue
        to = _addresses(e.get("to_address_email_list"))
        people = [by_addr[a] for a in to if a in by_addr] if to else [by_addr[asked]]
        for who in people:
            sent.setdefault(who["id"], []).append(e)
    for cid in sent:
        sent[cid].sort(key=lambda e: parse_time(e.get("timestamp_email") or e.get("timestamp_created"))
                       or parse_time("1970-01-01"))
    touches = {cid: [t for t in (_sent_time(e) for e in es) if t] for cid, es in sent.items()}
    return touches, sent, replied


def _fill(path, person, company, settings, notes, extra=None, mailbox=None):
    from . import send
    _, body = send._template(path, settings["send"], mailbox=mailbox)
    lead = lead_for(person, company, notes)
    values = {"firstName": lead.get("first_name") or "", "lastName": lead.get("last_name") or "",
              "companyName": lead.get("company_name") or "", **lead["custom_variables"], **(extra or {})}
    html = send.html_paragraphs(body)
    for key, value in values.items():
        html = html.replace("{{" + key + "}}", html_lib.escape(str(value)))
    return html, send.render(html, {})


def reminder_subject(settings):
    """The reminder template's own subject, or "" to reply as "Re: <first subject>". follow_up_2.json
    (agreed 15 Oct 2026) has its own subject, so person 1 gets it as a separate email."""
    from . import send
    paths = settings["send"].get("templates") or {}
    subject, _ = send._template(paths.get("reminder") or "templates/follow_up.json", settings["send"])
    return (subject or "").strip()


def reminder_email(person, company, settings, notes=None, mailbox=None):
    """(html, text) of person 1's one reminder (agreed 14 Oct 2026). mailbox: the one sending it
    (the same one that sent the first email), used only when the signature follows the mailbox."""
    paths = settings["send"].get("templates") or {}
    return _fill(paths.get("reminder") or "templates/follow_up.json", person, company, settings, notes,
                 mailbox=mailbox)


def forward_email(person, company, settings, notes=None, colleague="", original=None):
    """(html, text) of the note on top of a forward to the next person (agreed 14 Oct 2026)."""
    paths = settings["send"].get("templates") or {}
    mailbox = (original or {}).get("eaccount")  # the forward goes from the mailbox of the chain
    html, text = _fill(paths.get("forward") or "templates/forward.json", person, company, settings, notes,
                       {"colleague_name": colleague}, mailbox=mailbox)
    if original is not None and (settings["send"].get("rotation") or {}).get("forward_include_original"):
        body = original.get("body") or {}
        html += "<div><br></div><div>---------- Forwarded message ----------</div>" + (body.get("html") or "")
        text += "\n\n---------- Forwarded message ----------\n" + (body.get("text") or "")
    return html, text


def forward_subject(chain):
    """ "Fwd: " and the subject of the company's first email, without any Re: or Fwd: in front."""
    subject = re.sub(r"^\s*((re|fwd?|fw)\s*:\s*)+", "", chain.get("subject") or "", flags=re.I)
    return f"Fwd: {subject}"


NEXT_STEP = {
    "next": "the introduction to the next person", "forward": "a forward to the next person",
    "reminder": "person 1's reminder", "waiting": "the next email, 3 days after the last one",
    "waiting_same_person": "person 1's reminder, a week after their introduction",
    "waiting_for_gate_2": "someone to be approved at GATE2", "waiting_for_emails_key":
    "the GitHub secret INSTANTLY_EMAILS_KEY", "stopped": "nothing (someone replied or a person took over)",
    "no_reply": "Unqualified (the loop is finished)", "nothing": "nothing (nobody approved)",
}


def due_at(contacts, touches, why, gap_days, min_same_days):
    """When the company's next email is due, for the waiting reasons, or None."""
    import datetime as _dt
    times = [t for c in contacts if c.get("state") in ("sent", "bounced") for t in touch_times(c, touches)]
    if why == "waiting" and times:
        return max(times) + _dt.timedelta(days=gap_days)
    if why == "waiting_same_person":
        sent = [c for c in contacts if c.get("state") == "sent" and touch_times(c, touches)]
        if sent:
            first = min(sent, key=lambda c: touch_times(c, touches)[0])
            return touch_times(first, touches)[0] + _dt.timedelta(days=min_same_days)
    return None


def progress_rows(name, contacts, touches, statuses):
    """One line per person at a company: order, job title, Lead Status and when they were emailed.
    Job titles only: no names or email addresses are written anywhere."""
    rows = []
    for c in sorted(contacts, key=rank_of):
        p = c["properties"]
        label = statuses.label("contacts", p.get(LEAD_STATUS))
        times = touch_times(c, touches)
        emailed = ", ".join(ist(t) for t in times) if times else "not yet"
        rows.append(f"| {name} | {p.get('diablo_outreach_order') or '?'} | {p.get('jobtitle') or 'contact'} | "
                    f"{label} | {emailed} |")
    return rows


def overview(hs, instantly, settings, emails_api=None, now=None, statuses=None):
    """Read only: where every company in outreach is in its loop, for the health report."""
    statuses = statuses or LeadStatus(hs)
    leads = instantly_view(instantly, settings["sync"]["campaign_prefix"])
    gap = float(settings["send"].get("next_contact_after_days", 3))
    min_same = float((settings["send"].get("rotation") or {}).get("min_days_same_person", 7))
    companies = hs.tagged_search("companies", [statuses.filter("companies", "in_outreach")],
                                 COMPANY_PROPS, max_results=5000)
    if not companies:
        return "## Where every company is in its loop\n\n- No company is being emailed right now.\n"
    everyone = contacts_by_company(hs, [c["id"] for c in companies])
    people, nexts = [], []
    for company in companies:
        name = company.get("properties", {}).get("name") or "a company"
        contacts = annotate(everyone.get(company["id"]) or [], statuses, leads)
        touches = None
        if emails_api is not None:
            touches, _, _ = company_mail(emails_api, contacts)
            mark_sent(contacts, touches)
        _, why = decide(contacts, statuses.of("companies", company), gap, now, touches=touches, min_same_days=min_same)
        when = due_at(contacts, touches, why, gap, min_same)
        nexts.append(f"- **{name}**: next is {NEXT_STEP.get(why, why)}" + (f", due {ist(when)}" if when else ""))
        people += progress_rows(name, contacts, touches, statuses)
    return ("## Where every company is in its loop\n\n" + "\n".join(nexts) + "\n\n"
            "| Company | Order | Person (job title) | Lead Status | Emailed |\n|---|---|---|---|---|\n"
            + "\n".join(people) + "\n")


def advance(hs, instantly, settings, log=print, now=None, emails_api=None, statuses=None, leads=None):
    """Move each AUTO-OUTREACH company in outreach on through its one loop when the next email is due."""
    statuses = statuses or LeadStatus(hs)
    if leads is None:
        leads = instantly_view(instantly, settings["sync"]["campaign_prefix"])
    gap = float(settings["send"].get("next_contact_after_days", 3))
    rot = settings["send"].get("rotation") or {}
    min_same = float(rot.get("min_days_same_person", 7))
    companies = hs.tagged_search("companies", [statuses.filter("companies", "in_outreach")],
                                 COMPANY_PROPS, max_results=5000)
    result = {"next_contacts_added": 0, "forwards_sent": 0, "reminders_sent": 0, "no_reply": 0,
              "replied": 0, "waiting_for_emails_key": 0}
    if not companies:
        return result
    everyone = contacts_by_company(hs, [c["id"] for c in companies])
    notes = load_company_notes()
    contact_updates, company_updates = [], []
    sent_rows, waiting_rows = [], []
    for company in companies:
        props = company.get("properties", {})
        name = props.get("name")
        contacts = annotate(everyone.get(company["id"]) or [], statuses, leads)
        touches, history, replied = None, {}, set()
        if emails_api is not None and any(c["state"] in ("queued", "sent", "bounced") for c in contacts):
            touches, history, replied = company_mail(emails_api, contacts)
            mark_sent(contacts, touches)
        if replied:  # e.g. a reply to a forward, which Instantly's campaign does not count
            for c in contacts:
                if c["id"] in replied and forward(statuses.of("contacts", c), "replied"):
                    contact_updates.append((c["id"], statuses.props("contacts", "replied")))
            if forward(statuses.of("companies", company), "replied"):
                company_updates.append((company["id"], statuses.props("companies", "replied")))
            result["replied"] += 1
            sent_rows.append(f"| {name} | - | Reply received: nobody else there is emailed |")
            log(f"{name}: someone replied; nobody else there is emailed")
            continue
        due, why = decide(contacts, statuses.of("companies", company), gap, now,
                          touches=touches, min_same_days=min_same)
        if why == "no_reply":
            company_updates.append((company["id"], statuses.props("companies", "closed")))
            result["no_reply"] += 1
            sent_rows.append(f"| {name} | - | Loop finished with no reply: company set to Unqualified |")
            log(f"{name}: the loop is finished with no reply; the company is now Unqualified")
            continue
        if why in ("waiting", "waiting_same_person", "waiting_for_gate_2", "nothing", "stopped"):
            when = due_at(contacts, touches, why, gap, min_same)
            waiting_rows.append(f"| {name} | {NEXT_STEP.get(why, why)} | {ist(when) if when else '-'} |")
        if why == "waiting_for_emails_key":
            result["waiting_for_emails_key"] += 1
            waiting_rows.append(f"| {name} | {NEXT_STEP[why]} | - |")
            continue
        if why == "forward":
            prev = previous_colleague(due, contacts, touches)
            chain = (history.get(prev["id"]) or [None])[-1] if prev else None
            if chain is None or not due["properties"].get(PERSONAL_LINE):
                log(f"{name}: the next person cannot be emailed yet (no earlier email to forward, or no "
                    "personal line); will try again next run")
                continue
            html, text = forward_email(due, props, settings, notes, colleague=_name(prev), original=chain)
            first = min((e for es in history.values() for e in es),
                        key=lambda e: _sent_time(e) or parse_time("2999-01-01"), default=chain)
            emails_api.forward(chain, due["properties"]["email"], forward_subject(first), html, text)
            contact_updates.append((due["id"], statuses.props_or("contacts", "forwarded", "in_outreach")))
            result["forwards_sent"] += 1
            sent_rows.append(f"| {name} | {due['properties'].get('jobtitle') or 'next contact'} | Forward sent, naming "
                             f"the {prev['properties'].get('jobtitle') or 'colleague'} (Lead Status: Forward sent) |")
            log(f"{name}: no reply yet; the chain was forwarded to "
                f"{due['properties'].get('jobtitle') or 'the next contact'}, naming the colleague before them")
            continue
        if why == "reminder":
            past = history.get(due["id"]) or []
            if not past:
                log(f"{name}: could not find person 1's email to reply to; will try again next run")
                continue
            html, text = reminder_email(due, props, settings, notes, mailbox=past[-1].get("eaccount"))
            own = reminder_subject(settings)  # a template with its own subject (follow_up_2, 15 Oct 2026)
            if own:
                emails_api.reply(past[-1], own, html, text, keep_subject=True)
            else:
                emails_api.reply(past[-1], past[0].get("subject") or "", html, text)
            if statuses.has("contacts", "reminded") and forward(statuses.of("contacts", due), "reminded"):
                contact_updates.append((due["id"], statuses.props("contacts", "reminded")))
            result["reminders_sent"] += 1
            sent_rows.append(f"| {name} | {due['properties'].get('jobtitle') or 'person 1'} | Reminder sent, as a reply "
                             "in their own thread (Lead Status: Reminder sent) |")
            log(f"{name}: the loop is done; person 1 was sent their reminder, as a reply in their thread")
            continue
        campaign = last_campaign(contacts)
        if not due or why != "next" or not campaign or not due["properties"].get(PERSONAL_LINE):
            continue
        lead = lead_for(due, props, notes)  # nobody reached yet (e.g. person 1 bounced before sending)
        results = instantly.add_leads(campaign, [lead])
        if sum(r.get("leads_uploaded") or 0 for r in results):
            contact_updates.append((due["id"], statuses.props("contacts", "in_outreach")))
            result["next_contacts_added"] += 1
            sent_rows.append(f"| {name} | {due['properties'].get('jobtitle') or 'next contact'} | Introduction "
                             "(campaign) |")
            log(f"{name}: the introduction goes to {due['properties'].get('jobtitle') or 'the next contact'}")
        else:
            log(f"{name}: {lead['email']} is already in Instantly; not added again")
    hs.update_tagged("contacts", contact_updates)
    hs.update_tagged("companies", company_updates)
    if result["waiting_for_emails_key"]:
        log(f"{result['waiting_for_emails_key']} companies are ready for their next email, but the GitHub secret "
            "INSTANTLY_EMAILS_KEY (Instantly key with scope emails:all) is not set, so those emails wait")
    summary = "## Button 4: what was sent this run\n\n"
    summary += ("| Company | Person (job title) | What happened |\n|---|---|---|\n" + "\n".join(sent_rows)
                if sent_rows else "Nothing was due this run.")
    if waiting_rows:
        summary += ("\n\n## Waiting\n\n| Company | Next | Due |\n|---|---|---|\n" + "\n".join(waiting_rows))
    step_summary(summary)
    log(f"Loop: {result['forwards_sent']} forwards, {result['reminders_sent']} reminders, "
        f"{result['next_contacts_added']} introductions added, {result['replied']} companies replied, "
        f"{result['no_reply']} finished with no reply (now Unqualified)")
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Sync Instantly statuses to HubSpot")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--skip-if-not-configured", action="store_true",
                   help="exit quietly when keys are missing (used by the timer)")
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
        print("Sync skipped: HubSpot or Instantly key not added yet.")
        return 0
    try:
        key = os.environ.get("INSTANTLY_EMAILS_KEY")
        run(args.target, settings, HubSpot(), Instantly(), emails_api=Instantly(api_key=key) if key else None)
    except (PipelineError, HubSpotError, InstantlyError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
