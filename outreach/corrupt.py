"""Dead addresses: the problem is the contact, not the company (agreed 28 Oct 2026, Ariel).

At every run of button 4, after Instantly's results are copied to HubSpot (sync.run), each contact
whose email bounced, and each contact whose automatic reply says they have left, is checked once:

    What happened                                   The contact
    A hard bounce: the address does not exist or    "Unqualified Contact: Contact corrupt", Outreach
      the mailbox is no longer used                   order 0, "Outreach stopped because" says why
    An automatic reply saying they have left the    the same
      company or the mailbox is no longer read
    Any other bounce (a full mailbox, a server       left as it is today (Unqualified); listed on the
      problem)                                         run's summary page
    A bounce whose message cannot be read            left as it is today; listed on the summary page
                                                       to be checked by hand

A company inbox (info@, sales@) with a dead address gets the same contact label. Then, at its company:
  - everyone below moves up one (2 becomes 1, 3 becomes 2, ...);
  - the new number 1 becomes "GATE2: Approved to send" when its personal line is written, or as soon
    as the line arrives (import_lines); its introduction goes at the NEXT run of button 4, never in
    the same run (data/promoted.json remembers who moved up and in which run);
  - when nobody is left to email, the company goes back to "GATE1: Approved for outreach" so button 3
    looks for new people at its next monthly check, or, when the dead address was its company inbox,
    to "Invalid inbox: Mail bounced, need input" for a person to add a working address;
  - a company closed as "no response" only because its contact bounced (before 28 Oct 2026) is put
    right the same way.
A dead contact stays in HubSpot, so button 3 never adds the same address again. Only AUTO-OUTREACH
records are touched, and a Lead Status a person set by hand is never changed.
"""

import datetime as dt
import json
import os
import re

from .common import ROOT, step_summary
from .next_in_line import (CONTACT_PROPS, annotate, contacts_by_company, is_company_inbox, parse_time, rank_of,
                           tagged_company_of)
from .schema import LEAD_STATUS, ORDER, PERSONAL_LINE, STOP_REASON
from .stages import EMAILED

PROMOTED_FILE = ROOT / "data" / "promoted.json"
HOLD_MINUTES = 60  # without a GitHub run number, someone approved this recently waits for the next run
DONE_PREFIXES = ("contact corrupt", "email bounced")  # "Outreach stopped because": already checked

# The bounce says the address is dead (address unknown, mailbox closed or no longer used).
DEAD = re.compile(
    r"(user unknown|unknown user|no such (user|mailbox|recipient|address)|user not found|recipient not found|"
    r"unknown recipient|recipient (address )?rejected|address (was )?not found|address couldn'?t be found|"
    r"(doesn'?t|does not|did not) exist|mailbox (not found|unavailable|disabled|inactive|is disabled|"
    r"has been disabled|is inactive|no longer)|account (has been |is )?(disabled|deactivated|closed|suspended|"
    r"inactive)|no longer (in use|active|valid|exists|available)|invalid (recipient|mailbox|address)|"
    r"\b5\.1\.1\b|\b5\.1\.10\b|\b5\.2\.1\b|\b5\.1\.6\b|"
    r"empf[äa]nger (unbekannt|nicht gefunden)|existiert nicht|unbekannte(r)? empf[äa]nger|"
    r"adresse (introuvable|inconnue)|destinataire inconnu|n'existe pas)", re.I)
# An email that is a bounce notice (from the mail system, not a person).
NOTICE_SENDER = re.compile(r"(mailer-daemon|postmaster|mail delivery (sub)?system|microsoftexchange)", re.I)
NOTICE_SUBJECT = re.compile(
    r"(undeliver|delivery status notification|delivery (has )?failed|mail delivery failed|returned mail|"
    r"failure notice|could not be delivered|non[- ]?delivery|unzustellbar|nicht zustellbar|"
    r"zustellung fehlgeschlagen|non remis|non distribu)", re.I)
# An automatic reply saying the person has gone, or the mailbox is no longer read.
LEFT = re.compile(
    r"(no longer (with|at|employed|working|works|work for|part of)|(has|have) left (the|our|this) "
    r"(company|business|organi[sz]ation|team)|left the company|"
    r"(mailbox|e-?mail address|address|inbox|account) is no longer (monitored|in use|active|used|valid|read)|"
    r"no longer (monitored|in use)|"
    r"nicht mehr (im unternehmen|bei uns|f[üu]r uns|t[äa]tig|besetzt|aktiv|in benutzung|genutzt|gelesen|"
    r"abgerufen)|(hat|haben) (das unternehmen|uns|die firma) verlassen|ausgeschieden|"
    r"ne fait plus partie|a quitt[ée])", re.I)


def today():
    return dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y").lstrip("0")


# ---- Who moved up, so the new number 1 waits for the next run ---------------------------------

def load_promoted(path=None):
    try:
        data = json.loads((path or PROMOTED_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_promoted(data, path=None):
    path = path or PROMOTED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(data.items())), indent=1) + "\n", encoding="utf-8")


def run_id():
    return os.environ.get("GITHUB_RUN_ID", "")


def held_now(contact_id, promoted=None, now=None):
    """True when this contact was approved by this very run after moving up (it goes at the next run)."""
    entry = (load_promoted() if promoted is None else promoted).get(str(contact_id))
    if not entry or not entry.get("approved_run_at"):
        return False
    here = run_id()
    if here and entry.get("approved_run"):
        return entry["approved_run"] == here
    when = parse_time(entry["approved_run_at"])
    now = now or dt.datetime.now(dt.timezone.utc)
    return bool(when) and now - when < dt.timedelta(minutes=HOLD_MINUTES)


def waiting_for_line(contact_id, promoted=None):
    """True when this contact moved up and becomes GATE2 as soon as its personal line arrives."""
    entry = (load_promoted() if promoted is None else promoted).get(str(contact_id))
    return bool(entry) and not entry.get("approved_run_at")


def _approved_now(promoted, contact_id):
    promoted[str(contact_id)] = dict(promoted.get(str(contact_id)) or {}, approved_run=run_id(),
                                     approved_run_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))


# ---- Reading the bounce ----------------------------------------------------------------------

def _full_text(email):
    body = email.get("body") or {}
    if isinstance(body, str):
        text = body
    else:
        text = body.get("text") or re.sub(r"<[^>]+>", " ", body.get("html") or "")
    return " ".join([str(email.get("subject") or ""), text or "", str(email.get("content_preview") or "")])


def _is_notice(email):
    sender = str(email.get("from_address_email") or "")
    return bool(NOTICE_SENDER.search(sender) or NOTICE_SUBJECT.search(str(email.get("subject") or "")))


def bounce_text(lead, thread, emails_api=None):
    """Everything that says why the email bounced: Instantly's own fields on the lead and any bounce
    notice in the address's emails. "" when nothing can be read."""
    parts = [str(v) for k, v in (lead or {}).items()
             if v and any(w in k.lower() for w in ("bounce", "esp", "error", "status_summary", "reason"))]
    for e in thread or []:
        if e.get("ue_type") in (1, 3) or not _is_notice(e):
            continue
        if emails_api is not None and not (e.get("body") or {}):
            full = emails_api.get_email(e["id"]) if (e.get("id") and hasattr(emails_api, "get_email")) else None
            e = {**e, **full} if full else e
        parts.append(_full_text(e))
    return " ".join(p for p in parts if p.strip())


def kind_of_bounce(text):
    """ "dead" (the address does not exist or is no longer used), "other" or "unreadable"."""
    if not (text or "").strip():
        return "unreadable"
    return "dead" if DEAD.search(text) else "other"


def has_left(thread):
    """True when an automatic reply in the thread says the person has left or the mailbox is not read."""
    for e in thread or []:
        if e.get("ue_type") == 2 and not _is_notice(e) and LEFT.search(_full_text(e)):
            return True
    return False


# ---- The check at each run of button 4 --------------------------------------------------------

def _done(contact):
    return str((contact.get("properties") or {}).get(STOP_REASON) or "").strip().lower().startswith(DONE_PREFIXES)


def check(hs, emails_api, leads, statuses, seen=(), log=print, promoted_path=None):
    """Find dead addresses and move each company on. Returns {"corrupt": n, "rows": [...], "to_check": [...]}."""
    from .sync import stop_reasons  # sync imports this module
    out = {"corrupt": 0, "rows": [], "to_check": []}
    if not statuses.has("contacts", "corrupt"):
        log('The contact Lead Status choice "Unqualified Contact: Contact corrupt" is missing; run button 1 to add '
            "it. Dead addresses were not checked this run.")
        return out
    promoted = load_promoted(promoted_path)
    _approve_waiting(hs, statuses, promoted, log)
    if emails_api is None:
        log("Dead addresses were not checked: the GitHub secret INSTANTLY_EMAILS_KEY is needed to read the bounces")
        save_promoted(promoted, promoted_path)
        return out
    bounced = {e: l for e, l in (leads or {}).items() if l.get("status") == -1}
    rows = hs.tagged_read("contacts", list(bounced), CONTACT_PROPS, id_property="email") if bounced else []
    reasons, corrupt = [], {}  # corrupt: {contact id: (record, why)}
    for r in rows:
        if statuses.of("contacts", r) not in EMAILED + ("closed",) or _done(r):
            continue
        email = (r["properties"].get("email") or "").lower()
        try:
            thread = emails_api.thread_emails(email)
        except Exception as err:  # read again next run
            log(f"The bounce of a {r['properties'].get('jobtitle') or 'contact'} could not be read "
                f"({str(err)[:150]}); tried again next run")
            continue
        kind = kind_of_bounce(bounce_text(bounced.get(email), thread, emails_api))
        if kind == "dead":
            corrupt[str(r["id"])] = (r, f"Contact corrupt: email bounced, the address does not exist or is no "
                                        f"longer used ({today()})")
        else:
            why = ("not a dead address (for example a full mailbox), so left as Unqualified" if kind == "other"
                   else "the reason could not be read, check by hand")
            reasons.append((r["id"], f"Email bounced ({today()}): {why}"))
            out["to_check"].append((r, why))
    for r, _lead, event in seen or ():
        if event != "out of office" or str(r["id"]) in corrupt or _done(r):
            continue
        if statuses.of("contacts", r) not in EMAILED + ("closed",):
            continue
        try:
            thread = emails_api.thread_emails((r["properties"].get("email") or "").lower())
        except Exception:
            continue
        if has_left(thread):
            corrupt[str(r["id"])] = (r, f"Contact corrupt: an automatic reply says they have left or the mailbox "
                                        f"is no longer read ({today()})")
    stop_reasons(hs, "contacts", reasons, log)
    if corrupt:
        _move_up(hs, statuses, corrupt, leads, promoted, out, log)
    save_promoted(promoted, promoted_path)
    _summary(out)
    return out


def _move_up(hs, statuses, corrupt, leads, promoted, out, log):
    from .sync import stop_reasons
    value = statuses.props("contacts", "corrupt")
    hs.update_tagged("contacts", [(cid, {**value, ORDER: "0"}) for cid in corrupt])
    stop_reasons(hs, "contacts", [(cid, why) for cid, (_, why) in corrupt.items()], log)
    out["corrupt"] += len(corrupt)
    owner_of, companies = tagged_company_of(hs, list(corrupt), ["name", LEAD_STATUS])
    by_company = {}
    for cid in corrupt:
        if owner_of.get(cid):
            by_company.setdefault(owner_of[cid], []).append(cid)
    everyone = contacts_by_company(hs, list(by_company)) if by_company else {}
    contact_updates, company_updates = [], []
    for company_id, dead in by_company.items():
        company = companies.get(company_id) or {}
        name = (company.get("properties") or {}).get("name") or "a company"
        people = annotate(everyone.get(company_id) or [], statuses, leads or {})
        dead_inbox = any(is_company_inbox(corrupt[c][0]) for c in dead)
        rest = [c for c in people if str(c["id"]) not in corrupt and c["state"] != "skipped"]
        for c in dead:
            r = corrupt[c][0]
            out["rows"].append(f"| {name} | {r['properties'].get('jobtitle') or 'contact'} | "
                               f"{corrupt[c][1].split(' (')[0]} |")
        # Everyone below moves up one: the numbers of those still in the loop become 1, 2, 3 ...
        ranked = sorted((c for c in rest if 1 <= rank_of(c) < 999), key=rank_of)
        for i, c in enumerate(ranked, start=1):
            if rank_of(c) != i:
                contact_updates.append((c["id"], {ORDER: str(i)}))
                c["properties"][ORDER] = str(i)
        first = ranked[0] if ranked else None
        if first is not None and first["state"] in ("pending", "approved"):
            stage = statuses.of("contacts", first)
            title = first["properties"].get("jobtitle") or "the next contact"
            promoted[str(first["id"])] = {"moved_up": today()}
            if stage == "approved" or (stage == "copy_ready" and first["properties"].get(PERSONAL_LINE)):
                if stage != "approved":
                    contact_updates.append((first["id"], statuses.props("contacts", "approved")))
                _approved_now(promoted, first["id"])
                out["rows"].append(f"| {name} | {title} | Now number 1 and GATE2: Approved to send; the "
                                   "introduction goes at the next run |")
            else:
                out["rows"].append(f"| {name} | {title} | Now number 1; becomes GATE2 as soon as its personal "
                                   "line is written |")
            log(f"{name}: a dead address; {title} is now number 1")
        usable = [c for c in rest if c["state"] in ("pending", "approved", "queued", "sent")]
        stage = statuses.of("companies", company) if company else "team"
        if not usable and stage in ("", "approved", "in_outreach", "no_response"):
            if dead_inbox and statuses.has("companies", "invalid_inbox"):
                company_updates.append((company_id, statuses.props("companies", "invalid_inbox")))
                stop_reasons(hs, "companies", [(company_id, f"Company inbox bounced, needs a working address "
                                                            f"({today()})")], log)
                out["rows"].append(f"| {name} | - | Company: Invalid inbox: Mail bounced, need input |")
                log(f'{name}: its company inbox bounced and nobody is left; the company is now "Invalid inbox: '
                    'Mail bounced, need input"')
            else:
                company_updates.append((company_id, statuses.props("companies", "approved")))
                _company_reason(hs, company_id, f"Back to GATE1 ({today()}): its contacts' addresses are dead; "
                                                "button 3 looks for new people", log)
                out["rows"].append(f"| {name} | - | Company back to GATE1: button 3 looks for new people at its "
                                   "next monthly check |")
                log(f"{name}: nobody is left to email; the company is back on GATE1 for new people")
        elif usable and stage == "no_response" and not any(c["state"] == "sent" for c in usable):
            company_updates.append((company_id, statuses.props("companies", "in_outreach")))
            out["rows"].append(f"| {name} | - | Company back in outreach (it was closed only because of the "
                               "bounce) |")
    hs.update_tagged("contacts", contact_updates)
    hs.update_tagged("companies", company_updates)


def _company_reason(hs, company_id, text, log):
    try:
        if hs.has_property("companies", STOP_REASON):
            hs.update_tagged("companies", [(company_id, {STOP_REASON: text[:250]})])
    except Exception as err:
        log(f"Could not write why the company went back to GATE1: {str(err)[:200]}")


def _approve_waiting(hs, statuses, promoted, log):
    """Who moved up earlier and was waiting for a personal line: GATE2 now if the line has arrived (in
    case the import missed it); entries no longer needed are dropped."""
    if not promoted:
        return
    current = {str(c["id"]): c for c in hs.tagged_read("contacts", list(promoted), [LEAD_STATUS, PERSONAL_LINE])}
    updates = []
    for cid, entry in list(promoted.items()):
        c = current.get(cid)
        stage = statuses.of("contacts", c) if c else None
        if stage == "copy_ready" and not entry.get("approved_run_at") and c["properties"].get(PERSONAL_LINE):
            updates.append((cid, statuses.props("contacts", "approved")))
            _approved_now(promoted, cid)  # approved by this run, so it goes at the next one
        elif stage in ("found", "copy_ready") or (stage == "approved" and held_now(cid, promoted)):
            continue  # still waiting for its line, or approved by this very run
        else:
            del promoted[cid]  # its turn has come (or a person has taken it over): nothing more to remember
    if updates:
        hs.update_tagged("contacts", updates)
        log(f"{len(updates)} contact(s) that moved up after a dead address now have their personal line and are on "
            "GATE2; their introduction goes at the next run")


def _summary(out):
    text = ""
    if out["rows"]:
        text += ("## Dead addresses (Unqualified Contact: Contact corrupt)\n\n| Company | Person (job title) | "
                 "What happened |\n|---|---|---|\n" + "\n".join(out["rows"]) + "\n\n")
    if out["to_check"]:
        text += ("## Bounces left as they are\n\n| Person (job title) | Why |\n|---|---|\n"
                 + "\n".join(f"| {r['properties'].get('jobtitle') or 'contact'} | {why} |"
                             for r, why in out["to_check"]) + "\n\n")
    if text:
        step_summary(text)
