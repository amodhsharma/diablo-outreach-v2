"""Contacts marked "Unqualified: Rejected/Redirected by company owner" by hand (agreed 2 Nov 2026, Ariel).

For when the person is on leave, or their automatic reply points to someone else. A person only has to:

  1. add the new person in HubSpot with their email address and Lead source AUTO-OUTREACH, and link
     them to the company (Lead Status and Outreach order left empty);
  2. mark the original contact "Unqualified: Rejected/Redirected by company owner".

At the next run of button 3 (before anything else it does with the companies):

  - the original contact's Outreach order becomes 0 and it is never emailed again;
  - the people added by hand (AUTO-OUTREACH, linked to the company, no Lead Status) come first, then the
    company's other contacts still in the loop, numbered 1, 2, 3 ...; the ones added by hand are set to
    New, so the next mail-writing run writes their personal line;
  - the new number 1 goes to "GATE2: Approved to send" by itself: at once when its personal line is
    written, otherwise as soon as the line arrives (data/promoted.json, as for a dead address). Its
    introduction goes at the next run of button 4, and the week's wait for a reply starts from it;
  - the company's Lead Status stays as it is (Attempted to Contact); a company already closed as "no
    response" goes back to Attempted to Contact;
  - with nobody left, the company becomes "Unqualified: One contact inputted, which is unavailable".

A person added by hand without an email address holds the company back: button 3's summary lists it,
and the next run tries again once the address is in. Nothing is taken out of Instantly. Only
AUTO-OUTREACH records are changed.
"""

import datetime as dt

from .corrupt import _approved_now, load_promoted, save_promoted
from .next_in_line import CONTACT_PROPS, annotate, contacts_by_company, rank_of, tagged_company_of
from .schema import LEAD_STATUS, ORDER, PERSONAL_LINE, STOP_REASON

STILL_IN = ("pending", "approved", "queued", "sent")  # contacts that can still be emailed


def today():
    return dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y").lstrip("0")


def _done(contact):
    return str((contact.get("properties") or {}).get(ORDER) or "").strip() in ("0", "0.0")


def _title(contact, default="contact"):
    return ((contact.get("properties") or {}).get("jobtitle") or "").strip() or default


def run(hs, statuses, log=print, promoted_path=None):
    """Move each company on whose contact was marked Rejected/Redirected (see the top). Returns
    {"redirected": n, "rows": [summary rows], "no_email": [company names]}."""
    from .sync import stop_reasons  # sync imports corrupt, which this module imports
    out = {"redirected": 0, "rows": [], "no_email": []}
    if not statuses.has("contacts", "redirected"):
        return out
    marked = hs.tagged_search("contacts", [statuses.filter("contacts", "redirected")], CONTACT_PROPS,
                              max_results=2000)
    marked = [r for r in marked if not _done(r)]
    if not marked:
        return out
    owner_of, companies = tagged_company_of(hs, [r["id"] for r in marked], ["name", LEAD_STATUS])
    by_company = {}
    for r in marked:
        company_id = owner_of.get(str(r["id"]))
        if company_id:
            by_company.setdefault(company_id, []).append(r)
        else:
            out["rows"].append(f"| - | {_title(r)} | Not linked to an AUTO-OUTREACH company: link it, and the next "
                               "run moves the company on |")
    if not by_company:
        return out
    everyone = contacts_by_company(hs, list(by_company))
    promoted = load_promoted(promoted_path)
    updates, company_updates, reasons, company_reasons = {}, [], [], []

    def change(contact_id, props):
        updates.setdefault(str(contact_id), {}).update(props)

    for company_id, gone in by_company.items():
        company = companies.get(company_id) or {}
        name = (company.get("properties") or {}).get("name") or "a company"
        gone_ids = {str(r["id"]) for r in gone}
        people = annotate([c for c in everyone.get(company_id) or [] if str(c["id"]) not in gone_ids], statuses, {})
        added = [c for c in people if statuses.of("contacts", c) == ""]
        if any(not (c.get("properties") or {}).get("email") for c in added):
            out["no_email"].append(name)
            out["rows"].append(f"| {name} | - | A person added by hand has no email address: add it, and the next "
                               "run moves the company on |")
            log(f"{name}: a person added by hand has no email address; the company waits for the next run")
            continue
        added.sort(key=lambda c: (rank_of(c), str(c["id"])))
        added_ids = {str(c["id"]) for c in added}
        others = sorted((c for c in people if str(c["id"]) not in added_ids and c["state"] in STILL_IN
                         and 1 <= rank_of(c) < 999), key=rank_of)
        chain = added + others
        for r in gone:
            change(r["id"], {ORDER: "0"})
            reasons.append((r["id"], f"Rejected/Redirected by company owner ({today()}): the next person takes over"))
            out["rows"].append(f"| {name} | {_title(r)} | Rejected/Redirected: Outreach order 0 |")
        for c in added:
            change(c["id"], statuses.props("contacts", "found"))
            c["properties"][LEAD_STATUS] = statuses.props("contacts", "found")[LEAD_STATUS]
        for i, c in enumerate(chain, start=1):
            if rank_of(c) != i:
                change(c["id"], {ORDER: str(i)})
        out["redirected"] += len(gone)
        stage = statuses.of("companies", company) if company else "team"
        if chain:
            first = chain[0]
            title = _title(first, "the next contact")
            first_stage = statuses.of("contacts", first)
            if first_stage == "approved" or first["state"] in ("queued", "sent"):
                out["rows"].append(f"| {name} | {title} | Now number 1, already on its way |")
            elif first_stage == "copy_ready" and first["properties"].get(PERSONAL_LINE):
                change(first["id"], statuses.props("contacts", "approved"))
                promoted[str(first["id"])] = {"moved_up": today()}
                _approved_now(promoted, first["id"])
                out["rows"].append(f"| {name} | {title} | Now number 1 and GATE2: Approved to send; the introduction "
                                   "goes at the next run of button 4 |")
            else:
                promoted[str(first["id"])] = {"moved_up": today()}
                out["rows"].append(f"| {name} | {title} | Now number 1; its personal line is written at the next "
                                   "mail-writing run, then it goes to GATE2 by itself |")
            if stage == "no_response":
                company_updates.append((company_id, statuses.props("companies", "in_outreach")))
                out["rows"].append(f"| {name} | - | Company back on Attempted to Contact |")
            log(f"{name}: a contact was marked Rejected/Redirected; {title} is now number 1")
        elif stage in ("", "approved", "located", "in_outreach", "no_response"):
            company_updates.append((company_id, statuses.props("companies", "redirected_none")))
            company_reasons.append((company_id, f"Its one contact was marked Rejected/Redirected and nobody is left "
                                                f"({today()})"))
            out["rows"].append(f"| {name} | - | Nobody left: company now Unqualified: One contact inputted, which "
                               "is unavailable |")
            log(f'{name}: nobody is left after the Rejected/Redirected contact; the company is now "Unqualified: '
                'One contact inputted, which is unavailable"')
    hs.update_tagged("contacts", list(updates.items()))
    hs.update_tagged("companies", company_updates)
    stop_reasons(hs, "contacts", reasons, log)
    stop_reasons(hs, "companies", company_reasons, log)
    save_promoted(promoted, promoted_path)
    return out


def hold(contacts, due, statuses, promoted=None):
    """Why button 4 must not email `due` yet at this company, or "" (2 Nov 2026): a contact here is marked
    Rejected/Redirected and button 3 has not moved the others up yet, or someone ranked above `due` moved
    up and is still waiting for its personal line (so the new number 1 always goes first)."""
    from .corrupt import waiting_for_line
    promoted = load_promoted() if promoted is None else promoted
    for c in contacts:
        if statuses.of("contacts", c) == "redirected" and not _done(c):
            return "button 3 moving the others up after a Rejected/Redirected contact"
    for c in contacts:
        if str(c["id"]) != str(due["id"]) and rank_of(c) < rank_of(due) and waiting_for_line(c["id"], promoted):
            return "the new number 1's personal line"
    return ""


def summary(out):
    """The section for button 3's summary page, or "" when nothing happened."""
    if not out.get("rows"):
        return ""
    return ("### Contacts marked Rejected/Redirected by company owner\n\n| Company | Person (job title) | What "
            "happened |\n|---|---|---|\n" + "\n".join(out["rows"]))
