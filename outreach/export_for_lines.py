"""Save the contacts that need email lines to mail/pending.json, for the outreach-mail-writing skill.

A contact needs lines when its Outreach contact status is "Contact found". For each one the
file holds the HubSpot contact ID, job title and seniority, plus what the research found about
its company (from data/company_notes.json). No names, emails or phone numbers are saved: the
email template fills in the first name itself, so the skill never needs them.

Runs after "3 - Find contacts: Apollo to HubSpot", after every lines import, and from the button
"4a - HubSpot contacts to email writer (automatic)".

Usage:
    python -m outreach.export_for_lines --target test
"""

import argparse
import json
import os
import sys

from .common import ROOT, PipelineError, category_label, check_target, load_company_notes, now_iso
from .hubspot_client import HubSpot, HubSpotError
from .next_in_line import STOPPED

PENDING_FILE = ROOT / "mail" / "pending.json"
COMPANY_PROPS = ["name", "domain", "diablo_market", "diablo_channel_category", "diablo_outreach_status",
                 "diablo_suppress_reason"]


def collect(hs, max_results=5000, exclude=()):
    """HubSpot's search can lag a few seconds behind an update, so every status is read again
    directly before a contact is listed; `exclude` drops contacts just updated by the caller."""
    props = ["jobtitle", "diablo_hierarchy_rank", "diablo_hierarchy_level", "diablo_contact_status"]
    found = hs.search(
        "contacts", [{"propertyName": "diablo_contact_status", "operator": "EQ", "value": "contact_found"}],
        props, max_results=max_results)
    exclude = {str(i) for i in exclude}
    ids = [c["id"] for c in found if str(c["id"]) not in exclude]
    contacts = [c for c in hs.batch_read("contacts", ids, props)
                if (c.get("properties", {}).get("diablo_contact_status") or "") == "contact_found"] if ids else []
    if not contacts:
        return []
    links = hs.associated_ids("contacts", "companies", [c["id"] for c in contacts])
    company_ids = sorted({ids[0] for ids in links.values() if ids})
    companies = {c["id"]: c["properties"] for c in hs.batch_read("companies", company_ids, COMPANY_PROPS)}
    labels = hs.option_labels("companies", "diablo_channel_category")
    notes = load_company_notes()
    rows = []
    for c in contacts:
        company_id = (links.get(c["id"]) or [None])[0]
        comp = companies.get(company_id)
        if not comp or comp.get("diablo_suppress_reason") or (comp.get("diablo_outreach_status") or "") in STOPPED:
            continue
        p = c.get("properties", {})
        domain = (comp.get("domain") or "").lower()
        note = notes.get(domain, {})
        rank = str(p.get("diablo_hierarchy_rank") or "")
        rows.append({
            "contact_id": str(c["id"]),
            "job_title": p.get("jobtitle") or "",
            "seniority": p.get("diablo_hierarchy_level") or "",
            "rank": int(rank) if rank.isdigit() else 99,
            "company": {
                "name": comp.get("name") or note.get("name") or "",
                "domain": domain,
                "location": comp.get("diablo_market") or note.get("market") or "",
                "channel": category_label(comp.get("diablo_channel_category"), labels) or note.get("category") or "",
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


def run(target, hs, path=None, log=print, exclude=()):
    check_target(hs, target)
    rows = collect(hs, exclude=exclude)
    save(rows, target, path)
    log(f"{len(rows)} contacts need email lines; saved to mail/pending.json")
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description="Save the contacts that need email lines")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--skip-if-not-configured", action="store_true")
    args = p.parse_args(argv)
    if args.skip_if_not_configured and not os.environ.get("HUBSPOT_TOKEN"):
        print("The HubSpot key is not added yet; skipping.")
        return 0
    try:
        run(args.target, HubSpot())
    except (PipelineError, HubSpotError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
