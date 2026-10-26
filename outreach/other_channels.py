"""Two campaigns a month (agreed 26 Oct 2026, Ariel).

From 23 to 26 Oct 2026 channels outside our usual ones were sent from their own campaigns ("Diablo |
OCT2026 | Other channels" and "Diablo | OCT2026 | Company inboxes | Other channels"). Since 26 Oct
2026 there are only two campaigns a month: one for people and one for everything else (company
inboxes), whatever the channel. The bold heading "Why we think our bond would be strong" with the
personal line travels with each contact as its own bond paragraph instead.

Button 4 moves the leads still waiting in an "Other channels" campaign into the matching campaign of
the two, once that campaign's email has room for the bond paragraph:
  1. each lead first gets its full set of details again from HubSpot, now with the bond paragraph,
     while it is still in the campaign that does not send (so nobody gets the email without it);
  2. then it is moved; a lead Instantly has already emailed is never moved (a moved lead counts as
     not yet emailed, so it would be emailed twice);
  3. an "Other channels" campaign left with no leads is deleted, as is the preview campaign.
Each moved contact gets a note on its HubSpot timeline. Nothing is ever deleted in HubSpot.
"""

import datetime as dt

from . import bond, timeline
from .common import load_company_notes
from .next_in_line import CONTACT_PROPS, COMPANY_PROPS, lead_for, tagged_company_of

PREVIEW_NAME = "TEST | Bond paragraph preview (delete me)"


def merge(hs, instantly, settings, log=print):
    """Returns {"moved": n, "kept": n, "deleted": [campaign names]}."""
    from .send import INBOX, PERSON, bond_ready, is_other_campaign, other_suffix, with_bond
    done = {"moved": 0, "kept": 0, "deleted": []}
    if not (bond_ready(settings, PERSON) and bond_ready(settings, INBOX)):
        return done
    prefix = settings["sync"]["campaign_prefix"]
    campaigns = instantly.list_campaigns()
    ids = {c.get("name"): c["id"] for c in campaigns}
    notes = load_company_notes()
    config = bond.load()
    for camp in campaigns:
        name = str(camp.get("name") or "")
        if name == PREVIEW_NAME:
            instantly.delete_campaign(camp["id"])
            done["deleted"].append(name)
            log(f"Deleted the preview campaign: {name}")
            continue
        if not (name.startswith(prefix) and is_other_campaign(name)):
            continue
        target = name[: -len(other_suffix())]
        target_id = ids.get(target)
        if not target_id:
            log(f'{name}: its leads stay for now, as the campaign "{target}" does not exist')
            continue
        leads = instantly.list_leads(camp["id"])
        emailed = [l for l in leads if l.get("timestamp_last_contact")]
        waiting = [l for l in leads if not l.get("timestamp_last_contact") and l.get("email")]
        ready = _with_details(hs, waiting, notes, config, with_bond, log)
        for lead_id, variables in ready.values():
            instantly.update_lead(lead_id, {"custom_variables": variables})
        if ready:
            instantly.move_leads(camp["id"], target_id, [lead_id for lead_id, _ in ready.values()])
            done["moved"] += len(ready)
            log(f'{name}: {len(ready)} leads not yet emailed moved to "{target}", each with its bond paragraph')
            try:
                day = dt.date.today().strftime("%d %b %Y").lstrip("0")
                timeline.write(hs, [(cid, f'introduction moved to the Instantly campaign "{target}" ({day}); the '
                                          '"Other channels" campaign it was in had not been launched')
                                    for cid in ready], log)
            except Exception as err:
                log(f"Could not write the timeline notes: {str(err)[:200]}")
        kept = len(leads) - len(ready)
        done["kept"] += kept
        if kept:
            log(f"{name}: {kept} leads stay ({len(emailed)} already emailed, so they are never moved)")
        else:
            instantly.delete_campaign(camp["id"])
            done["deleted"].append(name)
            log(f"Deleted the empty campaign: {name}")
    return done


def fill_waiting(hs, instantly, settings, log=print):
    """Before the two campaigns' email gets room for the bond paragraph: every lead there not yet
    emailed gets its bond_paragraph (empty for the usual channels), so no lead is ever left without a
    value for it. Returns how many leads were given one."""
    from .send import INBOX, PERSON, bond_ready, is_other_campaign, with_bond
    if not (bond_ready(settings, PERSON) and bond_ready(settings, INBOX)):
        return 0
    prefix = settings["sync"]["campaign_prefix"]
    notes, config, filled = load_company_notes(), bond.load(), 0
    for camp in instantly.list_campaigns():
        name = str(camp.get("name") or "")
        if not name.startswith(prefix) or is_other_campaign(name):
            continue
        waiting = [l for l in instantly.list_leads(camp["id"])
                   if l.get("email") and not l.get("timestamp_last_contact") and not _has_paragraph(l)]
        ready = _with_details(hs, waiting, notes, config, with_bond, log)
        for lead_id, variables in ready.values():
            instantly.update_lead(lead_id, {"custom_variables": variables})
        filled += len(ready)
        if ready:
            log(f"{name}: {len(ready)} leads not yet emailed given their bond paragraph (empty for the usual channels)")
    return filled


def _has_paragraph(lead):
    return any(bond.VARIABLE in (lead.get(k) or {}) for k in ("custom_variables", "payload"))


def _with_details(hs, leads, notes, config, with_bond, log):
    """{contact id: (Instantly lead id, full custom variables with the bond paragraph)} for the leads
    whose AUTO-OUTREACH contact and company HubSpot holds. Any other lead is left where it is."""
    by_email = {l["email"].lower(): l for l in leads}
    if not by_email:
        return {}
    contacts = hs.tagged_read("contacts", list(by_email), CONTACT_PROPS, id_property="email")
    owner_of, companies = tagged_company_of(hs, [c["id"] for c in contacts], COMPANY_PROPS)
    out = {}
    for c in contacts:
        company = companies.get(owner_of.get(str(c["id"])))
        lead = by_email.get((c["properties"].get("email") or "").lower())
        if not company or not lead or not lead.get("id"):
            continue
        fresh = with_bond(lead_for(c, company["properties"], notes), company["properties"], notes, config)
        out[str(c["id"])] = (lead["id"], fresh["custom_variables"])
    missing = len(by_email) - len(out)
    if missing:
        log(f"{missing} leads not moved: their contact or company could not be read in HubSpot")
    return out
