"""Two campaigns a month (agreed 26 Oct 2026, Ariel).

From 23 to 26 Oct 2026 channels outside our usual ones were sent from their own campaigns ("Diablo |
OCT2026 | Other channels" and "Diablo | OCT2026 | Company inboxes | Other channels"), which were
never launched. Since 26 Oct 2026 there are only two campaigns a month: one for people and one for
everything else (company inboxes), whatever the channel. The bold heading "Why we think our bond
would be strong" with the personal line travels with each contact as its own bond paragraph instead.

Button 4 retires the "Other channels" campaigns (Ariel, 26 Oct 2026: delete them and put the
contacts back on gate 2):
  1. each contact Instantly never emailed goes back to "GATE2: Approved to send" in HubSpot first,
     so it is never lost; then its lead is deleted from that campaign, so button 4 adds it again to
     the month's campaign (with its bond paragraph, once that email has room for it);
  2. a lead Instantly has already emailed is never touched;
  3. an "Other channels" campaign left with no leads is deleted, and so is the preview campaign
     once the two campaigns have room for the bond paragraph.
Each contact gets a note on its HubSpot timeline. Nothing is ever deleted in HubSpot.
"""

import datetime as dt

from . import bond, timeline
from .common import load_company_notes
from .next_in_line import CONTACT_PROPS, COMPANY_PROPS, lead_for, tagged_company_of
from .stages import LeadStatus

PREVIEW_NAME = "TEST | Bond paragraph preview (delete me)"


def retire(hs, instantly, settings, log=print, notes_path=None):
    """Returns {"back_to_gate2": n, "kept": n, "deleted": [campaign names]}."""
    from .send import INBOX, PERSON, bond_ready, is_other_campaign
    done = {"back_to_gate2": 0, "kept": 0, "deleted": []}
    prefix = settings["sync"]["campaign_prefix"]
    statuses = LeadStatus(hs)
    ready = bond_ready(settings, PERSON) and bond_ready(settings, INBOX)
    for camp in instantly.list_campaigns():
        name = str(camp.get("name") or "")
        if name == PREVIEW_NAME:
            if ready:
                instantly.delete_campaign(camp["id"])
                done["deleted"].append(name)
                log(f"Deleted the preview campaign: {name}")
            continue
        if not (name.startswith(prefix) and is_other_campaign(name)):
            continue
        leads = instantly.list_leads(camp["id"])
        waiting = {l["email"].lower(): l for l in leads if l.get("email") and not l.get("timestamp_last_contact")}
        contacts = hs.tagged_read("contacts", list(waiting), ["email", "hs_lead_status"], id_property="email") \
            if waiting else []
        back = [(c, waiting[(c["properties"].get("email") or "").lower()]) for c in contacts
                if (c["properties"].get("email") or "").lower() in waiting]
        if back:
            hs.update_tagged("contacts", [(c["id"], statuses.props("contacts", "approved")) for c, _ in back])
            for _, lead in back:
                instantly.delete_lead(lead["id"])
            done["back_to_gate2"] += len(back)
            log(f'{name}: {len(back)} contacts never emailed are back on "GATE2: Approved to send"; button 4 adds '
                "them to the month's campaign")
            _note(hs, [c["id"] for c, _ in back], name, log, notes_path)
        kept = len(leads) - len(back)
        done["kept"] += kept
        if kept:
            log(f"{name}: {kept} leads stay (already emailed, or not found in HubSpot), so the campaign stays")
        else:
            instantly.delete_campaign(camp["id"])
            done["deleted"].append(name)
            log(f"Deleted the campaign: {name}")
    return done


def _note(hs, contact_ids, name, log, notes_path=None):
    """A timeline note, and the "added to the campaign" note is written again when it is added anew."""
    try:
        day = dt.date.today().strftime("%d %b %Y").lstrip("0")
        timeline.write(hs, [(cid, f'the "{name}" campaign was never launched, so this introduction was never sent; '
                                  f'back on GATE2: Approved to send ({day}) for the month\'s campaign') for cid in contact_ids], log)
        seen = timeline.load(notes_path)
        if seen.get("queued"):
            seen["queued"] -= {str(c) for c in contact_ids}
            timeline.save(seen, notes_path)
    except Exception as err:
        log(f"Could not write the timeline notes: {str(err)[:200]}")


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
        log(f"{missing} leads not given their bond paragraph: their contact or company could not be read in HubSpot")
    return out
