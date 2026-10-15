"""Save the contacts that need email lines to mail/pending.json, for the outreach-mail-writing skill.

A contact needs lines when it is an AUTO-OUTREACH contact whose Lead Status is "New". For each one the
file holds the HubSpot contact ID, job title and seniority, plus what the research found about
its company (from data/company_notes.json). No names, emails or phone numbers are saved: the
email template fills in the first name itself, so the skill never needs them.

Runs as the last step of button "3 - Find contacts" and after every lines import.

Usage:
    python -m outreach.export_for_lines --target test
"""

import argparse
import json
import os
import sys

from .common import ROOT, PipelineError, channel_of, check_target, load_company_notes, load_settings, market_of, now_iso
from .find_contacts import hierarchy_level
from .hubspot_client import HubSpot, HubSpotError
from .next_in_line import COMPANY_PROPS, tagged_company_of
from .schema import LEAD_STATUS, ORDER
from .stages import COMPANY_STOPPED, LeadStatus

PENDING_FILE = ROOT / "mail" / "pending.json"


def collect(hs, max_results=5000, exclude=(), settings=None, new_ids=()):
    """HubSpot's search can lag a few seconds behind an update, so every status is read again
    directly before a contact is listed; `exclude` drops contacts just updated by the caller.
    `new_ids` are contacts button 3 has just added: the search may not show them yet, so they
    are read by their ID and listed straight away (agreed 15 Oct 2026)."""
    statuses = LeadStatus(hs)
    hierarchy = ((settings or load_settings()).get("contacts") or {}).get("hierarchy") or []
    props = ["jobtitle", ORDER, LEAD_STATUS]
    found = hs.tagged_search("contacts", [statuses.filter("contacts", "found")], props, max_results=max_results)
    exclude = {str(i) for i in exclude}
    ids = list(dict.fromkeys([str(c["id"]) for c in found] + [str(i) for i in new_ids]))
    ids = [i for i in ids if i not in exclude]
    contacts = [c for c in hs.tagged_read("contacts", ids, props)
                if statuses.of("contacts", c) == "found"] if ids else []
    if not contacts:
        return []
    owner_of, companies = tagged_company_of(hs, [c["id"] for c in contacts], COMPANY_PROPS)
    notes = load_company_notes()
    rows = []
    for c in contacts:
        company = companies.get(owner_of.get(str(c["id"])))
        if not company or statuses.of("companies", company) in COMPANY_STOPPED:
            continue
        comp = company["properties"]
        p = c.get("properties", {})
        domain = (comp.get("domain") or "").lower()
        note = notes.get(domain, {})
        rank = str(p.get(ORDER) or "")
        rows.append({
            "contact_id": str(c["id"]),
            "job_title": p.get("jobtitle") or "",
            "seniority": hierarchy_level(p.get("jobtitle"), hierarchy)[1] if hierarchy else "",
            "rank": int(float(rank)) if rank.replace(".", "", 1).isdigit() else 99,
            "company": {
                "name": comp.get("name") or note.get("name") or "",
                "domain": domain,
                "location": market_of(comp) or note.get("market") or "",
                "channel": channel_of(comp, notes),
                "based_out_of": note.get("based_out_of") or "",
                "distributes": note.get("distributes") or "",
                "channels_supplied": note.get("channels_supplied") or "",
                "sf_brands_carried": note.get("sf_brands_carried") or "",
                "what_they_do_well": note.get("what_they_do_well") or [],
                "fit_rationale": note.get("fit_rationale") or "",
            },
        })
    # Most senior first, so the people emailed first get their lines first.
    rows.sort(key=lambda r: (r["rank"], r["company"]["name"].lower(), r["contact_id"]))
    return rows


def save(rows, target, path=None):
    path = path or PENDING_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"generated_at": now_iso(), "target": target, "contacts": rows}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def run(target, hs, path=None, log=print, exclude=(), new_ids=()):
    check_target(hs, target)
    rows = collect(hs, exclude=exclude, new_ids=new_ids)
    save(rows, target, path)
    log(f"{len(rows)} contacts need email lines; saved to mail/pending.json")
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description="Save the contacts that need email lines")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--skip-if-not-configured", action="store_true")
    p.add_argument("--new-contacts", default="",
                   help="the file of contacts button 3 has just added (runs/new_contacts.json)")
    args = p.parse_args(argv)
    new_ids = []
    if args.new_contacts and os.path.exists(args.new_contacts):
        with open(args.new_contacts, encoding="utf-8") as fh:
            new_ids = json.load(fh).get("contact_ids") or []
    if args.skip_if_not_configured and not os.environ.get("HUBSPOT_TOKEN"):
        print("The HubSpot key is not added yet; skipping.")
        return 0
    try:
        run(args.target, HubSpot(), new_ids=new_ids)
    except (PipelineError, HubSpotError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
