"""Fill in "Job Number" (21 Oct 2026) on AUTO-OUTREACH companies that do not have it yet.

New companies get it when they are imported (import_research.py). This fills in companies imported
before the field existed, from the research files in research/<date>/ (matched by website, or by name
when there is no website). Runs with button 2's automatic runs; changes nothing where the field is
missing in the account (button 1 adds it) or where no research file matches.

Usage:
    python -m outreach.job_numbers --target live
"""

import argparse
import json
import os
import sys

from .common import ROOT, PipelineError, check_target, clean_domain
from .hubspot_client import HubSpot, HubSpotError
from .schema import JOB_NUMBER


def research_jobs(folder=None):
    """({website: job id}, {company name: job id}) from every research file, oldest first."""
    by_domain, by_name = {}, {}
    for path in sorted((folder or ROOT / "research").glob("*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        job = data.get("job_id") if isinstance(data, dict) else None
        if not job:
            continue
        for c in data.get("companies") or []:
            domain = clean_domain(c.get("domain")) if c.get("domain") != "no domain" else None
            if domain:
                by_domain.setdefault(domain, job)
            if c.get("name"):
                by_name.setdefault(c["name"].strip().lower(), job)
    return by_domain, by_name


def run(target, hs, log=print, folder=None):
    check_target(hs, target)
    if not hs.has_property("companies", JOB_NUMBER):
        log('The company field "Job Number" is missing in this account; run button 1 to add it')
        return {"filled": 0}
    by_domain, by_name = research_jobs(folder)
    if not by_domain and not by_name:
        return {"filled": 0}
    rows = hs.tagged_search("companies", [{"propertyName": JOB_NUMBER, "operator": "NOT_HAS_PROPERTY"}],
                            ["name", "domain", JOB_NUMBER], max_results=10000)
    updates = []
    for r in rows:
        p = r.get("properties") or {}
        job = by_domain.get(clean_domain(p.get("domain")) or "") or by_name.get((p.get("name") or "").strip().lower())
        if job:
            updates.append((r["id"], {JOB_NUMBER: job}))
    if updates:
        hs.update_tagged("companies", updates)
    log(f"Job Number filled in on {len(updates)} companies ({len(rows) - len(updates)} without a matching research file)")
    return {"filled": len(updates)}


def main(argv=None):
    p = argparse.ArgumentParser(description="Fill in Job Number on companies")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--skip-if-not-configured", action="store_true")
    args = p.parse_args(argv)
    if args.skip_if_not_configured and not os.environ.get("HUBSPOT_TOKEN"):
        print("Job Number skipped: the HubSpot key is not added yet.")
        return 0
    try:
        run(args.target, HubSpot())
    except (PipelineError, HubSpotError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
