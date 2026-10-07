"""Nightly: save every company HubSpot already holds to data/known_companies.csv.

The outreachResearch skill reads this file to build the prompt's exclusion list, so
Claude never needs HubSpot access. Same rules as version 1: companies already in the
pipeline, suppressed companies, customers, and any company HubSpot holds for the same
country as the job (the skill picks those by the country column).

Usage:
    python -m outreach.known_companies --target test
"""

import argparse
import csv
import os
import sys

from .common import KNOWN_FILE, PipelineError, check_target
from .hubspot_client import HubSpot, HubSpotError

COLUMNS = ["name", "domain", "country", "why"]

# The first matching reason is kept.
REASONS = (
    ("pipeline", [{"propertyName": "diablo_outreach_status", "operator": "HAS_PROPERTY"}]),
    ("suppressed", [{"propertyName": "diablo_suppress_reason", "operator": "HAS_PROPERTY"}]),
    ("customer", [{"propertyName": "lifecyclestage", "operator": "EQ", "value": "customer"}]),
    ("other", [{"propertyName": "country", "operator": "HAS_PROPERTY"}]),
)


def collect(hs, max_results=10000):
    """Rows of name, domain, country and why, one per HubSpot company, sorted by name."""
    found = {}
    for why, filters in REASONS:
        for rec in hs.search("companies", filters, ["name", "domain", "country"], max_results=max_results):
            if rec["id"] in found:
                continue
            p = rec.get("properties", {})
            if not (p.get("name") or p.get("domain")):
                continue
            found[rec["id"]] = {
                "name": (p.get("name") or "").strip(),
                "domain": (p.get("domain") or "").strip().lower(),
                "country": (p.get("country") or "").strip(),
                "why": why,
            }
    return sorted(found.values(), key=lambda r: (r["name"].lower(), r["domain"]))


def save(rows, path=None):
    path = path or KNOWN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(target, hs, path=None, log=print):
    check_target(hs, target)
    rows = collect(hs)
    save(rows, path)
    log(f"Saved {len(rows)} HubSpot companies to data/known_companies.csv")
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description="Save the list of companies already in HubSpot")
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
