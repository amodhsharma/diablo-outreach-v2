"""Button 4, step 1: copy Instantly results back to HubSpot's Lead Status. Runs every 3 hours.

Only AUTO-OUTREACH companies and contacts are ever changed (hubspot_client.TagGuard); an
Instantly lead whose HubSpot contact lacks the tag is ignored. Statuses only move forward
(Attempted to Contact, then In Progress, then Unqualified) and a Lead Status set by a person
(for example Emailed or Won) is never changed.

    Instantly                          Contact               Company
    replied or marked interested       In Progress           In Progress
    marked not interested              Unqualified           Unqualified
    unsubscribed (opted out)           Unqualified           Unqualified (nobody else is emailed)
    on Instantly's blocklist           Unqualified           Unqualified (nobody else is emailed)
    a reply asking us to stop          Unqualified           Unqualified (nobody else is emailed)
    an automatic answer (out of        unchanged             unchanged (no reply: the loop carries on)
      office, holiday)
    bounced                            Unqualified           unchanged (the others carry on)

After an opt-out the others at the company show "Colleague opted out", and "Outreach stopped
because" says why on the person, the colleagues and the company, with a note on the timeline
(19 Oct 2026). The opt-out signals are checked again just before every email goes.

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
import datetime as dt
import html as html_lib
import os
import re
import sys
import time

from .common import PipelineError, check_target, ist, load_company_notes, load_settings, run_dir, step_summary, write_json
from .hubspot_client import HubSpot, HubSpotError
from .instantly_client import Instantly, InstantlyError
from .next_in_line import (
    COMPANY_PROPS, annotate, apply_test_gaps, contacts_by_company, decide, follow_up_settings, instantly_view,
    is_company_inbox,
    last_campaign, lead_for, mark_sent, parse_time, rank_of, tagged_company_of, touch_times,
)
from .schema import COMPANY_NOTE, LEAD_STATUS, PERSONAL_LINE, STOP_REASON
from .stages import COLLEAGUE_STAGES, EMAILED, TEAM, LeadStatus, forward


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


# ---- Opt-outs (19 Oct 2026, strain test c5) -------------------------------------------------
# Several signals, so the blocklist is never the only safeguard: Instantly's "unsubscribed", its
# blocklist (an address, the same address without a "+tag", or a whole domain), a reply asking us
# to stop, and HubSpot's own memory (the "Outreach stopped because" field once an opt-out is found).
OPT_OUT_EVENTS = ("unsubscribed", "blocklisted", "opted out by reply", "opted out earlier")
STOP_TEXT = {"blocklisted": "Opted out: on Instantly's blocklist",
             "unsubscribed": "Opted out: unsubscribed in Instantly",
             "opted out by reply": "Opted out: asked in a reply not to be emailed again"}
BLOCKLIST_TRIES = 3
BLOCKLIST_RETRY_SECONDS = 5
BLOCKLIST_FRESH_SECONDS = 60  # read again before a send when the copy in hand is older than this


class BlockList(set):
    """Instantly's blocklist (lower case addresses and domains) and whether it could be read."""

    def __init__(self, values=(), ok=True, problem=""):
        super().__init__(values)
        self.ok, self.problem, self.read_at = ok, problem, time.monotonic()
        self._plain = None

    def plain(self):
        """The addresses again without any "+tag" (clgdbt+c5p1@gmail.com also as clgdbt@gmail.com)."""
        if self._plain is None:
            self._plain = {_untagged(v) for v in self if "@" in v}
        return self._plain


def _untagged(email):
    name, _, domain = (email or "").rpartition("@")
    return f"{name.split('+', 1)[0]}@{domain}" if name else email


def read_blocklist(*clients, log=print):
    """Instantly's blocklist. Tries each key in turn (the main key first, then the emails key), each
    a few times. When it cannot be read at all, the run carries on: anyone already marked as opted
    out in HubSpot stays stopped, and the report says that entries added since the last successful
    read are not applied yet (agreed 19 Oct 2026; nothing else is held back)."""
    problem = "no Instantly key can read it"
    key = os.environ.get("INSTANTLY_BLOCKLIST_KEY")  # read-only key for the blocklist (20 Oct 2026)
    if key:
        try:
            clients = (Instantly(api_key=key),) + tuple(clients)
        except Exception:
            pass
    for client in clients:
        if client is None or not hasattr(client, "blocklist"):
            continue
        for attempt in range(BLOCKLIST_TRIES):
            try:
                found = BlockList(client.blocklist())
                log(f"Instantly blocklist: {len(found)} entries read (addresses and domains)")
                return found
            except Exception as err:
                problem = str(err)[:200]
                if "block_list_entries" in problem or " 401" in problem or " 403" in problem:
                    problem = ("Instantly refused the key: it is not allowed to read the blocklist. Add the GitHub "
                               "secret INSTANTLY_BLOCKLIST_KEY: an Instantly API key with the permission "
                               "block_list_entries:read")
                    break  # asking again with the same key does not help
                if attempt + 1 < BLOCKLIST_TRIES and BLOCKLIST_RETRY_SECONDS:
                    time.sleep(BLOCKLIST_RETRY_SECONDS)
    log(f"WARNING: Instantly's blocklist could not be read ({problem}). Forwards and reminders still go out; "
        "anyone already marked as opted out in HubSpot stays stopped, but blocklist entries added since the "
        "last successful read are not applied in this run")
    return BlockList(ok=False, problem=problem)


def is_blocked(email, blocked):
    """True when the address, the same address without its "+tag", or its whole domain is on
    Instantly's blocklist."""
    email = (email or "").strip().lower()
    if not email or not blocked or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1]
    if email in blocked or domain in blocked or ("@" + domain) in blocked:
        return True
    plain = blocked.plain() if isinstance(blocked, BlockList) else {_untagged(v) for v in blocked if "@" in v}
    return _untagged(email) in plain


def opted_out_earlier(contact):
    """HubSpot remembers an opt-out found before (the "Outreach stopped because" field)."""
    return str((contact.get("properties") or {}).get(STOP_REASON) or "").lower().startswith("opted out")


def today():
    return dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y").lstrip("0")


# ---- Replies: automatic answers and requests to stop (19 Oct 2026, strain test c6) ------------
# An automatic answer (out of office, holiday) counts as NO reply: the loop carries on.
# Words that mark an automatic answer (20 Oct 2026: a wider list, looked for anywhere in the subject
# and in the text above any quoted email, in the languages of our markets).
AUTO_PHRASES = (
    # English
    r"automatic reply", r"automated reply", r"automated response", r"automatic response",
    r"auto[- ]?reply", r"auto[- ]?response", r"auto[- ]?responder", r"autoreply", r"out of (the )?office",
    r"\booo\b", r"away from (the |my )?(office|desk)", r"on (annual |parental |maternity |paternity |sick )?leave",
    r"on holiday", r"on vacation", r"currently away", r"limited access to (my )?e-?mails?",
    r"this is an automated", r"automatically generated", r"do not reply to this (e-?mail|message)",
    r"no longer (with|at) (the company|this company)", r"has left the company",
    # German
    r"automatische antwort", r"abwesenheitsnotiz", r"abwesenheit", r"abwesend", r"nicht im b[üu]ro",
    r"au[ßs]er haus", r"im urlaub", r"urlaubsbedingt", r"nicht erreichbar", r"automatisch generiert",
    # French
    r"r[ée]ponse automatique", r"message automatique", r"absente? du bureau", r"je suis (actuellement )?absente?",
    r"en cong[ée]s?", r"hors du bureau",
    # Spanish, Italian, Portuguese
    r"respuesta autom[áa]tica", r"fuera de la oficina", r"de vacaciones", r"ausente",
    r"risposta automatica", r"fuori ufficio", r"sono (in ferie|assente)", r"resposta autom[áa]tica",
    r"fora do escrit[óo]rio",
    # Dutch, Nordic, Polish, Czech
    r"automatisch antwoord", r"afwezig", r"met vakantie", r"niet aanwezig", r"autosvar", r"automatisk svar",
    r"fr[åa]nvarande", r"frav[æa]r", r"automatyczna odpowied", r"nieobecn", r"automatick[áa] odpov[ěe]d",
    r"mimo kancel[áa][řr]",
)
AUTO_PHRASE = re.compile("(" + "|".join(AUTO_PHRASES) + ")", re.I)
AUTO_HEADERS = re.compile(r"(auto-submitted:\s*auto-(replied|generated)|x-autoreply|x-autorespond|"
                          r"precedence:\s*auto_reply|x-auto-response-suppress)", re.I)
# Kept for the earlier subject check (19 Oct 2026).
AUTO_SUBJECT = AUTO_PHRASE
AUTO_BODY = AUTO_PHRASE
RETURN_WORDS = re.compile(r"\b(return|returning|back|until|zur[üu]ck|wieder|bis zum|retour|jusqu|regreso|"
                          r"hasta|rientro|fino al)\b", re.I)
SHORT_ANSWER = 800  # characters: a longer text needs a return date too, so a real answer is not missed
# A reply asking not to be emailed again counts as an opt-out.
OPT_OUT_WORDS = re.compile(
    r"(unsubscribe|opt(ed)?[- ]?out\b|remove me|remove us|take me off|take us off|stop (emailing|sending|"
    r"contacting|writing)|do not (contact|email|write)|don'?t (contact|email|write)|no (more|further) e-?mails|"
    r"not (to )?contact (me|us) again|abmelden|austragen|keine (weiteren )?(e-?mails|nachrichten|werbung)|"
    r"nicht mehr (kontaktieren|anschreiben|schreiben)|d[ée]sinscri|d[ée]sabonn|ne plus (me |nous )?"
    r"(contacter|[ée]crire|recevoir|envoyer)|darse de baja|darme de baja|no (me|nos) (contacte|escriba)|"
    r"cancellami|disiscriv|non contattarmi|afmelden|uitschrijven|niet meer (mailen|contacteren))", re.I)
QUOTE_START = re.compile(
    r"(^|\n)\s*(>|on .{0,200}wrote:|am .{0,200}schrieb|le .{0,200}a [ée]crit|el .{0,200}escribi[óo]|"
    r"il .{0,200}ha scritto|op .{0,200}schreef|-{2,}\s*(original message|urspr[üu]ngliche nachricht|"
    r"message d'origine|forwarded message|mensaje original)|_{5,}|from:\s|von:\s|de\s?:\s|sent from my)",
    re.I)


def reply_text(email):
    """The words of a received email above any quoted earlier email, as plain text."""
    body = email.get("body") or {}
    if isinstance(body, str):
        text = body
    else:
        text = body.get("text") or ""
        if not text and body.get("html"):
            text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", body["html"], flags=re.I)
            text = html_lib.unescape(re.sub(r"<[^>]+>", " ", text))
    text = text or email.get("content_preview") or ""
    m = QUOTE_START.search(text)
    return (text[:m.start()] if m else text).strip()


def auto_reply_reason(email):
    """Why an answer counts as automatic (out of office, holiday), or "" when it does not. Checked in
    this order (20 Oct 2026, a safety check so an automatic answer is never taken as a real one):
    Instantly's own flag; auto-reply headers; any of the AUTO_PHRASES anywhere in the subject; any of
    them in the text above the quoted email, when the text is short (a longer text also needs a word
    such as "until" or "back", so a real answer that mentions a holiday is not missed)."""
    if email.get("is_auto_reply") or email.get("auto_reply"):
        return "Instantly marked it as an automatic reply"
    headers = email.get("headers") or email.get("raw_headers") or ""
    if headers and AUTO_HEADERS.search(headers if isinstance(headers, str) else " ".join(map(str, headers))):
        return "its headers say it was sent automatically"
    m = AUTO_PHRASE.search(email.get("subject") or "")
    if m:
        return f'the subject says "{m.group(0)}"'
    text = reply_text(email)
    m = AUTO_PHRASE.search(text) if text else None
    if m and (len(text) < SHORT_ANSWER or RETURN_WORDS.search(text)):
        return f'the text says "{m.group(0)}"'
    return ""


def is_auto_reply(email):
    """True for an automatic answer (out of office, holiday); see auto_reply_reason."""
    return bool(auto_reply_reason(email))


def is_opt_out_reply(email):
    return bool(OPT_OUT_WORDS.search(reply_text(email)))


def _with_body(emails_api, email):
    """The email with its text: the list of emails may leave the body out."""
    body = email.get("body")
    if body and (isinstance(body, str) or body.get("text") or body.get("html")):
        return email
    full = emails_api.get_email(email["id"]) if (email.get("id") and hasattr(emails_api, "get_email")) else None
    return {**email, **full} if full else email


def classify_replies(emails_api, address, why=None):
    """What a person's answers in Instantly amount to: "opt_out", "reply", "auto" (only automatic
    answers) or None (no answer found, or the emails could not be read). why (a list) gets the reason
    an answer was taken as automatic."""
    try:
        got = [e for e in emails_api.thread_emails(address) if e.get("ue_type") == 2]
    except Exception:
        return None
    kinds = set()
    for e in got:
        e = _with_body(emails_api, e)
        reason = auto_reply_reason(e)
        if reason:
            kinds.add("auto")
            if why is not None:
                why.append(reason)
        elif is_opt_out_reply(e):
            kinds.add("opt_out")
        else:
            kinds.add("reply")
    for kind in ("opt_out", "reply", "auto"):
        if kind in kinds:
            return kind
    return None


def stop_reasons(hs, object_type, items, log=print):
    """Write "Outreach stopped because" and a timeline note on AUTO-OUTREACH records: [(id, text)].
    Never stops the run: a missing field or a key without note access is reported once."""
    items = [(str(rid), text) for rid, text in items if text]
    if not items:
        return
    try:
        if hs.has_property(object_type, STOP_REASON):
            hs.update_tagged(object_type, [(rid, {STOP_REASON: text[:250]}) for rid, text in items])
        else:
            log(f'The {object_type} field "Outreach stopped because" is missing; run button 1 to add it')
    except Exception as err:
        log(f"Could not write why outreach stopped on {len(items)} {object_type}: {str(err)[:200]}")
    try:
        if hasattr(hs, "note_tagged"):
            hs.note_tagged(object_type, [(rid, f"Diablo outreach stopped. {text}") for rid, text in items])
    except Exception as err:
        log(f"Could not add a timeline note on {len(items)} {object_type} (the note says why outreach "
            f"stopped): {str(err)[:200]}")


# What the rest of a company shows once someone there has answered (agreed 19 Oct 2026); an opt-out
# gets its own choice, "Colleague opted out" (19 Oct 2026), or "Colleague replied: negative" in an
# account where button 1 has not added it yet.
COLLEAGUE_STAGE = {"marked interested": "colleague_positive", "replied": "colleague_replied",
                   "marked not interested": "colleague_negative", "unsubscribed": "colleague_opted_out",
                   "blocklisted": "colleague_opted_out", "opted out by reply": "colleague_opted_out",
                   "opted out earlier": "colleague_opted_out"}


# Contacts left alone when their company is Unqualified: their own Unqualified, a status that already
# says what happened at the company, one a person set by hand, and those already done.
KEEP_WHEN_COMPANY_CLOSED = ("closed", "company_unqualified", "no_response", TEAM) + COLLEAGUE_STAGES


def colleague_answer(contacts, statuses, leads, blocked=None):
    """The colleague Lead Status that the company's own answer calls for (23 Oct 2026), or None when
    nobody at the company has answered. Read from Instantly for the contacts whose own Lead Status says
    they answered (Replied or Unqualified), in the same order as a fresh reply: interested first, then an
    opt-out, then not interested, then any other reply. A reply from someone now Unqualified counts as
    not interested."""
    found = set()
    for c in contacts:
        own = statuses.of("contacts", c)
        if own not in ("replied", "closed"):
            continue
        p = c.get("properties", {})
        email = (p.get("email") or "").lower()
        lead = (leads or {}).get(email)
        if str(p.get(STOP_REASON) or "").lower().startswith("opted out") or is_blocked(email, blocked):
            found.add("colleague_opted_out")
        if not lead:
            continue
        _, _, event = lead_result(lead)
        if event == "marked interested":
            found.add("colleague_positive")
        elif event == "unsubscribed":
            found.add("colleague_opted_out")
        elif event == "marked not interested" or (event == "replied" and own == "closed"):
            found.add("colleague_negative")
        elif event == "replied":
            found.add("colleague_replied")
    for stage in ("colleague_positive", "colleague_opted_out", "colleague_negative", "colleague_replied"):
        if stage in found:
            if stage == "colleague_opted_out" and not statuses.has("contacts", stage):
                stage = "colleague_negative"  # until button 1 adds "Colleague opted out"
            return stage if statuses.has("contacts", stage) else None
    return None


def close_company_contacts(hs, statuses, log=print, leads=None, blocked=None):
    """Every AUTO-OUTREACH contact at an AUTO-OUTREACH company whose Lead Status is Unqualified (set by a
    person or by the loop) becomes "Unqualified company" (agreed 21 Oct 2026), with the reason written
    in "Outreach stopped because" and on its timeline. When someone at the company answered (Instantly
    shows it), the others get the colleague Lead Status instead, such as "Colleague replied: negative"
    (23 Oct 2026: contacts set back to GATE2 by hand get their right label back). Returns how many
    contacts changed."""
    if not statuses.has("contacts", "company_unqualified"):
        log('The contact Lead Status choice "Unqualified company" is missing; run button 1 to add it. '
            "Contacts at Unqualified companies were left as they are.")
        return 0
    companies = hs.tagged_search("companies", [statuses.filter("companies", "closed")],
                                 ["name", STOP_REASON], max_results=5000)
    if statuses.has("companies", "no_response"):  # 21 Oct 2026: no reply in time
        companies += hs.tagged_search("companies", [statuses.filter("companies", "no_response")],
                                      ["name", STOP_REASON], max_results=5000)
    if not companies:
        return 0
    everyone = contacts_by_company(hs, [c["id"] for c in companies])
    updates, reasons = [], []
    for company in companies:
        props = company.get("properties", {})
        why = (props.get(STOP_REASON) or "").strip()
        text = f"The company is Unqualified ({today()})" + (f": {why}" if why else "")
        people = everyone.get(company["id"]) or []
        stage = colleague_answer(people, statuses, leads, blocked) or "company_unqualified"
        changed = 0
        for c in people:
            if statuses.of("contacts", c) in KEEP_WHEN_COMPANY_CLOSED:
                continue
            updates.append((c["id"], statuses.props("contacts", stage)))
            reasons.append((c["id"], text))
            changed += 1
        if changed:
            label = statuses.label("contacts", statuses.props("contacts", stage)[LEAD_STATUS])
            log(f'{props.get("name")}: the company is Unqualified, so {changed} contact(s) there are now "{label}"')
    if updates:
        hs.update_tagged("contacts", updates)
        stop_reasons(hs, "contacts", reasons, log)
    return len(updates)


def mark_colleagues(hs, statuses, company_contacts, answered_ids, stage, log=print, name=""):
    """Give everyone at the company who has not answered themselves the colleague Lead Status, so
    gate 2 no longer shows them as waiting. Skipped quietly when the account lacks the choice
    (button 1 not run since 19 Oct 2026)."""
    if stage == "colleague_opted_out" and not statuses.has("contacts", stage):
        stage = "colleague_negative"  # until button 1 adds "Colleague opted out"
    if not statuses.has("contacts", stage):
        log(f"{name}: the Lead Status choice for colleagues is missing; run button 1 to add it")
        return []
    answered = {str(i) for i in answered_ids}
    updates = []
    for c in company_contacts:
        current = statuses.of("contacts", c)
        if str(c["id"]) in answered or current in ("replied", "closed", TEAM) + COLLEAGUE_STAGES:
            continue
        updates.append((c["id"], statuses.props("contacts", stage)))
    if updates:
        hs.update_tagged("contacts", updates)
    return updates


def run(target, settings, hs, instantly, log=print, emails_api=None):
    check_target(hs, target)
    statuses = LeadStatus(hs)
    leads = instantly_view(instantly, settings["sync"]["campaign_prefix"])
    log(f"{len(leads)} leads in the Diablo campaigns in Instantly")
    if not leads:
        return {"updated": 0}

    # Only AUTO-OUTREACH contacts come back from tagged_read; any other email is ignored.
    rows = hs.tagged_read("contacts", list(leads), ["email", LEAD_STATUS, "jobtitle"], id_property="email")
    blocked = read_blocklist(instantly, emails_api, log=log)
    contact_updates, changed = [], []
    for r in rows:
        p = r.get("properties", {})
        lead = leads.get((p.get("email") or "").lower())
        if not lead:
            continue
        new, company_stage, event = lead_result(lead)
        # Every answer is read, whatever label Instantly gave it (20 Oct 2026, case e4: Instantly
        # labelled an automatic reply "Interested"). Only automatic answers: no reply, the loop carries
        # on and the label is ignored. A request to stop: an opt-out. A real answer: Instantly's label
        # decides as before (none: "replied"). If the emails cannot be read, the label counts as before.
        if (emails_api is not None and (lead.get("email_reply_count") or 0) > 0
                and lead.get("status") not in (-1, -2)):
            why = []
            kind = classify_replies(emails_api, p.get("email"), why)
            if kind == "auto":
                new, company_stage, event = "in_outreach", None, "out of office"
                log(f"{p.get('jobtitle') or 'A contact'} sent only an automatic answer ({why[0] if why else 'out of office'})"
                    + ("; Instantly labelled it, the label is ignored" if lead.get("lt_interest_status") not in (None, 0)
                       else "") + "; it does not count as a reply, so the loop carries on")
            elif kind == "opt_out":
                new, company_stage, event = "closed", "closed", "opted out by reply"
            elif kind == "reply" and lead.get("lt_interest_status") in (None, 0):
                new, company_stage, event = "replied", "replied", "replied"
        if is_blocked(p.get("email"), blocked) and new not in ("closed", "replied"):
            # Blocklisted in Instantly counts as an opt-out (19 Oct 2026): the company stops.
            new, company_stage, event = "closed", "closed", "blocklisted"
        old = statuses.of("contacts", r)
        if not forward(old, new):
            continue
        if old == "approved":  # 23 Oct 2026: set back to GATE2 by hand, but Instantly already holds them
            log(f"{p.get('jobtitle') or 'A contact'} was at GATE2: Approved to send, but Instantly already has "
                f"them ({event}); set back to {statuses.label('contacts', statuses.props('contacts', new)[LEAD_STATUS])}")
        contact_updates.append((r["id"], statuses.props("contacts", new)))
        changed.append({"contact_id": r["id"], "from": old, "to": new, "event": event,
                        "company_to": company_stage, "jobtitle": p.get("jobtitle") or "contact"})
    hs.update_tagged("contacts", contact_updates)
    opt_out_rows = []
    opted = [c for c in changed if c["event"] in OPT_OUT_EVENTS]
    stop_reasons(hs, "contacts", [(c["contact_id"], f"{STOP_TEXT.get(c['event'], 'Opted out')} ({today()})")
                                  for c in opted], log)

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
        # Everyone else at a company that has answered gets a Lead Status saying so (19 Oct 2026).
        if company_updates:
            everyone = contacts_by_company(hs, list(company_updates))
            for company_id in company_updates:
                events = [c["event"] for c in ups if owner_of.get(str(c["contact_id"])) == company_id]
                answered = [c["contact_id"] for c in ups if owner_of.get(str(c["contact_id"])) == company_id]
                kind = ("colleague_positive" if "marked interested" in events else
                        "colleague_opted_out" if any(e in OPT_OUT_EVENTS for e in events) else
                        "colleague_negative" if any(COLLEAGUE_STAGE.get(e) == "colleague_negative" for e in events)
                        else "colleague_replied")
                cname = (current.get(company_id) or {}).get("properties", {}).get("name", "")
                marked = mark_colleagues(hs, statuses, everyone.get(company_id) or [], answered, kind, log, cname)
                if kind == "colleague_opted_out":
                    stop_reasons(hs, "companies", [(company_id, f"A contact opted out ({today()})")], log)
                    stop_reasons(hs, "contacts", [(cid, f"A colleague opted out ({today()})") for cid, _ in marked], log)
                    for c in ups:
                        if owner_of.get(str(c["contact_id"])) == company_id and c["event"] in OPT_OUT_EVENTS:
                            opt_out_rows.append(f"| {cname} | {c['jobtitle']} | {STOP_TEXT.get(c['event'])} |")
                            log(f"{cname}: {c['jobtitle']} opted out ({c['event']}); the company is now Unqualified "
                                "and nobody else there is emailed")

    moved = advance(hs, instantly, settings, log, emails_api=emails_api, statuses=statuses, leads=leads,
                    blocked=blocked, opt_out_rows=opt_out_rows)
    try:  # 21 Oct 2026: the contacts of every Unqualified company become "Unqualified company"
        moved["company_contacts_closed"] = close_company_contacts(hs, statuses, log, leads=leads,
                                                                   blocked=blocked)
    except Exception as err:  # never stops the run; tried again next run
        log(f"Could not mark the contacts of Unqualified companies: {str(err)[:200]}")
        moved["company_contacts_closed"] = 0
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


def company_mail(emails_api, contacts, details=None):
    """What Instantly holds for a company's people: ({contact id: [times emailed]},
    {contact id: [emails sent to them, oldest first]}, {contact ids that replied}).
    A forward may be filed under the address it was forwarded from, so every email is matched to
    a person by its own To or From address. Automatic answers (out of office) are not replies
    (19 Oct 2026); a reply asking us to stop goes into details["opted_out"] instead, when given."""
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
            e = _with_body(emails_api, e)
            if is_auto_reply(e):
                if details is not None:
                    details.setdefault("auto_replies", set()).add(asked)
                continue
            sender = _addresses(e.get("from_address_email"))
            # A reply from another address of theirs (e.g. their main address instead of the one we
            # wrote to) counts for the person whose conversation it arrived in (19 Oct 2026, case c3).
            who = (by_addr.get(sender[0]) if sender else None) or by_addr.get(asked)
            if who:
                if details is not None and is_opt_out_reply(e):
                    details.setdefault("opted_out", set()).add(who["id"])
                else:
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


def reminder_path(settings, person=None):
    """The reminder template for this person: a company inbox (no people in Apollo, 19 Oct 2026)
    gets templates.reminder_company_inbox, everyone else templates.reminder."""
    paths = settings["send"].get("templates") or {}
    if person is not None and is_company_inbox(person):
        return paths.get("reminder_company_inbox") or "templates/follow_up_no_info_apollo_1.json"
    return paths.get("reminder") or "templates/follow_up.json"


def reminder_subject(settings, person=None):
    """The reminder template's own subject, or "" to reply as "Re: <first subject>". follow_up_2.json
    (agreed 15 Oct 2026) has its own subject, so person 1 gets it as a separate email."""
    from . import send
    subject, _ = send._template(reminder_path(settings, person), settings["send"])
    return (subject or "").strip()


def forward_field(settings):
    """(HubSpot field, plain name) the forward needs filled in for the person it goes to."""
    from . import send
    if send.template_uses(settings, "forward", "company_note"):
        return COMPANY_NOTE, "Outreach company note"
    return PERSONAL_LINE, "Outreach personal line"


def reminder_email(person, company, settings, notes=None, mailbox=None):
    """(html, text) of person 1's one reminder (agreed 14 Oct 2026). mailbox: the one sending it
    (the same one that sent the first email), used only when the signature follows the mailbox."""
    return _fill(reminder_path(settings, person), person, company, settings, notes, mailbox=mailbox)


def forward_email(person, company, settings, notes=None, colleague="", original=None):
    """(html, text) of the note on top of a forward to the next person (agreed 14 Oct 2026)."""
    paths = settings["send"].get("templates") or {}
    mailbox = (original or {}).get("eaccount")  # the forward goes from the mailbox of the chain
    html, text = _fill(paths.get("forward") or "templates/forward.json", person, company, settings, notes,
                       {"colleague_name": colleague}, mailbox=mailbox)
    if original is not None and (settings["send"].get("rotation") or {}).get("forward_include_original"):
        html, text = add_forwarded(html, text, original)
    return html, text


def add_forwarded(html, text, original):
    """The earlier email underneath, as an email program shows a forward (switched on 19 Oct 2026:
    the strain test showed Instantly's forward does not include it by itself)."""
    body = original.get("body") or {}
    when = parse_time(original.get("timestamp_email") or original.get("timestamp_created"))
    to = original.get("to_address_email_list") or ""
    to = ", ".join(to) if isinstance(to, (list, tuple)) else str(to)
    head = [("From", original.get("from_address_email") or original.get("eaccount") or ""),
            ("Date", when.strftime("%a, %d %b %Y at %H:%M UTC") if when else ""),
            ("Subject", original.get("subject") or ""), ("To", to)]
    head = [(k, v) for k, v in head if v]
    orig_html = body.get("html") or html_lib.escape(body.get("text") or "").replace("\n", "<br>")
    orig_text = body.get("text") or re.sub(r"<[^>]+>", "", (body.get("html") or "").replace("<br>", "\n"))
    html += ("<div><br></div><div>---------- Forwarded message ---------</div>"
             + "".join(f"<div>{k}: {html_lib.escape(v)}</div>" for k, v in head)
             + "<div><br></div>" + orig_html)
    text += ("\n\n---------- Forwarded message ---------\n" + "".join(f"{k}: {v}\n" for k, v in head)
             + "\n" + orig_text)
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
    "no_reply": "Contacted, but no response, unqualified (the loop is finished)",
    "nothing": "nothing (nobody approved)",
    "waiting_for_reply": "a reply to person 1's introduction (no follow-ups are sent)",
}


def due_at(contacts, touches, why, gap_days, min_same_days, no_reply_days=7):
    """When the company's next email is due, for the waiting reasons, or None. For
    waiting_for_reply (follow-ups off), when the company closes if nobody replies."""
    import datetime as _dt
    times = [t for c in contacts if c.get("state") in ("sent", "bounced") for t in touch_times(c, touches)]
    if why == "waiting_for_reply":
        sent = [t for c in contacts if c.get("state") == "sent" for t in touch_times(c, touches)]
        return max(sent) + _dt.timedelta(days=no_reply_days) if sent else None
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


def overview(hs, instantly, settings, emails_api=None, now=None, statuses=None, blocked=None):
    """Read only: where every company in outreach is in its loop, for the health report. With the
    blocklist given, each company also says whether anyone there is on it (19 Oct 2026)."""
    statuses = statuses or LeadStatus(hs)
    leads = instantly_view(instantly, settings["sync"]["campaign_prefix"])
    gap = float(settings["send"].get("next_contact_after_days", 3))
    min_same = float((settings["send"].get("rotation") or {}).get("min_days_same_person", 7))
    one_email = follow_up_settings(settings["send"])
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
        _, why = decide(contacts, statuses.of("companies", company), gap, now, touches=touches, min_same_days=min_same,
                        follow_ups=one_email[0], no_reply_days=one_email[1],
                        inbox_reminder=one_email[2])
        when = due_at(contacts, touches, why, gap, min_same, one_email[1])
        line = f"- **{name}**: next is {NEXT_STEP.get(why, why)}" + (f", due {ist(when)}" if when else "")
        if blocked is not None and getattr(blocked, "ok", True):
            found = stop_signals(contacts, blocked, leads)
            line += (f"; **opted out: {len(found)} there** (the company is stopped at the next run)" if found
                     else "; blocklist: clear")
        nexts.append(line)
        people += progress_rows(name, contacts, touches, statuses)
    return ("## Where every company is in its loop\n\n" + "\n".join(nexts) + "\n\n"
            "| Company | Order | Person (job title) | Lead Status | Emailed |\n|---|---|---|---|---|\n"
            + "\n".join(people) + "\n")


def blocklist_line(blocked):
    if isinstance(blocked, BlockList) and not blocked.ok:
        return (f"**Instantly blocklist could not be read** ({blocked.problem}). Emails still went out; anyone "
                "already marked as opted out in HubSpot stayed stopped, but blocklist entries added since the last "
                "successful read were not applied in this run.")
    return f"Instantly blocklist: {len(blocked or ())} entries read and checked before every email."


def _summary(sent_rows, waiting_rows, opt_out_rows, blocked):
    summary = "## Button 4: what was sent this run\n\n" + blocklist_line(blocked) + "\n\n"
    summary += ("| Company | Person (job title) | What happened |\n|---|---|---|\n" + "\n".join(sent_rows)
                if sent_rows else "Nothing was due this run.")
    if opt_out_rows:
        summary += ("\n\n## Opt-outs found this run\n\n| Company | Person (job title) | Signal |\n|---|---|---|\n"
                    + "\n".join(opt_out_rows))
    if waiting_rows:
        summary += ("\n\n## Waiting\n\n| Company | Next | Due |\n|---|---|---|\n" + "\n".join(waiting_rows))
    step_summary(summary)


def stop_signals(contacts, blocked, leads, details=None):
    """[(contact, event)] for everyone at a company who opted out, by any of the signals: Instantly
    unsubscribed, on Instantly's blocklist, a reply asking us to stop, or an opt-out HubSpot already
    holds (19 Oct 2026)."""
    found = []
    asked_to_stop = (details or {}).get("opted_out") or set()
    for c in contacts:
        email = (c["properties"].get("email") or "").lower()
        lead = (leads or {}).get(email) or {}
        if lead.get("status") == -2:
            found.append((c, "unsubscribed"))
        elif is_blocked(email, blocked):
            found.append((c, "blocklisted"))
        elif c["id"] in asked_to_stop:
            found.append((c, "opted out by reply"))
        elif opted_out_earlier(c):
            found.append((c, "opted out earlier"))
    return found


def advance(hs, instantly, settings, log=print, now=None, emails_api=None, statuses=None, leads=None,
            blocked=None, opt_out_rows=None):
    """Move each AUTO-OUTREACH company in outreach on through its one loop when the next email is due."""
    statuses = statuses or LeadStatus(hs)
    blocklist = {"now": blocked if blocked is not None else read_blocklist(instantly, emails_api, log=log)}

    def fresh_blocklist():
        """The blocklist, read again when the copy in hand is more than a minute old (a last check
        just before each email; if it cannot be read again, the earlier copy is used)."""
        held = blocklist["now"]
        if isinstance(held, BlockList) and time.monotonic() - held.read_at > BLOCKLIST_FRESH_SECONDS:
            again = read_blocklist(instantly, emails_api, log=lambda *_: None)
            if again.ok:
                blocklist["now"] = again
        return blocklist["now"]

    if leads is None:
        leads = instantly_view(instantly, settings["sync"]["campaign_prefix"])
    gap = float(settings["send"].get("next_contact_after_days", 3))
    rot = settings["send"].get("rotation") or {}
    min_same = float(rot.get("min_days_same_person", 7))
    one_email = follow_up_settings(settings["send"])  # 21 Oct 2026: follow-ups to people off
    companies = hs.tagged_search("companies", [statuses.filter("companies", "in_outreach")],
                                 COMPANY_PROPS, max_results=5000)
    result = {"next_contacts_added": 0, "forwards_sent": 0, "reminders_sent": 0, "no_reply": 0,
              "replied": 0, "waiting_for_emails_key": 0, "opted_out": 0}
    opt_out_rows = list(opt_out_rows or [])
    if not companies:
        _summary([], [], opt_out_rows, blocklist["now"])
        return result
    everyone = contacts_by_company(hs, [c["id"] for c in companies])
    notes = load_company_notes()
    contact_updates, company_updates = [], []
    sent_rows, waiting_rows = [], []

    def no_response(company, name, contacts):
        """The loop is finished with no reply (21 Oct 2026): the company and everyone emailed there
        become "Contacted, but no response, unqualified" (Unqualified in an account where button 1 has
        not added that choice yet); the others there become "Unqualified company" in the same run."""
        company_updates.append((company["id"], statuses.props_or("companies", "no_response", "closed")))
        for c in contacts:
            if c.get("state") == "sent" and statuses.of("contacts", c) in EMAILED:
                contact_updates.append((c["id"], statuses.props_or("contacts", "no_response", "closed")))
        result["no_reply"] += 1
        sent_rows.append(f"| {name} | - | No reply: company set to Contacted, but no response, unqualified |")
        log(f"{name}: no reply to the introduction; the company is now \"Contacted, but no response, "
            "unqualified\"")

    def stop_company(company, name, contacts, found):
        """An opt-out at the company: that person and the company are Unqualified, everyone else
        there shows "Colleague opted out", and HubSpot says why (19 Oct 2026)."""
        for c, event in found:
            if forward(statuses.of("contacts", c), "closed"):
                contact_updates.append((c["id"], statuses.props("contacts", "closed")))
        if forward(statuses.of("companies", company), "closed"):
            company_updates.append((company["id"], statuses.props("companies", "closed")))
        fresh = [(c, e) for c, e in found if e != "opted out earlier"]
        stop_reasons(hs, "contacts", [(c["id"], f"{STOP_TEXT.get(e, 'Opted out')} ({today()})") for c, e in fresh], log)
        marked = mark_colleagues(hs, statuses, contacts, [c["id"] for c, _ in found], "colleague_opted_out", log, name)
        stop_reasons(hs, "contacts", [(cid, f"A colleague opted out ({today()})") for cid, _ in marked], log)
        stop_reasons(hs, "companies", [(company["id"], f"A contact opted out ({today()})")], log)
        for c, event in found:
            opt_out_rows.append(f"| {name} | {c['properties'].get('jobtitle') or 'contact'} | "
                                f"{STOP_TEXT.get(event, 'Opted out earlier (already in HubSpot)')} |")
        result["opted_out"] += 1
        sent_rows.append(f"| {name} | - | Opted out: company Unqualified, nobody else emailed |")
        log(f"{name}: someone there opted out ({', '.join(sorted({e for _, e in found}))}); the company is now "
            "Unqualified and nobody else there is emailed")

    def last_check(company, name, contacts, details):
        """Just before an email goes: anyone at the company opted out since the run started?"""
        found = stop_signals(contacts, fresh_blocklist(), leads, details)
        if found:
            stop_company(company, name, contacts, found)
            return False
        return True

    for company in companies:
        props = company.get("properties", {})
        name = props.get("name")
        contacts = annotate(everyone.get(company["id"]) or [], statuses, leads)
        touches, history, replied, details = None, {}, set(), {}
        if emails_api is not None and any(c["state"] in ("queued", "sent", "bounced") for c in contacts):
            try:
                touches, history, replied = company_mail(emails_api, contacts, details)
            except Exception as err:  # one company's emails not readable never stops the others
                log(f"{name}: Instantly's emails for this company could not be read ({str(err)[:150]}); "
                    "nothing is sent to it this run, it is tried again next run")
                waiting_rows.append(f"| {name} | emails could not be read, tried again next run | - |")
                continue
            mark_sent(contacts, touches)
        found = stop_signals(contacts, blocklist["now"], leads, details)
        if found:  # an opt-out comes before anything else, also before a colleague's reply
            stop_company(company, name, contacts, found)
            continue
        if replied:  # e.g. a reply to a forward, which Instantly's campaign does not count
            for c in contacts:
                if c["id"] in replied and forward(statuses.of("contacts", c), "replied"):
                    contact_updates.append((c["id"], statuses.props("contacts", "replied")))
            if forward(statuses.of("companies", company), "replied"):
                company_updates.append((company["id"], statuses.props("companies", "replied")))
            mark_colleagues(hs, statuses, contacts, replied, "colleague_replied", log, name)
            result["replied"] += 1
            sent_rows.append(f"| {name} | - | Reply received: nobody else there is emailed |")
            log(f"{name}: someone replied; nobody else there is emailed")
            continue
        due, why = decide(contacts, statuses.of("companies", company), gap, now,
                          touches=touches, min_same_days=min_same,
                          follow_ups=one_email[0], no_reply_days=one_email[1],
                        inbox_reminder=one_email[2])
        if why == "no_reply":
            no_response(company, name, contacts)
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
            # forward_2.json (19 Oct 2026) uses the company note; the older forward.json the personal line.
            needed, label = forward_field(settings)
            if chain is None or not due["properties"].get(needed):
                log(f"{name}: the next person cannot be emailed yet (no earlier email to forward, or no "
                    f"{label}); will try again next run")
                continue
            if not ((chain.get("body") or {}).get("html") or (chain.get("body") or {}).get("text")):
                full = emails_api.get_email(chain["id"]) if hasattr(emails_api, "get_email") else None
                if full:  # the list of emails may leave out the body; read the one email in full
                    chain = {**chain, **full}
            html, text = forward_email(due, props, settings, notes, colleague=_name(prev), original=chain)
            first = min((e for es in history.values() for e in es),
                        key=lambda e: _sent_time(e) or parse_time("2999-01-01"), default=chain)
            if not last_check(company, name, contacts, details):
                continue
            try:
                emails_api.forward(chain, due["properties"]["email"], forward_subject(first), html, text)
            except Exception as err:
                log(f"{name}: Instantly refused the forward ({str(err)[:150]}); it is tried again next run")
                continue
            contact_updates.append((due["id"], statuses.props_or("contacts", "forwarded", "in_outreach")))
            result["forwards_sent"] += 1
            sent_rows.append(f"| {name} | {due['properties'].get('jobtitle') or 'next contact'} | Forward sent, naming "
                             f"the {prev['properties'].get('jobtitle') or 'colleague'} (Lead Status: Forward sent) |")
            log(f"{name}: no reply yet; the chain was forwarded to "
                f"{due['properties'].get('jobtitle') or 'the next contact'}, naming the colleague before them")
            continue
        if why == "reminder":
            past = history.get(due["id"]) or []
            if statuses.of("contacts", due) == "reminded":
                # HubSpot already says the reminder went (20 Oct 2026): never send it twice, even when
                # Instantly's record of it is missing. The loop ends after the usual gap.
                last = max(touch_times(due, touches) or [None], key=lambda t: t or parse_time("1970-01-01"))
                if last is None or (now or dt.datetime.now(dt.timezone.utc)) - last >= dt.timedelta(days=gap):
                    no_response(company, name, contacts)
                continue
            if not past:
                log(f"{name}: could not find person 1's email to reply to; will try again next run")
                continue
            html, text = reminder_email(due, props, settings, notes, mailbox=past[-1].get("eaccount"))
            own = reminder_subject(settings, due)  # a template with its own subject (follow_up_2, 15 Oct 2026)
            if not last_check(company, name, contacts, details):
                continue
            subject = own or past[0].get("subject") or ""
            if not own and not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            try:
                # Sent to person 1's own address in their thread (20 Oct 2026: a "reply" to our own
                # email went back to our own mailbox, so person 1 never got it).
                emails_api.send_in_thread(past[-1], due["properties"]["email"], subject, html, text)
            except Exception as err:
                log(f"{name}: Instantly refused the reminder ({str(err)[:150]}); it is tried again next run")
                continue
            if statuses.has("contacts", "reminded") and forward(statuses.of("contacts", due), "reminded"):
                contact_updates.append((due["id"], statuses.props("contacts", "reminded")))
            result["reminders_sent"] += 1
            sent_rows.append(f"| {name} | {due['properties'].get('jobtitle') or 'person 1'} | Reminder sent, as a reply "
                             "in their own thread (Lead Status: Reminder sent) |")
            log(f"{name}: the loop is done; person 1 was sent their reminder, in their own thread")
            continue
        campaign = last_campaign(contacts)
        if not due or why != "next" or not campaign or not due["properties"].get(PERSONAL_LINE):
            continue
        lead = lead_for(due, props, notes)  # nobody reached yet (e.g. person 1 bounced before sending)
        if not last_check(company, name, contacts, details):
            continue
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
    _summary(sent_rows, waiting_rows, opt_out_rows, blocklist["now"])
    log(f"Loop: {result['forwards_sent']} forwards, {result['reminders_sent']} reminders, "
        f"{result['next_contacts_added']} introductions added, {result['replied']} companies replied, "
        f"{result['no_reply']} finished with no reply (now Contacted, but no response, unqualified)")
    return result


LAST_RUN = None  # diagnostics/sync_last_run.md, set below


def write_last_run(lines):
    """Everything step 1 said in its last run, saved with the report (20 Oct 2026), so the reason for a
    problem can be read without opening GitHub's log. Email addresses are masked."""
    from .common import ROOT
    path = LAST_RUN or ROOT / "diagnostics" / "sync_last_run.md"
    masked = [re.sub(r"([A-Za-z0-9._%-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+)", r"\1***@\2", line) for line in lines]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Button 4, step 1: the last run\n\nWritten " + dt.datetime.now(dt.timezone.utc)
                        .strftime("%Y-%m-%d %H:%M UTC") + "\n\n```\n" + "\n".join(masked) + "\n```\n",
                        encoding="utf-8")
    except OSError:
        pass


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
    lines, code = [], 0

    def log(text):
        print(text)
        lines.append(str(text))
    try:
        key = os.environ.get("INSTANTLY_EMAILS_KEY")
        run(args.target, settings, HubSpot(), Instantly(), emails_api=Instantly(api_key=key) if key else None,
            log=log)
    except (PipelineError, HubSpotError, InstantlyError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        lines.append(f"ERROR: {err}")
        code = 1
    except Exception as err:  # anything unexpected: written down so it can be read without the GitHub log
        import traceback
        lines.append("UNEXPECTED ERROR: " + "".join(traceback.format_exception(err))[-3000:])
        write_last_run(lines)
        raise
    write_last_run(lines)
    if any(line.startswith("WARNING: Instantly's blocklist could not be read") for line in lines):
        # Emails went out as usual; the run is marked so GitHub emails about it (20 Oct 2026).
        from .common import ROOT
        (ROOT / "runs").mkdir(exist_ok=True)
        (ROOT / "runs" / "blocklist_unreadable").write_text("1\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
