"""Dead addresses: the problem is the contact, not the company (agreed 28 Oct 2026, Ariel).

At every run of button 4, after Instantly's results are copied to HubSpot (sync.run), each contact
whose email bounced, and each contact whose automatic reply says they have left, is checked once:

    What happened                                   The contact
    A hard bounce: the address does not exist or    "Unqualified: Contact corrupt", Outreach order 0,
      the mailbox is no longer used                   "Outreach stopped because" says why
    An automatic reply saying they have left the    the same
      company or the mailbox is no longer read
    Any other bounce (a full mailbox, a server       "Unqualified: Bounced, other reason" (2 Nov 2026);
      problem)                                         listed on the run's summary page
    A bounce whose message cannot be read            the same; listed on the summary page to be
                                                       checked by hand
    A temporary bounce (16 Nov 2026, Ariel): the      nothing changes: still "Attempted to Contact"; the
      receiving or sending mail system was down        loop carries on and their reminder a week later is
      ("try again later", "service unavailable",       the retry. A second temporary bounce for the same
      a 4.x.x code), e.g. an Outlook outage            person counts as "Bounced, other reason"

A company inbox (info@, sales@) with a dead address gets "Unqualified: Inbox Bounced" instead (2 Nov
2026). Then, at its company:
  - everyone below moves up one (2 becomes 1, 3 becomes 2, ...);
  - the new number 1 becomes "GATE2: Approved to send" when its personal line is written, or as soon
    as the line arrives (import_lines); its introduction goes at the NEXT run of button 4, never in
    the same run (data/promoted.json remembers who moved up and in which run);
  - when nobody is left to email, the company stops (2 Nov 2026, Ariel): "Unqualified: Personal inbox
    bounced", or "Unqualified: Company inbox bounced" when the dead address was its company inbox (add
    a working address and set it back to GATE1 by hand). Before 2 Nov 2026 it went back to GATE1;
  - a company closed as "no response" only because its contact bounced (before 28 Oct 2026) is put
    right the same way.
A dead contact stays in HubSpot, so button 3 never adds the same address again. Only AUTO-OUTREACH
records are touched, and a Lead Status a person set by hand is never changed.

Where the reason comes from (20 Nov 2026, Ariel): the bounce notices in admin@'s label BOUNCED (bounce_inbox.py)
first, then Instantly's own emails. Every contact whose email bounced gets "Outreach stopped because" starting
with "Bounced:" and the reason, so a HubSpot filter on that field finds every contact that added to the bounce
rate (temporary ones included, which stay in the loop):

    Bounced: address does not exist             Contact corrupt (Inbox Bounced for a company inbox); next moves up
    Bounced: domain has no mail system          the same, and nobody else at that domain is emailed: colleagues
                                                  not yet emailed there become Contact corrupt too
    Bounced: blocked by their mail system       Bounced, other reason; the company stops (as before)
    Bounced: inbox full                         Bounced, other reason
    Bounced: temporary problem                  stays in the loop (as before)
    Bounced: other reason                       Bounced, other reason
    Bounced: reason could not be read, check    Bounced, other reason (it used to say "not a dead address", which
      by hand                                     was wrong). Read again when a notice for it arrives in BOUNCED
Without any notice, Instantly's "no mail system found" for the address's domain counts as "domain has no mail
system". The older wordings ("Contact corrupt: email bounced ...", "Email bounced (...): ...") are rewritten to
these at each run, so the filter finds them too.
"""

import datetime as dt
import json
import os
import re

from .common import ROOT, from_us, step_summary
from .next_in_line import (CONTACT_PROPS, annotate, contacts_by_company, is_company_inbox, parse_time, rank_of,
                           tagged_company_of)
from .schema import LEAD_STATUS, ORDER, PERSONAL_LINE, STOP_REASON
from .stages import EMAILED

PROMOTED_FILE = ROOT / "data" / "promoted.json"
TEMPORARY_FILE = ROOT / "data" / "temporary_bounces.json"  # contact id: {day, notices}; IDs and dates only
HOLD_MINUTES = 60  # without a GitHub run number, someone approved this recently waits for the next run
DONE_PREFIXES = ("contact corrupt", "email bounced", "inbox bounced", "bounced:")  # "Outreach stopped because"
BOUNCED = "Bounced:"  # 20 Nov 2026 (Ariel): every bounced contact's "Outreach stopped because" starts with this
LABELS = {"dead": "address does not exist", "no_mail": "domain has no mail system", "full": "inbox full",
          "policy": "blocked by their mail system", "temporary": "temporary problem", "other": "other reason",
          "unreadable": "reason could not be read, check by hand"}
# 3 Nov 2026: never plain Unqualified (only a person sets it, and a person's choice is never changed).
BOUNCE_STAGES = EMAILED + ("bounced_other",)
MESSAGE = "Bounce message:"  # in "Outreach stopped because" since 3 Nov 2026

# The bounce says the address is dead (address unknown, mailbox closed or no longer used).
DEAD = re.compile(
    r"(user unknown|unknown user|no such (user|mailbox|recipient|address)|user not found|recipient not found|"
    r"unknown recipient|recipient (address )?rejected|address (was )?not found|address couldn'?t be found|"
    r"(doesn'?t|does not|did not) exist|mailbox (not found|unavailable|disabled|inactive|is disabled|"
    r"has been disabled|is inactive|no longer)|account (has been |is )?(disabled|deactivated|closed|suspended|"
    r"inactive)|no longer (in use|active|valid|exists|available)|invalid (recipient|mailbox|address)|"
    r"\b5\.1\.1\b|\b5\.1\.10\b|\b5\.2\.1\b|\b5\.1\.6\b|"
    # 3 Nov 2026: Microsoft's answer when the address is not in the company's directory
    r"\b5\.4\.1\b|recipient address rejected: access denied|"
    r"empf[äa]nger (unbekannt|nicht gefunden)|existiert nicht|unbekannte(r)? empf[äa]nger|"
    r"adresse (introuvable|inconnue)|destinataire inconnu|n'existe pas)", re.I)
# 3 Nov 2026 (Ariel): the receiving company's mail system blocks us (Google: "has a policy that prohibited the
# mail"); the address exists, but its colleagues would bounce too, so the company stops.
POLICY = re.compile(
    r"(policy that prohibited|prohibited the mail|\b5\.7\.1\b|rejected (by|for) (policy|security)|"
    r"blocked (by|due to) (policy|the recipient)|message (was )?blocked|sender (address )?(is )?blocked|"
    r"not (allowed|authori[sz]ed) to send|spam (message )?rejected|rejected as spam|"
    r"blocklisted|blacklisted)", re.I)
# 16 Nov 2026 (Ariel, after an Outlook outage): a temporary bounce, from a mail system that is down or busy.
# Only when nothing in it is permanent (a 5.x.x code or a 5xx reply), so a dead address always stays dead.
TEMPORARY = re.compile(
    r"((?<![\d.])4\.\d{1,3}\.\d{1,3}\b|(?<![\d.])4[2-5]\d[ -]|temporar(y|ily)|try (again )?later|will (be )?retried|"
    r"deferred|delivery (has been )?delayed|service (is )?(temporarily )?unavailable|server (is )?busy|"
    r"too many (connections|messages|requests)|rate limit|throttl|timed? ?out|connection (refused|reset|lost)|"
    r"gr[ae]ylist|vor[üu]bergehend|sp[äa]ter erneut|temporairement|r[ée]essayer plus tard)", re.I)
PERMANENT = re.compile(r"((?<![\d.])5\.\d{1,3}\.\d{1,3}\b|(?<![\d.])5\d\d[ -])")  # not the 500 in 4.7.500
# A full mailbox is about the person, not an outage: it stays "Bounced, other reason" (2 Nov 2026).
FULL = re.compile(r"(mailbox (is )?full|over (the )?quota|quota exceeded|\b4\.2\.2\b|insufficient storage|"
                  r"postfach (ist )?voll|bo[iî]te (aux lettres )?pleine)", re.I)
# 20 Nov 2026: the receiving domain has no working mail system (no MX record, a DNS failure, an unknown host).
NO_MAIL = re.compile(
    r"(servfail|dns (type '?mx'? )?(lookup|error)|mx (record|lookup)|no mx\b|nxdomain|"
    r"domain (name )?(not found|does not exist|couldn'?t be found)|host (not found|unknown)|"
    r"unrouteable (address|domain)|name or service not known|no route to host)", re.I)
FULL_MORE = re.compile(r"(inbox (is )?(full|out of storage)|out of storage|storage (space )?(is )?full|\b5\.2\.2\b|"
                       r"recipient inbox full)", re.I)
NO_MAIL_SYSTEM = 1000  # Instantly's lead.esp_code: no mail system found for the domain
TEMPORARY_LIMIT = 2  # the second temporary bounce for the same person counts as "Bounced, other reason"
# The words of a bounce worth showing in HubSpot: the diagnostic line, or an SMTP code with what follows.
DIAGNOSTIC = re.compile(r"(diagnostic[- ]message[:\s]*|diagnostic[- ]code[:\s]*)?(\b[45]\d\d\b[\s-]*)?"
                        r"\b[45]\.\d{1,3}\.\d{1,3}\b[^\n]{0,180}", re.I)
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


def approved_elsewhere(contact_ids, path=None):
    """Contacts that moved up and were put on GATE2 by another step of this run (chain.fill_lines, 3 Nov
    2026): their introduction still waits for the next run, as agreed for everyone who moves up."""
    promoted = load_promoted(path)
    hit = [str(c) for c in contact_ids]  # every one of them, not only those who moved up after a dead address
    for cid in hit:
        _approved_now(promoted, cid)
    if hit:
        save_promoted(promoted, path)
    return hit


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
    """ "dead" (the address does not exist or is no longer used), "policy" (their mail system blocks us),
    "temporary" (a mail system down or busy, 16 Nov 2026), "other" or "unreadable"."""
    if not (text or "").strip():
        return "unreadable"
    if DEAD.search(text):
        return "dead"
    if POLICY.search(text):
        return "policy"
    temporary = TEMPORARY.search(text) and not PERMANENT.search(text) and not FULL.search(text)
    return "temporary" if temporary else "other"


def classify(notice_text, lead=None):
    """20 Nov 2026: one of LABELS for a bounce. notice_text: the bounce notices' words (BOUNCED label and
    Instantly's emails). Without any notice, Instantly's "no mail system found" means no_mail; anything else
    Instantly holds about the lead is used only when it clearly says dead or blocked, otherwise "unreadable"."""
    text = notice_text or ""
    if text.strip():
        if NO_MAIL.search(text):
            return "no_mail"
        kind = kind_of_bounce(text)
        if kind == "other" and (FULL.search(text) or FULL_MORE.search(text)):
            return "full"
        return kind
    try:
        esp = int((lead or {}).get("esp_code"))
    except (TypeError, ValueError):
        esp = None
    if esp == NO_MAIL_SYSTEM:
        return "no_mail"
    lead_text = " ".join(str(v) for k, v in (lead or {}).items()
                         if v and any(w in k.lower() for w in ("bounce", "error", "reason")))
    kind = kind_of_bounce(lead_text) if lead_text.strip() else "unreadable"
    return kind if kind in ("dead", "policy") else "unreadable"


def bounced_reason(kind, text, extra=""):
    """ "Bounced: <reason> (<date>). Bounce message: ..." for "Outreach stopped because" (20 Nov 2026)."""
    said = bounce_message(text) if (text or "").strip() else "(none could be read)"
    return f"{BOUNCED} {LABELS.get(kind, LABELS['other'])} ({today()}){extra}. {MESSAGE} {said}"


# The older wordings, rewritten so a filter on "Bounced:" finds every bounce (20 Nov 2026).
OLD_WORDINGS = (
    (re.compile(r"^(?:Contact corrupt|Inbox bounced): email bounced, the address does not exist or is no longer used",
                re.I), f"{BOUNCED} {LABELS['dead']}"),
    (re.compile(r"^Email bounced (\([^)]*\)): not a dead address \(for example a full mailbox\)[^.]*\.?", re.I),
     f"{BOUNCED} {LABELS['unreadable']} \\1."),
    (re.compile(r"^Email bounced (\([^)]*\)): their mail system blocks our emails; the company stops\.?", re.I),
     f"{BOUNCED} {LABELS['policy']} \\1; the company stops."),
    (re.compile(r"^Email bounced (\([^)]*\)): the reason could not be read, check by hand\.?", re.I),
     f"{BOUNCED} {LABELS['unreadable']} \\1."),
)


def new_wording(reason):
    """The reason in the "Bounced:" wording, or None when it is not one of the older bounce wordings."""
    for pattern, repl in OLD_WORDINGS:
        if pattern.search(reason or ""):
            return pattern.sub(repl, reason, count=1)[:250]
    return None


def rename_old(hs, log=print):
    """Rewrite the older bounce wordings on AUTO-OUTREACH contacts (each run; nothing to do once done)."""
    from .sync import stop_reasons
    try:
        rows = hs.tagged_search("contacts", [{"propertyName": STOP_REASON, "operator": "CONTAINS_TOKEN",
                                              "value": "bounced"}], [STOP_REASON], max_results=5000)
    except Exception as err:
        log(f"Could not read the older bounce wordings: {str(err)[:150]}")
        return 0
    items = [(r["id"], new) for r in rows
             if (new := new_wording(str((r.get("properties") or {}).get(STOP_REASON) or "")))]
    if items:
        stop_reasons(hs, "contacts", items, log)
        log(f'{len(items)} older bounce reason(s) now start with "{BOUNCED}"')
    return len(items)


_TEMPORARY = {"key": None, "ids": frozenset()}


def load_temporary(path=None):
    try:
        return json.loads((path or TEMPORARY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_temporary(data, path=None):
    path = path or TEMPORARY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def temporary_ids(path=None):
    """The contacts whose bounce was temporary and who stay in the loop (16 Nov 2026): Instantly still shows
    them as bounced, so the loop and sync read this list instead."""
    path = path or TEMPORARY_FILE
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return frozenset()
    if _TEMPORARY["key"] != key:
        data = load_temporary(path)
        _TEMPORARY.update(key=key, ids=frozenset(c for c, e in data.items() if not e.get("gave_up")))
    return _TEMPORARY["ids"]


def notices(thread):
    return [e for e in thread or [] if e.get("ue_type") == 2 and _is_notice(e)]


def bounce_message(text):
    """The bounce's own words, short, for "Outreach stopped because" (3 Nov 2026)."""
    text = " ".join((text or "").split())
    m = DIAGNOSTIC.search(text)
    words = (m.group(0) if m else text)[:160].strip()
    words = re.split(r"(?i)\b(for more information|please contact your|learn more)\b", words)[0]
    return re.sub(r"https?://\S+", "", words).strip(" .;:")


def has_left(thread):
    """True when an automatic reply in the thread says the person has left or the mailbox is not read."""
    for e in thread or []:
        if e.get("ue_type") == 2 and not from_us(e) and not _is_notice(e) and LEFT.search(_full_text(e)):
            return True
    return False


# ---- The check at each run of button 4 --------------------------------------------------------

REREAD_PER_RUN = 15


def _done(contact, inbox=None):
    """Checked already. A bounce noted before 3 Nov 2026 (without its message) is read once more, so the new
    rules (Microsoft's 5.4.1, policy blocks) and the message reach it too. 20 Nov 2026: a temporary bounce is
    always looked at again (its second one counts), and a bounce whose reason could not be read is read again
    once a notice for its address is in the BOUNCED label."""
    reason = str((contact.get("properties") or {}).get(STOP_REASON) or "").strip()
    low = reason.lower()
    email = str((contact.get("properties") or {}).get("email") or "").lower()
    has_notice = bool(email and (inbox or {}).get(email))
    if low.startswith(f"{BOUNCED} {LABELS['temporary']}".lower()):
        return False
    if low.startswith(f"{BOUNCED} {LABELS['unreadable']}".lower()) or "not a dead address" in low:
        return MESSAGE.lower() in low and not has_notice  # never read with today's rules: read once more
    if low.startswith("email bounced"):
        return MESSAGE.lower() in low and not has_notice
    return low.startswith(DONE_PREFIXES)


def check(hs, emails_api, leads, statuses, seen=(), log=print, promoted_path=None, inbox=None):
    """Find dead addresses and move each company on. inbox: {address: [notice text]} from admin@'s BOUNCED label
    (bounce_inbox.read_for_run; 20 Nov 2026). Returns {"corrupt": n, "rows": [...], "to_check": [...]}."""
    from .sync import stop_reasons  # sync imports this module
    out = {"corrupt": 0, "rows": [], "to_check": []}
    inbox = inbox or {}
    if not statuses.has("contacts", "corrupt"):
        log('The contact Lead Status choice "Unqualified: Contact corrupt" is missing; run button 1 to add '
            "it. Dead addresses were not checked this run.")
        return out
    promoted = load_promoted(promoted_path)
    _approve_waiting(hs, statuses, promoted, log)
    rename_old(hs, log)  # 20 Nov 2026: every bounce reason starts with "Bounced:"
    if emails_api is None and not inbox:
        log("Dead addresses were not checked: the GitHub secret INSTANTLY_EMAILS_KEY is needed to read the bounces")
        save_promoted(promoted, promoted_path)
        return out
    bounced = {e: l for e, l in (leads or {}).items() if l.get("status") == -1}
    # 20 Nov 2026: a notice in BOUNCED counts even when Instantly has not marked the lead (or the lead is gone)
    for address in inbox:
        bounced.setdefault(address, (leads or {}).get(address) or {})
    rows = hs.tagged_read("contacts", list(bounced), CONTACT_PROPS, id_property="email") if bounced else []
    reasons, corrupt, other, blocked, no_mail = [], {}, [], [], []  # corrupt: {contact id: (record, why)}
    temporary, back = load_temporary(), []  # 16 Nov 2026: temporary bounces stay in the loop
    again = 0
    for r in rows:
        if statuses.of("contacts", r) not in BOUNCE_STAGES or _done(r, inbox):
            continue
        email = (r["properties"].get("email") or "").lower()
        known = temporary.get(str(r["id"]))
        from_label = inbox.get(email) or []
        title = r["properties"].get("jobtitle") or "contact"
        if from_label:  # the notices are in admin@'s BOUNCED label: Instantly's emails need not be read
            thread, count, notice = [], len(from_label), " ".join(from_label)
        else:
            if emails_api is None:
                continue
            if str(r["properties"].get(STOP_REASON) or "").strip().lower().startswith(("email bounced", "bounced:")):
                # an older bounce read once more; a few each run, as Instantly's emails are slow to read
                again += 1
                if again > REREAD_PER_RUN:
                    continue
            try:
                thread = emails_api.thread_emails(email)
            except Exception as err:  # read again next run
                log(f"The bounce of a {title} could not be read ({str(err)[:150]}); tried again next run")
                continue
            count = len(notices(thread))
            notice = bounce_text({}, thread, emails_api)
        if known and not known.get("gave_up") and count <= known.get("notices", 0):
            continue  # the same temporary bounce as before: nothing new to read
        lead = bounced.get(email) or {}
        kind = classify(notice, lead)
        text = notice if notice.strip() else ("Instantly found no mail system for this domain" if kind == "no_mail" else "")
        if kind == "temporary" and count < TEMPORARY_LIMIT and not (known or {}).get("gave_up"):
            temporary[str(r["id"])] = {"day": (known or {}).get("day") or today(), "notices": max(count, 1)}
            if statuses.of("contacts", r) == "bounced_other":
                back.append((r["id"], statuses.props("contacts", "in_outreach")))
            reasons.append((r["id"], bounced_reason("temporary", text, "; still in the loop, the reminder is the retry")))
            log(f"The email to a {title} bounced for a temporary reason ({bounce_message(text)[:120]}); they stay in "
                "the loop and their reminder is the retry")
            continue
        if kind == "temporary":  # the second one: counted as any other bounce from now on
            temporary[str(r["id"])] = dict(known or {}, notices=count, gave_up=today())
            kind = "other"
        if kind in ("dead", "no_mail"):
            corrupt[str(r["id"])] = (r, bounced_reason(kind, text))
            if kind == "no_mail":
                no_mail.append(r)
            continue
        reasons.append((r["id"], bounced_reason(kind, text, "; the company stops" if kind == "policy" else "")))
        out["to_check"].append((r, LABELS[kind]))
        if statuses.of("contacts", r) != "bounced_other" and statuses.has("contacts", "bounced_other"):
            other.append((r["id"], statuses.props("contacts", "bounced_other")))
        if kind == "policy":
            blocked.append(r)
    if no_mail:  # 20 Nov 2026: nobody else at a dead domain is emailed
        _same_domain(hs, statuses, no_mail, corrupt, log)
    for r, _lead, event in seen or ():
        if event != "out of office" or str(r["id"]) in corrupt or _done(r) or emails_api is None:
            continue
        if statuses.of("contacts", r) not in BOUNCE_STAGES:
            continue
        try:
            thread = emails_api.thread_emails((r["properties"].get("email") or "").lower())
        except Exception:
            continue
        if has_left(thread):
            corrupt[str(r["id"])] = (r, f"Contact corrupt: an automatic reply says they have left or the mailbox "
                                        f"is no longer read ({today()})")
    if other:
        hs.update_tagged("contacts", other)
    if back:
        hs.update_tagged("contacts", back)
    save_temporary(temporary)
    stop_reasons(hs, "contacts", reasons, log)
    if blocked:
        _close_blocked(hs, statuses, blocked, leads, out, log)
    if corrupt:
        _move_up(hs, statuses, corrupt, leads, promoted, out, log)
    save_promoted(promoted, promoted_path)
    _summary(out)
    return out


NOT_YET_EMAILED = ("found", "copy_ready", "approved")


def _same_domain(hs, statuses, dead, corrupt, log):
    """Colleagues at the same company with an address at the dead domain, not emailed yet, become Contact
    corrupt as well (20 Nov 2026, Ariel): their email could never arrive."""
    owner_of, _ = tagged_company_of(hs, [r["id"] for r in dead], ["name"])
    domains = {}
    for r in dead:
        company = owner_of.get(str(r["id"]))
        domain = str(r["properties"].get("email") or "").lower().split("@")[-1]
        if company and domain:
            domains.setdefault(company, set()).add(domain)
    everyone = contacts_by_company(hs, list(domains)) if domains else {}
    n = 0
    for company, ds in domains.items():
        for c in everyone.get(company) or []:
            domain = str(c["properties"].get("email") or "").lower().split("@")[-1]
            if str(c["id"]) in corrupt or domain not in ds or statuses.of("contacts", c) not in NOT_YET_EMAILED:
                continue
            corrupt[str(c["id"])] = (c, f"Contact corrupt: its email domain has no mail system (a colleague's email "
                                        f"bounced, {today()}); never emailed")
            n += 1
    if n:
        log(f"{n} colleague(s) at a domain with no mail system will not be emailed (Contact corrupt)")


def close_dead(hs, statuses, dead, leads=None, log=print, promoted_path=None):
    """dead: {contact id: (record, why)}. Contact corrupt (Inbox Bounced for a company inbox), the next person moves
    up, and the company stops when nobody is left (used by button 4's send step, 20 Nov 2026)."""
    out = {"corrupt": 0, "rows": [], "to_check": []}
    if not dead:
        return out
    promoted = load_promoted(promoted_path)
    _move_up(hs, statuses, dict(dead), leads or {}, promoted, out, log)
    save_promoted(promoted, promoted_path)
    _summary(out)
    return out


def _close_blocked(hs, statuses, blocked, leads, out, log):
    """Their mail system blocks us (3 Nov 2026, Ariel): the company becomes "Unqualified: Bounced, other
    reason" and its colleagues are not emailed, unless someone else there already received our email
    (then the block is not the whole company's)."""
    from .sync import stop_reasons
    if not statuses.has("companies", "bounced_other"):
        return
    owner_of, companies = tagged_company_of(hs, [r["id"] for r in blocked], ["name", LEAD_STATUS])
    by_company = {}
    for r in blocked:
        if owner_of.get(str(r["id"])):
            by_company.setdefault(owner_of[str(r["id"])], set()).add(str(r["id"]))
    everyone = contacts_by_company(hs, list(by_company)) if by_company else {}
    updates = []
    for company_id, ids in by_company.items():
        company = companies.get(company_id) or {}
        name = (company.get("properties") or {}).get("name") or "a company"
        people = annotate(everyone.get(company_id) or [], statuses, leads or {})
        if any(c["state"] == "sent" and str(c["id"]) not in ids for c in people):
            continue
        if statuses.of("companies", company) not in ("", "approved", "located", "in_outreach", "no_response"):
            continue
        updates.append((company_id, statuses.props("companies", "bounced_other")))
        stop_reasons(hs, "companies", [(company_id, f"Their mail system blocks our emails ({today()}): the "
                                                    "colleagues there are not emailed")], log)
        out["rows"].append(f"| {name} | - | Company: Unqualified: Bounced, other reason (their mail system blocks "
                           "us; colleagues not emailed) |")
        log(f'{name}: their mail system blocks our emails; the company is now "Unqualified: Bounced, other reason"')
    hs.update_tagged("companies", updates)


def _move_up(hs, statuses, corrupt, leads, promoted, out, log):
    from .sync import stop_reasons
    # 2 Nov 2026 (Ariel): a company inbox gets "Unqualified: Inbox Bounced", a person "Unqualified: Contact corrupt".
    for cid, (r, why) in list(corrupt.items()):
        if is_company_inbox(r):
            corrupt[cid] = (r, why.replace("Contact corrupt:", "Inbox bounced:", 1))
    hs.update_tagged("contacts", [(cid, {**statuses.props("contacts", "inbox_bounced" if is_company_inbox(r) else
                                                          "corrupt"), ORDER: "0"}) for cid, (r, _) in corrupt.items()])
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
        if (statuses.of("companies", company) if company else "team") not in ("", "approved", "located",
                                                                              "in_outreach", "no_response"):
            continue  # 3 Nov 2026: in conversation, with the sales team or closed otherwise: nobody moves up
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
        if not usable and stage in ("", "approved", "located", "in_outreach", "no_response"):
            # 2 Nov 2026 (Ariel): nobody left, so the company stops (it no longer goes back to GATE1).
            if dead_inbox and statuses.has("companies", "invalid_inbox"):
                company_updates.append((company_id, statuses.props("companies", "invalid_inbox")))
                stop_reasons(hs, "companies", [(company_id, f"Company inbox bounced, needs a working address "
                                                            f"({today()})")], log)
                out["rows"].append(f"| {name} | - | Company: Unqualified: Company inbox bounced |")
                log(f'{name}: its company inbox bounced and nobody is left; the company is now "Unqualified: '
                    'Company inbox bounced"')
            else:
                company_updates.append((company_id, statuses.props("companies", "personal_bounced")))
                stop_reasons(hs, "companies", [(company_id, f"Personal inbox bounced: its contacts' addresses are "
                                                            f"dead and nobody is left ({today()})")], log)
                out["rows"].append(f"| {name} | - | Company: Unqualified: Personal inbox bounced (nobody left) |")
                log(f'{name}: nobody is left to email; the company is now "Unqualified: Personal inbox bounced"')
        elif usable and stage == "no_response" and not any(c["state"] == "sent" for c in usable):
            company_updates.append((company_id, statuses.props("companies", "in_outreach")))
            out["rows"].append(f"| {name} | - | Company back in outreach (it was closed only because of the "
                               "bounce) |")
    hs.update_tagged("contacts", contact_updates)
    hs.update_tagged("companies", company_updates)


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
        text += ("## Dead addresses (Unqualified: Contact corrupt)\n\n| Company | Person (job title) | "
                 "What happened |\n|---|---|---|\n" + "\n".join(out["rows"]) + "\n\n")
    if out["to_check"]:
        text += ("## Bounces left as they are\n\n| Person (job title) | Why |\n|---|---|\n"
                 + "\n".join(f"| {r['properties'].get('jobtitle') or 'contact'} | {why} |"
                             for r, why in out["to_check"]) + "\n\n")
    if text:
        step_summary(text)
