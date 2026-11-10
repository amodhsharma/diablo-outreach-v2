"""Replies that only point us to someone else (agreed 3 Nov 2026, Ariel).

A neutral reply (a real person, no yes or no: Instantly has not labelled it Interested or Not interested)
often says "my address has changed" or "please write to my colleague". So does an automatic reply saying
the person has left. At every run of button 4 each new one is read once, and the automation acts by
itself only when it is sure, that is when all of these hold:

  - the reply holds 1 to 3 email addresses that are new, at the same domain as the person or the company;
  - its words say it is a redirect ("please contact", "new address", "no longer", "has left", "now
    handled by" ..., in the languages of our markets); an automatic "has left" reply always does;
  - nobody has dealt with it yet: the person is not already Rejected/Redirected, and no new address is a
    team contact in HubSpot (one already tagged AUTO-OUTREACH is linked, never added twice).

Then it adds the new contact(s) (AUTO-OUTREACH, linked to the company, job title "Referred by
colleague", legal basis "Legitimate interest - Lead"), marks the person who replied
"Unqualified: Rejected/Redirected by company owner" and puts the company back on Attempted to Contact.
Button 3 then makes the new contact number 1 (redirect.py), button 4 copies the line, approves it and
sends the introduction.

When it is not sure it changes nothing: the company stays paused on In Progress for a person to handle.
Either way the case goes into the email to ALERT_TO (Amodh only) at the time of the daily summary:
how many such replies came in, how many were switched, and the details of those left for a person.

A company paused on In Progress goes back into the loop by itself (release, 10 Nov 2026, Ariel) when:
  - the person who replied is now Rejected/Redirected and nobody else there is really in conversation
    (contacts left on In Progress by the rules before 2 Nov 2026, who never replied, do not count);
  - the "reply" turns out to be an out-of-office after all (it is then read again as one);
  - a neutral reply has waited 7 days with nobody changing anything: the person who replied keeps In
    Progress and the loop passes them by ("parked"), the others there carry on.
Contacts that were paused with it go back to where they were: Attempted to Contact if Instantly already
has them, otherwise GATE2 (with a line) or New.

Also (10 Nov 2026, Ariel):
  - a colleague copied into the reply ("I have looped in Kate, our buyer") counts like an address in the
    text, when the reply's words say it is a redirect;
  - an out-of-office that gives a stand-in at the same company ("in urgent cases contact the shop:
    shop@...") adds that address as a new contact, who gets their own introduction; the person away is
    left as they are and the loop carries on.

data/referrals.json remembers which replies were read (HubSpot IDs, the day and the outcome only; no
names, addresses or text).
"""

import datetime as dt
import json
import os
import re
import sys

from .common import ROOT
from .schema import LEAD_STATUS, LEGAL_BASIS, LEGAL_BASIS_LEAD, TAG, TAG_PROPERTY

FILE = ROOT / "data" / "referrals.json"
INDIA = dt.timezone(dt.timedelta(hours=5, minutes=30))
MAX_NEW = 3
PER_RUN = 20  # replies read per run of button 4 (Instantly's emails are slow to read); the rest next run
RULES = 2  # 10 Nov 2026: replies left for a person under the first rules are read once more under these
STALE_DAYS = 7  # a neutral reply nobody acted on for this many days: the company goes on (10 Nov 2026)
JOB_TITLE = "Referred by colleague"
EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
OURS = re.compile(r"@(?:[a-z0-9-]+\.)*(diablo[a-z0-9-]*\.[a-z.]+)$", re.I)
# Only wording that clearly sends us elsewhere (3 Nov 2026, after review: "responsible for", "instead", "no longer"
# on their own also appear in replies from the right person, so they no longer count).
REDIRECT = re.compile(
    r"(please (contact|write to|reach out to|email|send (it|your|this|them) to)|kindly (contact|write to|reach out to)|"
    r"contact (my|our) (colleague|team|department|purchas|buyer|category)|reach out to (my|our) (colleague|team)|"
    r"new (e-?mail )?address|e-?mail address (has )?changed|address has changed|"
    r"no longer (with|at|work|employed|part of|in charge|responsible)|(has|have) left (the|our|this)|"
    r"now (handled|managed|looked after) by|forward(ed)? (it|your|this) to|"
    r"wenden sie sich|kontaktieren sie|schreiben sie (bitte )?an|neue (e-?mail-?)?adresse|nicht mehr (bei|im|f[üu]r)|"
    r"veuillez contacter|merci de contacter|[ée]crivez [àa]|nouvelle adresse|n'est plus (chez|dans|en charge)|"
    r"rivolgersi a|contattare|scrivere a|nuovo indirizzo|non (è|e) pi[uù] (in|con|presso|responsabile)|"
    r"contacte con|escriba a|nueva direcci[óo]n|ya no (trabaja|est[áa]|es responsable)|"
    r"neem contact op met|nieuw (e-?mail)?adres|niet meer (bij|werkzaam))", re.I)
# A colleague copied into the reply (10 Nov 2026, Daily Blooms): only words that say so.
COPIED = re.compile(
    r"(point(ed)? you (in the direction of|to(wards)?) (my|our)|(has|have) been (looped|cc'?d|copied) in|"
    r"loop(ed|ing)? (her|him|them|my colleague|our) [a-z ]{0,30}in(to)?\b|i(?: have|'ve) (cc'?d|copied|looped in) "
    r"(my|our|her|him|them)\b|(cc'?d|copied) (her|him|them|my colleague) (in|on)|in (kopie|cc) (gesetzt|genommen)|"
    r"(mis|mets|met) en copie|messo in copia|(puesto|pongo) en copia|in de cc (gezet|geplaatst))", re.I)
# An out-of-office naming a stand-in ("in urgent cases please contact ...") (10 Nov 2026, VELOMANIA).
COVER = re.compile(
    r"(in (case of )?(urgent|urgency|an emergency|emergencies)|for (urgent|immediate) (matters|enquiries|inquiries|"
    r"requests|assistance|questions)|urgent (matters|enquiries|inquiries|requests)|in my absence|during my absence|"
    r"while i am (away|out)|in dringenden f[äa]llen|in eiligen f[äa]llen|w[äa]hrend meiner abwesenheit|vertretung|"
    r"en cas d'urgence|pour (toute )?(demande|question)s? urgentes?|en mon absence|pendant mon absence|"
    r"vous pouvez contacter|in caso di urgenza|per urgenze|in mia assenza|durante la mia assenza|"
    r"en caso de urgencia|para (asuntos|temas) urgentes|durante mi ausencia|in dringende gevallen|"
    r"bij dringende zaken|tijdens mijn afwezigheid)", re.I)
# Public mail services: an address there is never "the same company" just because it shares the domain.
FREE_MAIL = re.compile(
    r"^(gmail|googlemail|yahoo|ymail|hotmail|outlook|live|msn|icloud|me|mac|aol|gmx|web|mail|yandex|proton|"
    r"protonmail|t-online|orange|libero|wp|o2|seznam|bigpond|optusnet|xtra|rediffmail|qq|163|126)\.", re.I)
NEAR = 250  # the address must come within this many characters after the redirect words
# A reply that also asks us for something is a buyer copying a colleague in, not a hand-over (10 Nov 2026).
ASKS = re.compile(r"(\?|\b(send|price|prices|pricing|price list|catalogue|catalog|samples?|quote|quotation|offer|"
                  r"preis|preise|preisliste|katalog|muster|prix|tarifs?|catalogue|[ée]chantillons?|prezzi|listino|"
                  r"campioni|precios?|cat[áa]logo|muestras?|prijzen|prijslijst)\b)", re.I)


def today_india(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(INDIA).date().isoformat()


def load(path=None):
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data, path=None):
    path = path or FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _domain(address):
    return (address or "").rsplit("@", 1)[-1].lower().strip()


def _site(domain):
    d = (domain or "").lower().strip()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    return d[4:] if d.startswith("www.") else d


def addresses_in(text, sender=""):
    """The email addresses in a text, lower case, without the sender's own and without ours."""
    found = []
    for a in EMAIL.findall(text or ""):
        a = a.strip(".'").lower()
        if a == (sender or "").lower() or OURS.search(a) or a in found:
            continue
        found.append(a)
    return found


def name_from(address):
    """First and last name from an address such as anna.meier@ or anna_meier@; empty when unclear."""
    local = address.split("@", 1)[0]
    parts = [p for p in re.split(r"[._-]+", local) if p.isalpha() and len(p) > 1]
    if len(parts) == 2:
        return parts[0].capitalize(), parts[1].capitalize()
    return "", ""


def _near_redirect(text, address, words=None):
    """True when the address comes shortly after redirect wording (not, say, alone in a signature)."""
    low = (text or "").lower()
    at = low.find(address)
    return any(0 <= at - m.end() <= NEAR for m in (words or REDIRECT).finditer(low[:at])) if at >= 0 else False


def _same_company(addresses, sender, company_domain):
    ours = {d for d in (_domain(sender), _site(company_domain)) if d and not FREE_MAIL.match(d)}
    return [a for a in addresses if _domain(a) in ours or any(_domain(a).endswith("." + d) for d in ours)]


def copied_in(emails, sender=""):
    """The addresses a reply was also sent to (To and CC), without the sender's own and without ours."""
    found = []
    for e in emails or ():
        for field in ("to_address_email_list", "cc_address_email_list"):
            value = e.get(field) or ""
            value = ",".join(value) if isinstance(value, (list, tuple)) else str(value)
            for a in addresses_in(value, sender):
                if a not in found:
                    found.append(a)
    return found


def judge(text, sender, company_domain, automatic_left=False, copied=()):
    """(new addresses at the company, why not sure or ""). copied: the colleagues the reply was also sent to
    (10 Nov 2026): they count when the reply's words say it is a redirect."""
    found = addresses_in(text, sender)
    cc = [a for a in _same_company(copied, sender, company_domain) if a not in found]
    same = _same_company(found, sender, company_domain) + cc
    if not found and not cc:
        return [], "no email address in the reply"
    if not same:
        return [], "the address in the reply is not at the company's own domain"
    if len(same) > MAX_NEW:
        return [], f"more than {MAX_NEW} addresses in the reply"
    if not automatic_left:
        if not all(_near_redirect(text, a) for a in same if a not in cc):
            return [], "no clear wording that it is a redirect"
        if cc and not (REDIRECT.search(text or "") or COPIED.search(text or "")):
            return [], "a colleague was copied in, but no clear wording that it is a redirect"
        if cc and ASKS.search(text or ""):
            return [], "a colleague was copied in, but the reply also asks us for something"
    return same, ""


def judge_cover(text, sender, company_domain):
    """The stand-in(s) an out-of-office names at the same company ("in urgent cases contact ..."), or []."""
    same = _same_company(addresses_in(text, sender), sender, company_domain)
    if not same or len(same) > MAX_NEW:
        return []
    near = [a for a in same if _near_redirect(text, a, COVER) or _near_redirect(text, a)]
    return near if len(near) == len(same) else []


def _reply_parts(emails_api, address, kind):
    """(the words of their replies above any quoted email, the emails themselves). kind: "real" (real
    replies), "left" (automatic replies saying they have left) or "cover" (other automatic replies that
    name a stand-in)."""
    from .corrupt import LEFT, _is_notice
    from .sync import _with_body, auto_reply_reason, reply_text
    texts, emails = [], []
    for e in emails_api.thread_emails(address):
        if e.get("ue_type") != 2 or _is_notice(e):
            continue
        full = _with_body(emails_api, e)
        is_auto = bool(auto_reply_reason(full))
        words = reply_text(full) or str(full.get("content_preview") or "")
        left = is_auto and LEFT.search(" ".join([str(full.get("subject") or ""), words]))
        if (kind == "real" and not is_auto) or (kind == "left" and left) or (
                kind == "cover" and is_auto and not left and (COVER.search(words) or REDIRECT.search(words))):
            texts.append(words)
            emails.append(full)
    return texts, emails


def _reply_texts(emails_api, address, automatic):
    """The words of their replies: the real ones, or for `automatic` the automatic ones that matter here."""
    if not automatic:
        return _reply_parts(emails_api, address, "real")[0]
    return _reply_parts(emails_api, address, "left")[0] or _reply_parts(emails_api, address, "cover")[0]


def process(hs, emails_api, statuses, seen, log=print, path=None, now=None):
    """Read each new neutral reply, or automatic "has left" reply, once (see the top). Returns
    {"switched": n, "unsure": n}."""
    from .next_in_line import tagged_company_of
    from .stages import EMAILED
    from .sync import stop_reasons
    out = {"switched": 0, "unsure": 0, "added": 0, "ids": set()}
    if emails_api is None or not statuses.has("contacts", "redirected"):
        return out
    state = load(path)
    handled = state.setdefault("handled", {})
    day = today_india(now)
    todo = []
    for r, lead, event in seen or ():
        cid, stage = str(r["id"]), statuses.of("contacts", r)
        prev = handled.get(cid)
        if prev and not (prev.get("outcome") == "unsure" and int(prev.get("rules") or 1) < RULES):
            continue
        # The Lead Status read before this run's changes: In Progress, or still emailed when the reply is new.
        if event == "replied" and stage in ("replied",) + EMAILED and (lead or {}).get("lt_interest_status") in (None, 0):
            todo.append((r, False))
        elif event == "out of office" and stage in EMAILED:
            todo.append((r, True))
    if not todo:
        return out
    todo = todo[:PER_RUN]
    owner_of, companies = tagged_company_of(hs, [r["id"] for r, _ in todo],
                                            ["name", "domain", "country", "city", "hubspot_owner_id", LEAD_STATUS])
    for r, automatic in todo:
        try:
            _one(hs, emails_api, statuses, r, automatic, owner_of, companies, handled, day, out, log)
        except Exception as err:  # this one is read again next run; the others carry on
            log(f"A reply naming someone else could not be handled ({str(err)[:150]}); tried again next run")
        save(state, path)  # after each, so what was done is never done twice
    return out


def _record(handled, cid, entry):
    """Write the outcome; a reply read again keeps its first day (the 7 days count from it)."""
    prev = handled.get(cid) or {}
    entry = dict(entry, rules=RULES)
    for keep in ("parked", "replies"):  # a parked reply read again stays parked
        if prev.get(keep) and entry.get("outcome") in ("unsure", "none"):
            entry[keep] = prev[keep]
    if prev.get("day") and entry.get("outcome") == "unsure":
        entry["day"] = prev["day"]
    handled[cid] = entry


def _one(hs, emails_api, statuses, r, automatic, owner_of, companies, handled, day, out, log):
    from .next_in_line import tagged_company_of
    from .sync import stop_reasons
    cid = str(r["id"])
    address = (r["properties"].get("email") or "").lower()
    company_id = owner_of.get(cid)
    company = companies.get(company_id) or {}
    cp = company.get("properties") or {}
    if not company_id or statuses.of("companies", company) not in ("replied", "in_outreach", "approved",
                                                                     "located", "no_response"):
        return
    cover = False
    try:
        texts, emails = _reply_parts(emails_api, address, "left" if automatic else "real")
        if automatic and not texts:  # 10 Nov 2026: an out-of-office naming a stand-in at the company
            texts, emails = _reply_parts(emails_api, address, "cover")
            cover = bool(texts)
    except Exception as err:  # read again next run
        log(f"{cp.get('name')}: the reply could not be read ({str(err)[:150]}); tried again next run")
        return
    if not texts:
        _record(handled, cid, {"day": day, "outcome": "none"})  # an ordinary out-of-office, or nothing to read
        return
    text = "\n".join(texts)
    if cover:
        new = judge_cover(text, address, cp.get("domain"))
        why = "" if new else "no stand-in at the company's own domain"
        if not new:
            _record(handled, cid, {"day": day, "outcome": "none"})
            return
    else:
        new, why = judge(text, address, cp.get("domain"), automatic_left=automatic,
                         copied=[] if automatic else copied_in(emails, address))
    if automatic and why and not addresses_in(text, address):
        # "Has left" and no address: the dead-address rule (corrupt.py) handles it as before.
        _record(handled, cid, {"day": day, "outcome": "none"})
        return
    known = {}
    if new:
        # Read every contact with these addresses, the team's too, so nobody is ever added twice.
        known = {(x["properties"].get("email") or "").lower(): x for x in
                 hs.batch_read("contacts", new, ["email", TAG_PROPERTY], id_property="email")}
        if any((x.get("properties") or {}).get(TAG_PROPERTY) != TAG for x in known.values()):
            new, why = [], "the new address is already one of the team's own contacts in HubSpot"
        elif known:
            elsewhere, _ = tagged_company_of(hs, [x["id"] for x in known.values()], ["name"])
            if any(elsewhere.get(str(x["id"])) not in (None, str(company_id)) for x in known.values()):
                new, why = [], "the new address is already a contact at another company in HubSpot"
    if why:
        _record(handled, cid, {"day": day, "outcome": "unsure", "company": str(company_id), "why": why,
                               "automatic": automatic})
        out["unsure"] += 1
        log(f"{cp.get('name')}: a reply names someone else, but not clearly enough to act on ({why}); "
            "left for a person")
        return
    records = []
    for a in new:
        if a in known:
            continue
        first, last = name_from(a)
        # Lead Status stays empty on purpose: button 3 (redirect.py) numbers them and sets them to New.
        props = {"email": a, "jobtitle": JOB_TITLE, LEGAL_BASIS: LEGAL_BASIS_LEAD, "company": cp.get("name") or ""}
        if cover:  # a stand-in: New, so button 3 numbers it after the others and copies a line (no redirect)
            props.update(statuses.props("contacts", "found"))
        props.update({k: v for k, v in (("firstname", first), ("lastname", last),
                                        ("country", cp.get("country")), ("city", cp.get("city")),
                                        ("hubspot_owner_id", cp.get("hubspot_owner_id"))) if v})
        records.append(props)
    created = hs.create_tagged("contacts", records) if records else []
    ids = [str(x["id"]) for x in created if x] + [str(x["id"]) for x in known.values()]
    hs.associate_primary_tagged([(i, company_id) for i in ids])
    if cover:
        # The person is only away: they stay as they are. The stand-in is numbered by button 3, gets the
        # line copied and their own introduction (hand_tagged.py, chain.fill_open).
        if statuses.of("companies", company) == "no_response":
            hs.update_tagged("companies", [(company_id, statuses.props("companies", "in_outreach"))])
        _record(handled, cid, {"day": day, "outcome": "added", "company": str(company_id), "new": ids,
                               "automatic": True})
        out["added"] += 1
        log(f"{cp.get('name')}: an out-of-office named {len(ids)} stand-in(s) at the company; added as new "
            "contact(s), who get their own introduction")
        return
    hs.update_tagged("contacts", [(cid, statuses.props("contacts", "redirected"))])
    stop_reasons(hs, "contacts", [(cid, f"Redirected automatically ({dt.date.fromisoformat(day).strftime('%d %b %Y').lstrip('0')}): "
                                        "their reply named a new contact")], log)
    _record(handled, cid, {"day": day, "outcome": "switched", "company": str(company_id), "new": ids,
                           "automatic": automatic})
    out["switched"] += 1
    out["ids"].add(cid)
    log(f"{cp.get('name')}: a reply named {len(ids)} new contact(s); added, and the person who replied is "
        "now Rejected/Redirected")


def _days(since, day):
    try:
        return (dt.date.fromisoformat(day) - dt.date.fromisoformat(since)).days
    except (TypeError, ValueError):
        return 0


def _history(emails_api, address):
    """(answered, emailed) from Instantly's emails, for a contact Instantly's Diablo campaigns no longer hold:
    answered is "reply" (a real one), "auto" (only automatic answers) or ""; None when it cannot be read."""
    from .sync import _with_body, auto_reply_reason
    if emails_api is None or not address:
        return None
    try:
        thread = emails_api.thread_emails(address)
        got = [_with_body(emails_api, e) for e in thread if e.get("ue_type") == 2]
    except Exception:
        return None
    answered = ("reply" if any(not auto_reply_reason(e) for e in got) else "auto") if got else ""
    return answered, any(e.get("ue_type") in (1, 3) for e in thread)


def wake(hs, statuses, leads, log=print, path=None):
    """A parked contact who writes again (more replies in Instantly than when parked) is read again, and their
    company is paused on In Progress once more, with the others there on "Colleague replied". Returns how many."""
    from .next_in_line import contacts_by_company, tagged_company_of
    from .sync import mark_colleagues
    state = load(path)
    handled = state.get("handled") or {}
    parked = {cid: e for cid, e in handled.items() if e.get("parked")}
    if not parked or leads is None:
        return 0
    rows = hs.tagged_read("contacts", list(parked), ["email", LEAD_STATUS])
    woke = []
    for r in rows:
        lead = leads.get(((r.get("properties") or {}).get("email") or "").lower())
        entry = parked[str(r["id"])]
        if lead is None or "replies" not in entry:
            continue  # their count was not known when parked: nothing to compare with
        if int(lead.get("email_reply_count") or 0) > int(entry.get("replies") or 0):
            woke.append(r)
    if not woke:
        return 0
    owner_of, companies = tagged_company_of(hs, [r["id"] for r in woke], ["name", LEAD_STATUS])
    everyone = contacts_by_company(hs, sorted({c for c in owner_of.values() if c}))
    for r in woke:
        handled.pop(str(r["id"]), None)  # read again at the next run, as a new reply
        company_id = owner_of.get(str(r["id"]))
        company = companies.get(company_id)
        if not company or statuses.of("companies", company) not in ("in_outreach", "approved", "located", "no_response"):
            continue
        name = (company.get("properties") or {}).get("name")
        hs.update_tagged("companies", [(company_id, statuses.props("companies", "replied"))])
        mark_colleagues(hs, statuses, everyone.get(company_id) or [], [r["id"]], "colleague_replied", log, name)
        log(f"{name}: the person whose reply had waited 7 days wrote again; the company is paused on In Progress")
    save(state, path)
    return len(woke)


def release(hs, statuses, log=print, leads=None, seen=None, path=None, now=None, emails_api=None):
    """Companies paused on In Progress that go back to Attempted to Contact (see the top). Returns how many.

    seen: this run's (contact, lead, event) from sync. A contact on In Progress is really in conversation unless
    this run reads its answers as automatic, Instantly holds it with no reply, or (not in Instantly's Diablo
    campaigns any more) its emails show no real reply. Parked contacts never count. Without `seen` every In
    Progress contact counts, as before 10 Nov 2026."""
    from .next_in_line import contacts_by_company
    from .stages import TEAM
    if not statuses.has("contacts", "redirected"):
        return 0
    paused = hs.tagged_search("companies", [statuses.filter("companies", "replied")], ["name", LEAD_STATUS],
                              max_results=2000)
    if not paused:
        return 0
    state = load(path)
    handled = state.setdefault("handled", {})
    day = today_india(now)
    events = None if seen is None else {str(r["id"]): event for r, _, event in seen}
    everyone = contacts_by_company(hs, [c["id"] for c in paused])
    back, contacts = [], []
    history = {}

    def past(c):
        address = (c["properties"].get("email") or "").lower()
        if address not in history:
            history[address] = _history(emails_api, address)
        return history[address]

    def really_talking(c):
        if events is None:
            return True
        event = events.get(str(c["id"]))
        if event == "out of office":
            return False
        if event in ("emailed", "queued"):
            return False  # Instantly holds them and they never replied: left on In Progress by older rules
        if event is not None:
            return True
        found = past(c)
        return found is None or found[0] == "reply"  # unreadable: counted, so nobody is reset by mistake

    for company in paused:
        name = (company.get("properties") or {}).get("name")
        people = everyone.get(company["id"]) or []
        stages = {str(c["id"]): statuses.of("contacts", c) for c in people}
        if {"sales", TEAM} & set(stages.values()):
            continue
        on_hold = [c for c in people if stages[str(c["id"])] == "replied"
                   and not (handled.get(str(c["id"])) or {}).get("parked")]
        real = [c for c in on_hold if really_talking(c)]
        misread = [c for c in on_hold if events is not None and events.get(str(c["id"])) == "out of office"]
        why = ""
        if not real and "redirected" in stages.values():
            why = "the person who replied is Rejected/Redirected and nobody else there is in conversation"
        elif not real and misread:
            why = "the reply was an out-of-office after all"
        elif real and all((handled.get(str(c["id"])) or {}).get("outcome") == "unsure"
                          and _days((handled.get(str(c["id"])) or {}).get("day"), day) >= STALE_DAYS for c in real):
            why = f"the reply has waited {STALE_DAYS} days with nobody acting on it"
        if not why:
            continue
        if leads is not None and any(
                stages[str(c["id"])] in ("colleague_replied", "replied") and c not in real
                and (c["properties"].get("email") or "").lower() not in leads and past(c) is None for c in people):
            log(f"{name}: would go back on Attempted to Contact, but Instantly's emails could not be read for "
                "someone there; tried again next run")
            continue
        back.append((company["id"], statuses.props("companies", "in_outreach")))
        for c in people:
            own, cid = stages[str(c["id"])], str(c["id"])
            if c in real:
                address = (c["properties"].get("email") or "").lower()
                handled[cid]["parked"] = day  # keeps In Progress; the loop passes them by
                if address in (leads or {}):
                    handled[cid]["replies"] = int(leads[address].get("email_reply_count") or 0)
                continue
            if own not in ("colleague_replied", "replied") or (handled.get(cid) or {}).get("parked"):
                continue
            # Paused with the company (a colleague, an In Progress left by older rules, a misread
            # out-of-office): back to where they were, never to GATE2 or New once emailed.
            email = (c["properties"].get("email") or "").lower()
            emailed = leads is not None and email in leads
            if not emailed and leads is not None:
                emailed = bool((past(c) or ("", True))[1])
            if emailed:
                stage = "in_outreach"
            else:
                has_line = bool((c["properties"].get("diablo_personal_line") or "").strip())
                stage = "approved" if has_line else "found"
            contacts.append((c["id"], statuses.props("contacts", stage)))
            if own == "replied" and (handled.get(cid) or {}).get("outcome") == "unsure":
                handled.pop(cid)  # read again next run, as what it really was (an out-of-office)
        state.setdefault("resumed", {})[str(company["id"])] = {"day": day, "why": why}
        log(f"{name}: {why}, so the company is back on Attempted to Contact")
    hs.update_tagged("companies", back)
    hs.update_tagged("contacts", contacts)
    if back:
        cutoff = (dt.date.fromisoformat(day) - dt.timedelta(days=30)).isoformat()
        state["resumed"] = {c: e for c, e in state["resumed"].items() if (e.get("day") or "") >= cutoff}
        save(state, path)
    return len(back)


# ---- The daily email to ALERT_TO --------------------------------------------------------------------

def report_text(hs, emails_api, statuses, day, path=None):
    """(subject, text) of the email about the replies read on `day` (an India date), or (None, None)."""
    from .common import PRODUCTION_PORTAL_ID
    state = load(path)
    handled = state.get("handled") or {}
    cases = {cid: e for cid, e in handled.items() if e.get("outcome") in ("switched", "unsure", "added")}
    todays = {cid: e for cid, e in cases.items() if e.get("day") == day}
    waiting = {cid: e for cid, e in cases.items() if e.get("outcome") == "unsure" and (e.get("day") or "") < day}
    ids = sorted(set(todays) | set(waiting) | {n for e in todays.values() for n in e.get("new") or []})
    people = {str(r["id"]): r for r in hs.tagged_read("contacts", ids, ["email", "jobtitle", LEAD_STATUS])} if ids else {}
    resumed = {c: e for c, e in (state.get("resumed") or {}).items() if e.get("day") == day}
    company_ids = sorted({e.get("company") for e in list(todays.values()) + list(waiting.values()) if e.get("company")}
                         | set(resumed))
    companies = {str(c["id"]): c for c in hs.tagged_read("companies", company_ids, ["name", LEAD_STATUS])} if company_ids else {}
    try:
        portal = hs.portal_id()
    except Exception:
        portal = PRODUCTION_PORTAL_ID

    def company(e):
        return ((companies.get(e.get("company")) or {}).get("properties") or {}).get("name") or "a company"

    def job(cid):
        return ((people.get(cid) or {}).get("properties") or {}).get("jobtitle") or "contact"

    def still_paused(e):
        c = companies.get(e.get("company"))
        return bool(c) and statuses.of("companies", c) == "replied"

    switched = [(cid, e) for cid, e in todays.items() if e["outcome"] == "switched"]
    added = [(cid, e) for cid, e in todays.items() if e["outcome"] == "added"]
    unsure = [(cid, e) for cid, e in todays.items() if e["outcome"] == "unsure"]
    old = [(cid, e) for cid, e in waiting.items() if still_paused(e)]
    long_day = dt.date.fromisoformat(day)
    lines = [f"Replies read on {long_day.strftime('%A')} {long_day.day} {long_day.strftime('%B %Y')} that only named "
             "someone else (no clear yes or no), or automatic replies saying the person has left.", "",
             f"Seen: {len(todays)}", f"Switched automatically: {len(switched)}", f"Left for you: {len(unsure)}"]
    if switched:
        lines += ["", "SWITCHED AUTOMATICALLY (the old contact is now Rejected/Redirected; the new one is emailed "
                      "after the next runs of buttons 3 and 4):"]
        for cid, e in switched:
            new = ", ".join(((people.get(n) or {}).get("properties") or {}).get("email") or "new contact"
                            for n in e.get("new") or [])
            lines.append(f"- {company(e)}: {job(cid)} -> {new}")
    if added:
        lines += ["", "STAND-INS ADDED FROM AN OUT-OF-OFFICE (the person away stays as they are; the stand-in gets "
                      "their own introduction after the next runs of buttons 3 and 4):"]
        for cid, e in added:
            new = ", ".join(((people.get(n) or {}).get("properties") or {}).get("email") or "new contact"
                            for n in e.get("new") or [])
            lines.append(f"- {company(e)}: {job(cid)} is away -> {new}")
    if resumed:
        lines += ["", "BACK IN THE LOOP (the company is on Attempted to Contact again):"]
        for company_id, e in sorted(resumed.items()):
            lines.append(f"- {company({'company': company_id})}: {e.get('why')}")
    if unsure:
        lines += ["", f"LEFT FOR YOU (nothing was changed for the reply; a company with a reply waits on In "
                      f"Progress for up to {STALE_DAYS} days, then goes on by itself, and an automatic \"has left\" "
                      "reply still marks that address Contact corrupt):"]
        for cid, e in unsure:
            address = ((people.get(cid) or {}).get("properties") or {}).get("email") or ""
            excerpt = ""
            if emails_api is not None and address:
                try:
                    texts = _reply_texts(emails_api, address, bool(e.get("automatic")))
                    excerpt = " ".join(" ".join(texts).split())[:400]
                except Exception:
                    excerpt = ""
            lines += [f"- {company(e)} (https://app.hubspot.com/contacts/{portal}/record/0-2/{e.get('company')})",
                      f"  Who replied: {job(cid)}", f"  Why it was not sure: {e.get('why')}"]
            if excerpt:
                lines.append(f'  Their reply: "{excerpt}"')
    if old:
        lines += ["", f"Still waiting for you from earlier days: {len(old)} ("
                      + ", ".join(sorted({company(e) for _, e in old})) + ")"]
    if not todays and not old and not resumed:
        return None, None
    lines += ["", "Kind regards,", "Diablo outreach"]
    return f"Partner outreach: replies naming someone else ({long_day.day} {long_day.strftime('%b %Y')})", "\n".join(lines)


def main(argv=None):
    import argparse
    from .common import check_target
    from .hubspot_client import HubSpot
    from .instantly_client import Instantly
    from .stages import LeadStatus
    from . import alert
    p = argparse.ArgumentParser(description="Email ALERT_TO about yesterday's replies that named someone else")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--preview", action="store_true", help="show the email, send nothing")
    args = p.parse_args(argv)
    hs = HubSpot()
    check_target(hs, args.target)
    key = os.environ.get("INSTANTLY_EMAILS_KEY")
    yesterday = (dt.datetime.now(INDIA).date() - dt.timedelta(days=1)).isoformat()
    subject, text = report_text(hs, Instantly(api_key=key) if key else None, LeadStatus(hs), yesterday)
    if not subject:
        print("No reply named someone else yesterday, and none is waiting: nothing to send.")
        return 0
    print(subject + "\n\n" + text)
    if not args.preview:
        alert.send(subject, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
