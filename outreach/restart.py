"""Restarting companies where nobody replied (agreed 19 Nov 2026, Ariel; switched on with restart.enabled in
config/settings.yaml). No new button: button 3, button 4 and the daily email do it.

    The end      A company where nobody replied ends on "No response: can restart" (stages.RESTART_LABEL), its
                 people who were emailed too (button 4, sync.py), and "Last closed on" gets the date. The people
                 there who were not emailed keep "Unqualified: Colleague Contacted, but no response".
    Switching on The companies still on "Unqualified: Contacted, but no response", and the contacts on it, move
                 to "No response: can restart" once (migrate); the date each company got there is kept.
    A restart    A person sets such a company back to GATE1. At its next run, button 3 (plan, then finish):
                 - waits until restart.wait_days_after_close days after "Last closed on" (9 days);
                 - refuses the whole company when anyone there replied, said no, opted out or was passed to the
                   sales team (their colleagues keep "Colleague replied" and so on);
                 - searches Apollo for restart.new_people more people (3; about 1 credit an email revealed);
                 - gives the new people send order 1, 2, 3 and the earlier people the places after them (the
                   company inbox last, or first when the company has no named people);
                 - puts everyone who can be emailed on GATE2: Approved to send at once (the same email as before;
                   a new person gets the line an earlier person had, as at any company); never anyone who
                   bounced, opted out, said no, was redirected or was rejected at GATE2;
                 - sets the company to "Contact located. Queued for processing" and "Outreach round" one higher.
    Button 4     sends the round under the chain rules of 17 Nov 2026, in this month's "Diablo | RESTART | <MONTH>"
                 campaigns (send.py; Instantly may hold the same address in an earlier campaign, so these add
                 a lead unless it is already in that campaign), never to an address that bounced anywhere in
                 Instantly, and keeps the counters (update_counters).

    Automatic    20 Nov 2026 (Ariel, restart.automatic): button 3 sets such a company to GATE1 by itself once its
                 wait is over (auto_queue) and starts it in the same run, exactly as above. Fresh companies go
                 first: in button 3 they get the Apollo credits first, in button 4 the day's room first.
    The limit    At most restart.max_rounds rounds in total (3), the first outreach included. A company that ends
                 its last round with no reply gets "Unqualified: Contacted, but no response" (sync.py), its no-reply
                 contacts too, and is never emailed again; one set to GATE1 by mistake is put back on it (plan).

data/restarts.json remembers each company's round and when it started (company and contact IDs and times only), and
the day the companies were first moved to "No response: can restart" ("migrated"), so that move happens once.
"""

import datetime as dt
import json

from .common import ROOT
from .schema import (COMPANY_NOTE, INTROS_SENT, LAST_CLOSED, LEAD_STATUS, ORDER, PERSONAL_LINE, REMINDERS_SENT,
                     ROUND, TIMES_INTRODUCED, TIMES_REMINDED)
from .stages import TEAM

FILE = ROOT / "data" / "restarts.json"
# Anyone at the company with one of these stops the whole restart: someone there answered, or a person took it over.
REPLY_STAGES = ("replied", "sales", "said_no", "opted_out", "colleague_positive", "colleague_negative",
                "colleague_replied", "colleague_opted_out", TEAM)
# The earlier people who are emailed again (anyone else there is left as they are).
EARLIER = ("no_response", "colleague_no_response", "found", "copy_ready", "approved")


def config(settings):
    """The restart settings, or None while restarts are switched off."""
    r = settings.get("restart") or {}
    if not r.get("enabled"):
        return None
    return {"wait_days": int(r.get("wait_days_after_close", 9)), "new_people": int(r.get("new_people", 3)),
            "word": word(settings), "automatic": bool(r.get("automatic")),
            "max_rounds": int(r.get("max_rounds") or 0)}


def finished(props, cfg):
    """True when the company has had every round it may have (restart.max_rounds; 0 means no limit)."""
    return bool(cfg and cfg.get("max_rounds")) and round_of(props) >= cfg["max_rounds"]


def word(settings):
    return str((settings.get("restart") or {}).get("campaign_word") or "RESTART")


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def load(path=None):
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("companies", {})
    return data


def save(data, path=None):
    path = path or FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def round_of(props):
    """The company's round (1 when the field is empty)."""
    try:
        return max(1, int(float(str((props or {}).get(ROUND)))))
    except (TypeError, ValueError):
        return 1


def _date(value):
    try:
        return dt.date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def migrate(hs, statuses, log=print, now=None, data=None):
    """Once restarts are on: the companies and contacts still on "Unqualified: Contacted, but no response" move to
    "No response: can restart", each company with the date it got there as "Last closed on". Nobody is emailed.
    Only once (data["migrated"]): afterwards that status means a company that used all its rounds (20 Nov 2026).
    Returns {"companies": n, "contacts": n}."""
    out = {"companies": 0, "contacts": 0}
    if not statuses.restart:
        return out
    if data is not None and data.get("migrated"):
        return out
    now = now or now_utc()
    if data is not None:
        data["migrated"] = now.date().isoformat()
    for obj in ("companies", "contacts"):
        values = statuses.values(obj, "no_response")
        if len(values) < 2:
            log(f'The {obj[:-1]} Lead Status choice "No response: can restart" is missing; run button 1 to add it.')
            return out
        new, old = values[0], values[1]
        rows = hs.tagged_search(obj, [{"propertyName": LEAD_STATUS, "operator": "EQ", "value": old}],
                                ["name", LAST_CLOSED], max_results=10000)
        if not rows:
            continue
        when = {}
        if obj == "companies":
            past = hs.history("companies", [r["id"] for r in rows], LEAD_STATUS)
            for cid, (_, history) in past.items():
                times = [t for v, t in history if str(v) == str(old) and t]
                if times:
                    when[str(cid)] = str(times[0])[:10]  # newest first: when it last got there
        updates = []
        for r in rows:
            props = {LEAD_STATUS: new}
            if obj == "companies" and not (r.get("properties") or {}).get(LAST_CLOSED):
                props[LAST_CLOSED] = when.get(str(r["id"])) or now.date().isoformat()
            updates.append((r["id"], props))
        hs.update_tagged(obj, updates)
        out[obj] = len(updates)
    if out["companies"] or out["contacts"]:
        log(f'Restarts switched on: {out["companies"]} companies and {out["contacts"]} contacts moved from '
            '"Unqualified: Contacted, but no response" to "No response: can restart" (nobody was emailed)')
    return out


def pending(company, data):
    """True when the company is on GATE1 after closing with no reply, and its new round has not started yet."""
    last = _date((company.get("properties") or {}).get(LAST_CLOSED))
    if last is None:
        return False
    rec = (data.get("companies") or {}).get(str(company["id"])) or {}
    started = _date(rec.get("started"))
    return started is None or started < last


def plan(hs, settings, statuses, approved, log=print, now=None, data=None):
    """Sorts the approved companies that wait for a restart. Returns {"start": [(company, its contacts)],
    "wait": [(name, allowed from)], "refused": [(name, why)], "skip": {company IDs button 3 leaves alone}}."""
    from .next_in_line import contacts_by_company
    out = {"start": [], "wait": [], "refused": [], "skip": set()}
    cfg = config(settings)
    if not cfg:
        return out
    now = now or now_utc()
    data = data if data is not None else load()
    mine = [c for c in approved if statuses.of("companies", c) == "approved" and pending(c, data)]
    if not mine:
        return out
    everyone = contacts_by_company(hs, [c["id"] for c in mine])
    for company in mine:
        cid = str(company["id"])
        name = (company.get("properties") or {}).get("name") or "A company"
        out["skip"].add(cid)
        allowed = _date(company["properties"].get(LAST_CLOSED)) + dt.timedelta(days=cfg["wait_days"])
        people = everyone.get(cid) or []
        answered = [c for c in people if statuses.of("contacts", c) in REPLY_STAGES]
        if finished(company.get("properties"), cfg):  # 20 Nov 2026: every round used; back to the final status
            hs.update_tagged("companies", [(company["id"], statuses.final("companies"))])
            out["refused"].append((name, f"it has had all {cfg['max_rounds']} rounds"))
            log(f'{name}: not restarted: it has had all {cfg["max_rounds"]} rounds, so it is back on "Unqualified: '
                'Contacted, but no response" and is never emailed again')
        elif answered:
            out["refused"].append((name, "someone there replied, said no, opted out or was passed to the sales team"))
            log(f"{name}: not restarted: someone there replied, said no, opted out or was passed to the sales team, "
                "so nobody there is emailed again")
        elif now.date() < allowed:
            out["wait"].append((name, allowed.isoformat()))
            log(f"{name}: waiting to restart: allowed from {allowed.isoformat()} ({cfg['wait_days']} days after it "
                "closed)")
        else:
            out["start"].append((company, people))
    return out


def round_starts(data=None):
    """{company id: when its current round started} for every restarted company (data/restarts.json)."""
    from .next_in_line import parse_time
    data = load() if data is None else data
    out = {}
    for cid, rec in (data.get("companies") or {}).items():
        when = parse_time(rec.get("started"))
        if when:
            out[str(cid)] = when
    return out


def this_round(touches, started):
    """20 Nov 2026: a restarted company's emails from earlier rounds do not count for this round's reminder, the
    48-hour close or the company's close: only the emails sent since its round started are kept."""
    if touches is None or started is None:
        return touches
    return {k: [t for t in v if t and t >= started] for k, v in touches.items()}


def auto_queue(hs, settings, statuses, props, log=print, now=None):
    """20 Nov 2026 (Ariel): with restart.automatic on, every AUTO-OUTREACH company on "No response: can restart" whose
    wait is over, that has rounds left and where nobody replied, is set to GATE1, as a person would do by hand.
    The oldest closed go first. Returns those companies (their Lead Status already GATE1 in hand), so the same run
    starts them even before HubSpot's search shows the change."""
    from .next_in_line import contacts_by_company
    cfg = config(settings)
    if not cfg or not cfg["automatic"] or not statuses.restart:
        return []
    alias = statuses.values("companies", "no_response")[0]
    now = now or now_utc()
    rows = hs.tagged_search("companies", [{"propertyName": LEAD_STATUS, "operator": "EQ", "value": alias}],
                            list(dict.fromkeys(list(props) + ["name", LEAD_STATUS, LAST_CLOSED, ROUND])),
                            max_results=10000)
    ready, later = [], 0
    for c in rows:
        p = c.get("properties") or {}
        last = _date(p.get(LAST_CLOSED))
        if last is None or finished(p, cfg):
            continue  # no date to count from, or every round used (sync.py ends those for good)
        if now.date() < last + dt.timedelta(days=cfg["wait_days"]):
            later += 1
            continue
        ready.append(c)
    if not ready:
        if later:
            log(f"Automatic restarts: none ready yet; {later} companies wait for their {cfg['wait_days']} days")
        return []
    everyone = contacts_by_company(hs, [c["id"] for c in ready])
    queued, gate1 = [], statuses.props("companies", "approved")
    for c in sorted(ready, key=lambda c: (str(c["properties"].get(LAST_CLOSED)), str(c["id"]))):
        name = c["properties"].get("name") or "A company"
        if any(statuses.of("contacts", x) in REPLY_STAGES for x in everyone.get(str(c["id"])) or []):
            log(f"{name}: not restarted automatically: someone there replied, said no, opted out or was passed to "
                "the sales team")
            continue
        c["properties"].update(gate1)
        queued.append(c)
    hs.update_tagged("companies", [(c["id"], dict(gate1)) for c in queued])
    log(f"Automatic restarts: {len(queued)} companies set to GATE1 (their {cfg['wait_days']} days are over)"
        + (f"; {later} more wait for their date" if later else ""))
    return queued


def finish(hs, statuses, company, people, created_ids, log=print, now=None, data=None):
    """Starts the new round at one company: the send order (new people first), GATE2 for everyone who can be
    emailed, the company on "Contact located" and its round one higher. Returns the contact IDs put on GATE2."""
    from .next_in_line import CONTACT_PROPS, is_company_inbox, rank_of
    now = now or now_utc()
    data = data if data is not None else load()
    cid = str(company["id"])
    props = company.get("properties") or {}
    name = props.get("name") or "A company"
    created = hs.tagged_read("contacts", [str(i) for i in created_ids], CONTACT_PROPS) if created_ids else []
    earlier = [c for c in people if statuses.of("contacts", c) in EARLIER]
    new_people = sorted((c for c in created if not is_company_inbox(c)), key=rank_of)
    old_people = sorted((c for c in earlier if not is_company_inbox(c)), key=rank_of)
    inboxes = sorted((c for c in earlier + created if is_company_inbox(c)), key=rank_of)
    named = new_people + old_people
    ordered = named + inboxes  # the company inbox last, or first when there is nobody named (19 Oct 2026 rule)
    source = next((c for c in sorted(earlier, key=rank_of)
                   if (c["properties"].get(PERSONAL_LINE) or "").strip()), None)
    updates, approved, writing = [], [], []
    for i, c in enumerate(ordered, start=1):
        p = c.get("properties") or {}
        change = {ORDER: str(i)}
        if (p.get(PERSONAL_LINE) or "").strip():
            change.update(statuses.props("contacts", "approved"))
        elif source is not None:  # the same email as before: the earlier person's line and company note
            change.update(statuses.props("contacts", "approved"))
            change[PERSONAL_LINE] = source["properties"].get(PERSONAL_LINE)
            if source["properties"].get(COMPANY_NOTE) and not p.get(COMPANY_NOTE):
                change[COMPANY_NOTE] = source["properties"].get(COMPANY_NOTE)
        else:  # nobody there has a line: the mail-writing run writes it, then it goes straight to GATE2
            change.update(statuses.props("contacts", "found"))
            writing.append(str(c["id"]))
        if LEAD_STATUS in change and change[LEAD_STATUS] == statuses.props("contacts", "approved")[LEAD_STATUS]:
            approved.append(str(c["id"]))
        updates.append((c["id"], change))
    new_round = round_of(props) + 1
    hs.update_tagged("contacts", updates)
    company_change = {ROUND: str(new_round)}
    if ordered:
        company_change.update(statuses.props_or("companies", "located", "approved"))
    hs.update_tagged("companies", [(company["id"], company_change)])
    data.setdefault("companies", {})[cid] = {"round": new_round, "started": now.isoformat(timespec="seconds"),
                                             "straight": writing}
    if ordered:
        log(f"{name}: restarted (round {new_round}): {len(new_people)} new people first, then {len(old_people)} "
            f"earlier people" + (f" and {len(inboxes)} company inbox(es)" if inboxes else "")
            + f"; {len(approved)} on GATE2: Approved to send")
    else:
        log(f"{name}: round {new_round} could not start: nobody there can be emailed and Apollo found nobody new")
    return approved


def straight_to_gate2(contact_id, data=None):
    """True for a person at a restarted company whose line was still to be written (import_lines puts them on GATE2)."""
    data = data if data is not None else load()
    return any(str(contact_id) in (rec.get("straight") or []) for rec in (data.get("companies") or {}).values())


def restarted_on(day, data=None, india=None):
    """How many companies had a new round started on this India date (YYYY-MM-DD)."""
    data = data if data is not None else load()
    n = 0
    for rec in (data.get("companies") or {}).values():
        try:
            when = dt.datetime.fromisoformat(rec.get("started"))
        except (TypeError, ValueError):
            continue
        if (when.astimezone(india) if india else when).date().isoformat() == day:
            n += 1
    return n


def counts(memory):
    """({contact ID: (introductions, reminders)}, {company ID: (introductions, reminders)}) over every round,
    from button 4's memory."""
    people, companies = {}, {}
    for cid, rec in (memory.get("contacts") or {}).items():
        rounds = list(rec.get("past") or []) + [rec]
        intro = sum(1 for r in rounds if r.get("introduced") or r.get("queued"))
        rem = sum(1 for r in rounds if r.get("reminded"))
        if not intro and not rem:
            continue
        people[cid] = (intro, rem)
        comp = rec.get("company")
        if comp:
            a, b = companies.get(comp, (0, 0))
            companies[comp] = (a + intro, b + rem)
    return people, companies


def update_counters(hs, memory, log=print):
    """Writes "Times introduced" and "Times reminded" on each person, and "Introductions sent", "Reminders sent" and
    "Outreach round" (1 when empty) on each company, where they changed. Returns how many records changed."""
    people, companies = counts(memory)
    changed = 0
    for obj, table, fields in (("contacts", people, (TIMES_INTRODUCED, TIMES_REMINDED)),
                               ("companies", companies, (INTROS_SENT, REMINDERS_SENT))):
        if not table:
            continue
        rows = hs.tagged_read(obj, list(table), list(fields) + ([ROUND] if obj == "companies" else []))
        updates = []
        for r in rows:
            p = r.get("properties") or {}
            want = dict(zip(fields, (str(n) for n in table[str(r["id"])])))
            if obj == "companies" and not str(p.get(ROUND) or "").strip():
                want[ROUND] = "1"
            diff = {k: v for k, v in want.items() if str(p.get(k) or "").split(".")[0] != v}
            if diff:
                updates.append((r["id"], diff))
        hs.update_tagged(obj, updates)
        changed += len(updates)
    if changed:
        log(f"Approach counters brought up to date on {changed} records")
    return changed
