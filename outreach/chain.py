"""Everyone at a company is emailed, each with their own introduction (agreed 2 Nov 2026, Ariel).

    Day 0      introduction to person 1 (the month's campaign)
    Day 3      introduction to person 2, as if they were the first contact (the month's campaign)
    Day 6 ...  the same for every further contact, company inbox last, 3 days apart
    Day 7      person 1's reminder, sent as a forward of their introduction ("Fwd: " + its subject),
               from the mailbox that sent it; everyone gets theirs a week after their own introduction
    3 days after the last reminder with no reply: the company and everyone emailed become
    "Unqualified: Contacted, but no response"

A reply or an opt-out from anyone stops the whole company at once. In HubSpot the company is one unit.

Gate 2: once person 1 is approved (or emailed), everyone else at the company goes to GATE2 by
themselves, and a contact without a personal line gets person 1's line and company note copied over
(fill_lines). A contact still without a line when their turn comes is skipped.

The backlog (run_backlog, the last step of button 4): companies closed as "no response" that still have
someone not yet emailed are reopened, oldest first (by when person 1 was emailed), only in the room the
new introductions leave under the day's limit, at most send.chain.backlog_per_day a day:

    2 or more people   person 2's introduction at once, person 1's reminder 3 days later, person 2's
                       reminder a week after their introduction, then as above
    1 person           person 1's reminder at once; the company closes 7 days later with no reply

Reminders: at most send.chain.reminders_per_mailbox_per_day from each mailbox a day, on top of its 30
introductions (40 at most, within the 50 a day that is safe for cold email); the rest wait for the next run.
data/chain_state.json remembers the reopened companies (IDs and dates only) and the day's counts.
"""

import datetime as dt
import json

from .common import ROOT
from .schema import COMPANY_NOTE, LEAD_STATUS, ORDER, PERSONAL_LINE, STOP_REASON

STATE_FILE = ROOT / "data" / "chain_state.json"


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def today_str(now=None):
    return (now or now_utc()).date().isoformat()


def config(settings):
    """The chain's settings, or None when it is switched off."""
    s = settings["send"]
    c = s.get("chain") or {}
    if not c.get("enabled"):
        return None
    return {"enabled": True, "gap": float(s.get("next_contact_after_days", 3)),
            "reminder": float((s.get("rotation") or {}).get("min_days_same_person", 7)),
            "close": float(s.get("next_contact_after_days", 3)),
            "inbox_reminder": bool(c.get("company_inbox_reminder", True)),
            "backlog_per_day": int(c.get("backlog_per_day", 50)),
            "reminders_per_mailbox": int(c.get("reminders_per_mailbox_per_day", 10)),
            "reminders_by_mailbox": {str(k).strip().lower(): int(v)
                                     for k, v in (c.get("reminders_by_mailbox") or {}).items()},
            "single_close": float(c.get("backlog_single_close_days", 7))}


# ---- What is remembered between runs ---------------------------------------------------------

def load_state(path=None):
    try:
        data = json.loads((path or STATE_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state, path=None):
    path = path or STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _day(state, now=None):
    """The day's counts, started afresh each day."""
    day = today_str(now)
    if (state.get("today") or {}).get("day") != day:
        state["today"] = {"day": day, "backlog": 0, "reminders": {}}
    return state["today"]


def reminders_left(state, mailbox, cfg, now=None):
    key = (mailbox or "").lower()
    used = int(_day(state, now)["reminders"].get(key, 0))
    return (cfg.get("reminders_by_mailbox") or {}).get(key, cfg["reminders_per_mailbox"]) - used


def count_reminder(state, mailbox, now=None):
    counts = _day(state, now)["reminders"]
    key = (mailbox or "").lower()
    counts[key] = int(counts.get(key, 0)) + 1


def company_rules(cfg, state, company_id):
    """The chain settings for one company: a reopened company's reminders wait until 3 days after it was
    reopened (1 person: at once) and a reopened 1-person company closes 7 days after its reminder."""
    rules = dict(cfg)
    entry = (state.get("reopened") or {}).get(str(company_id))
    if entry:
        when = dt.datetime.fromisoformat(entry["at"])
        rules["reminder_not_before"] = when + (dt.timedelta(0) if entry.get("single") else
                                               dt.timedelta(days=cfg["gap"]))
        if entry.get("single"):
            rules["close"] = cfg["single_close"]
    return rules


# ---- Gate 2 for everyone at the company once person 1 is approved -------------------------------

def fill_lines(contacts, statuses, log=print, name=""):
    """When person 1 is approved or emailed, everyone else at the company not yet through gate 2 goes to
    GATE2: their own line if written, otherwise person 1's line and company note copied over. Returns
    [(contact id, props)] to write; the contacts are updated in place (state "approved")."""
    from .next_in_line import rank_of
    from .stages import LEFT_OUT
    # Person 1 was approved: someone is approved or emailed, or was before they left or were redirected.
    gone = [c for c in contacts if statuses.of("contacts", c) in LEFT_OUT]
    if not any(c.get("state") in ("approved", "queued", "sent") for c in contacts) and not gone:
        return []
    # The line of the current person 1 (approved or emailed); a dead or redirected contact's only when nobody
    # else there has one (every line at a company is about the company).
    live = [c for c in sorted(contacts, key=rank_of) if c.get("state") in ("approved", "queued", "sent")
            and (c["properties"].get(PERSONAL_LINE) or "").strip()]
    old = [c for c in sorted(gone, key=rank_of) if (c["properties"].get(PERSONAL_LINE) or "").strip()]
    source = (live or old or [None])[0]
    updates = []
    for c in contacts:
        if c.get("state") != "pending" or not c["properties"].get("email"):
            continue
        if not str(c["properties"].get(ORDER) or "").strip():
            continue  # added by hand and not yet given its place by button 3 (redirect.py puts it first)
        props = dict(statuses.props("contacts", "approved"))
        if not (c["properties"].get(PERSONAL_LINE) or "").strip():
            if source is None:
                continue  # nobody there has a line yet: the mail-writing run writes it
            props[PERSONAL_LINE] = source["properties"].get(PERSONAL_LINE)
            if source["properties"].get(COMPANY_NOTE) and not c["properties"].get(COMPANY_NOTE):
                props[COMPANY_NOTE] = source["properties"].get(COMPANY_NOTE)
        c["properties"].update(props)
        c["state"] = "approved"
        updates.append((c["id"], props))
    if updates:
        log(f"{name}: {len(updates)} more contact(s) there went to GATE2: Approved to send by themselves "
            "(person 1 is approved; lines copied where missing)")
    return updates


def fill_open(hs, settings, statuses, leads=None, log=print):
    """fill_lines for every open company (GATE1, Contact located or Attempted to Contact) that has a contact on
    New or "New, Personal line filled" (3 Nov 2026, Ariel: a contact added later goes to GATE2 by itself, at button 3 or
    button 4, whichever runs first). Returns how many contacts went to GATE2."""
    from .next_in_line import annotate, contacts_by_company, tagged_company_of
    if not config(settings):
        return 0
    waiting = []
    for stage in ("found", "copy_ready"):
        if statuses.has("contacts", stage):
            waiting += hs.tagged_search("contacts", [statuses.filter("contacts", stage)], [ORDER], max_results=2000)
    waiting = [c for c in waiting if str((c.get("properties") or {}).get(ORDER) or "").strip()]
    if not waiting:
        return 0
    owner_of, companies = tagged_company_of(hs, [c["id"] for c in waiting], ["name", LEAD_STATUS])
    open_ids = sorted({cid for cid in owner_of.values()
                       if statuses.of("companies", companies.get(cid) or {}) in ("approved", "located", "in_outreach")})
    if not open_ids:
        return 0
    everyone = contacts_by_company(hs, open_ids)
    updates = []
    for cid in open_ids:
        people = annotate(everyone.get(cid) or [], statuses, leads or {})
        name = ((companies.get(cid) or {}).get("properties") or {}).get("name") or "a company"
        updates += fill_lines(people, statuses, log, name)
    hs.update_tagged("contacts", updates)
    from .corrupt import approved_elsewhere
    approved_elsewhere([cid for cid, _ in updates])  # moved up: still goes at the next run
    return len(updates)


def had_everything(emails_api, people):
    """True when everyone emailed at the company has two emails from us in Instantly (introduction and
    reminder); None when the emails cannot be read."""
    if emails_api is None:
        return None
    try:
        for c in people:
            address = (c["properties"].get("email") or "").lower()
            sent = [e for e in emails_api.thread_emails(address) if e.get("ue_type") in (1, 3)]
            if len(sent) < 2:
                return False
        return True
    except Exception:
        return None


# ---- The backlog -------------------------------------------------------------------------------

def _sent_day(lead):
    from .next_in_line import parse_time
    when = parse_time(lead.get("timestamp_last_contact"))
    return when.date().isoformat() if when else None


def room_today(leads, limit, now=None):
    """How many more introductions fit today: the day's limit less those Instantly already sent today
    and those waiting in the campaigns to be sent."""
    day = today_str(now)
    sent = sum(1 for l in leads.values() if _sent_day(l) == day)
    waiting = sum(1 for l in leads.values() if not l.get("timestamp_last_contact")
                  and l.get("status") not in (-1, -2, -3, 3))
    return max(0, limit - sent - waiting)


REOPENED = "Reopened from the backlog"


def answered(people, leads, blocked, emails_api=None):
    """Why a company must not be reopened, or "": anyone there replied, opted out, was marked in Instantly,
    is on the blocklist or opted out earlier (HubSpot remembers it). A reply is read when the emails key is
    there, so an automatic answer (out of office) does not count; without it any reply counts."""
    from .sync import classify_replies, is_blocked, opted_out_earlier
    for c in people:
        email = (c["properties"].get("email") or "").lower()
        lead = (leads or {}).get(email) or {}
        if opted_out_earlier(c) or is_blocked(email, blocked) or lead.get("status") == -2:
            return "someone there opted out"
        if lead.get("lt_interest_status") not in (None, 0):
            return "someone there was marked in Instantly"
        if (lead.get("email_reply_count") or 0) > 0:
            kind = classify_replies(emails_api, email) if emails_api is not None else None
            if kind != "auto":
                return "someone there replied"
    return ""


def run_backlog(hs, instantly, settings, log=print, now=None, state_path=None, emails_api=None, blocked=None):
    """Reopen companies closed as "no response", oldest first, in the room left today (see the top).
    Returns {"reopened": n, "rows": [...]}."""
    from . import send
    from .next_in_line import annotate, contacts_by_company, instantly_view, is_company_inbox, lead_for, rank_of
    from .stages import LEFT_OUT, LeadStatus
    from .sync import stop_reasons
    out = {"reopened": 0, "rows": []}
    cfg = config(settings)
    if not cfg:
        return out
    now = now or now_utc()
    state = load_state(state_path)
    day = _day(state, now)
    statuses = LeadStatus(hs)
    if not statuses.has("companies", "no_response"):
        return out
    leads = instantly_view(instantly, settings["sync"]["campaign_prefix"])
    room = min(room_today(leads, send.daily_limit_for(settings["send"]), now),
               cfg["backlog_per_day"] - int(day.get("backlog", 0)))
    if room <= 0:
        log("Backlog: no room left today after the new introductions")
        save_state(state, state_path)
        return out
    companies = hs.tagged_search("companies", [statuses.filter("companies", "no_response")],
                                 ["name", "domain", "city", "country", "industry_type", LEAD_STATUS, STOP_REASON],
                                 max_results=5000)
    reopened = state.setdefault("reopened", {})
    # Never twice: the state file remembers, and so does the company's "Outreach stopped because".
    closed_after = state.get("closed") or {}  # 3 Nov 2026: closed after everyone had their emails
    companies = [c for c in companies if str(c["id"]) not in reopened and str(c["id"]) not in closed_after
                 and not str(c["properties"].get(STOP_REASON) or "").startswith(REOPENED)
                 and (c["properties"].get("country") or "").strip()]
    if not companies:
        save_state(state, state_path)
        return out
    everyone = contacts_by_company(hs, [c["id"] for c in companies])
    candidates = []
    for company in companies:
        people = annotate(everyone.get(company["id"]) or [], statuses, leads)
        emailed = [c for c in people if statuses.of("contacts", c) == "no_response" and c.get("sent_at")]
        if not emailed:
            continue
        source = next((c for c in sorted(emailed, key=rank_of)
                       if (c["properties"].get(PERSONAL_LINE) or "").strip()), None)
        waiting = sorted((c for c in people if c not in emailed and c["properties"].get("email")
                          and 1 <= rank_of(c) < 999 and statuses.of("contacts", c) in (
                              "colleague_no_response", "company_unqualified", "found", "copy_ready", "approved")),
                         key=rank_of)
        # Anyone left in a status that stops the company would freeze it once reopened: leave it closed.
        rest = [c for c in people if c not in emailed and c not in waiting]
        stuck = [c for c in rest if c["state"] == "stop" and statuses.of("contacts", c) not in LEFT_OUT]
        if stuck or (not waiting and len(emailed) != 1) or source is None:
            continue
        candidates.append((min(c["sent_at"] for c in emailed), company, emailed, waiting, source, people))
    candidates.sort(key=lambda x: x[0])
    if blocked is None:
        from .sync import read_blocklist
        blocked = read_blocklist(instantly, emails_api, log=lambda *_: None)
    notes = send.load_company_notes()
    bond_config = send.bond.load()
    campaigns = {x["name"]: x["id"] for x in instantly.list_campaigns()}
    contact_updates, company_updates = {}, []
    for when, company, emailed, waiting, source, people in candidates:
        if out["reopened"] >= room:
            break
        cid, name = str(company["id"]), (company["properties"].get("name") or "a company")
        why = answered(people, leads, blocked, emails_api)
        if why:
            log(f"Backlog: {name} is not reopened ({why}); it is left as it is")
            continue
        if not waiting:
            done = had_everything(emails_api, emailed)
            if done is None:  # the emails could not be read: not reopened this time, tried again tomorrow
                log(f"Backlog: {name} is not reopened today (its emails could not be read)")
                continue
            if done:  # 3 Nov 2026: everyone already had both emails
                state.setdefault("closed", {})[cid] = today_str(now)
                continue
        mine = {}  # this company's updates, kept only when it is reopened
        for c in emailed:
            mine[str(c["id"])] = dict(statuses.props("contacts", "in_outreach"))
        for c in waiting:
            props = dict(statuses.props("contacts", "approved"))
            if not (c["properties"].get(PERSONAL_LINE) or "").strip():
                props[PERSONAL_LINE] = source["properties"].get(PERSONAL_LINE)
                if not c["properties"].get(COMPANY_NOTE) and source["properties"].get(COMPANY_NOTE):
                    props[COMPANY_NOTE] = source["properties"].get(COMPANY_NOTE)
            c["properties"].update(props)
            mine[str(c["id"])] = props
        if waiting:
            first = waiting[0]
            try:
                kind = send.kind_for(is_company_inbox(first))
                campaign_name = send.name_for_kind(kind, settings["sync"]["campaign_prefix"], settings["send"])
                campaign_id = campaigns.get(campaign_name)
                if not campaign_id:
                    campaign_id = instantly.create_campaign(send.campaign_body(campaign_name, "", settings, kind))["id"]
                    campaigns[campaign_name] = campaign_id
                    log(f"Created paused campaign: {campaign_name}")
                lead = send.with_bond(lead_for(first, company["properties"], notes), company["properties"], notes,
                                      bond_config)
                results = instantly.add_leads(campaign_id, [lead])
            except Exception as err:  # tried again at the next run; nothing written for this company
                log(f"Backlog: {name}: Instantly refused the introduction ({str(err)[:150]}); tried again next run")
                continue
            if not sum(r.get("leads_uploaded") or 0 for r in results):
                log(f"Backlog: {name}: the next contact is already in Instantly; the company is left as it is")
                continue
            mine[str(first["id"])].update(statuses.props("contacts", "in_outreach"))
            what = (f"{first['properties'].get('jobtitle') or 'next contact'}: introduction added; person 1's "
                    f"reminder in {int(cfg['gap'])} days")
        else:
            what = "only one person: their reminder goes at the next run, the company closes 7 days later"
        contact_updates.update(mine)
        company_updates.append((cid, statuses.props("companies", "in_outreach")))
        reopened[cid] = {"at": now.isoformat(timespec="seconds"), "single": not waiting}
        day["backlog"] = int(day.get("backlog", 0)) + 1
        out["reopened"] += 1
        out["rows"].append(f"| {name} | {when.date().isoformat()} | {what} |")
        log(f"Backlog: {name} reopened ({what})")
    save_state(state, state_path)  # first, so a company is never reopened twice even if HubSpot fails below
    hs.update_tagged("contacts", list(contact_updates.items()))
    hs.update_tagged("companies", company_updates)
    stop_reasons(hs, "companies", [(cid, f"{REOPENED} ({now.strftime('%d %b %Y').lstrip('0')}): the next contact "
                                         "is emailed") for cid, _ in company_updates], log)
    if out["rows"]:
        send.step_summary("## Button 4: backlog reopened this run\n\n| Company | Person 1 emailed | What happens |\n"
                          "|---|---|---|\n" + "\n".join(out["rows"]))
    return out


def main(argv=None):
    import argparse
    import os
    import sys
    from .common import PipelineError, check_target, load_settings
    from .hubspot_client import HubSpot, HubSpotError
    from .instantly_client import Instantly, InstantlyError
    p = argparse.ArgumentParser(description="Reopen the backlog of companies closed as no response")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--skip-if-not-configured", action="store_true")
    args = p.parse_args(argv)
    if args.skip_if_not_configured and not (os.environ.get("HUBSPOT_TOKEN") and os.environ.get("INSTANTLY_API_KEY")):
        print("Backlog skipped: a key it needs is not added yet.")
        return 0
    try:
        settings = load_settings()
        hs = HubSpot()
        check_target(hs, args.target)
        key = os.environ.get("INSTANTLY_EMAILS_KEY")
        run_backlog(hs, Instantly(), settings, emails_api=Instantly(api_key=key) if key else None)
    except (PipelineError, HubSpotError, InstantlyError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
