"""Create the Diablo outreach fields in a HubSpot account.

Safe to run more than once: it only creates what is missing and adds missing
dropdown options. It never deletes or renames anything.

Usage:
    python -m outreach.setup_hubspot --dry-run          # show the plan, no key needed
    python -m outreach.setup_hubspot                    # run against the key's account
    python -m outreach.setup_hubspot --allow-production # only when you mean the live account
"""

import argparse
import json
import sys

from .common import PRODUCTION_PORTAL_ID  # the live account; refused without --allow-production
from .hubspot_client import HubSpot, HubSpotError
from .schema import GROUP_LABEL, GROUP_NAME, PROPERTIES


def ensure_group(hs, object_type, dry_run, log):
    if dry_run:
        log(f"[plan] {object_type}: property group '{GROUP_LABEL}'")
        return
    groups = hs.request("GET", f"/crm/v3/properties/{object_type}/groups")["results"]
    if any(g["name"] == GROUP_NAME for g in groups):
        log(f"[ok]   {object_type}: group '{GROUP_LABEL}' already exists")
        return
    hs.request(
        "POST",
        f"/crm/v3/properties/{object_type}/groups",
        json={"name": GROUP_NAME, "label": GROUP_LABEL, "displayOrder": -1},
    )
    log(f"[new]  {object_type}: created group '{GROUP_LABEL}'")


def ensure_property(hs, object_type, spec, existing, dry_run, log):
    name = spec["name"]
    payload = dict(spec, groupName=GROUP_NAME, formField=False)

    if dry_run:
        log(f"[plan] {object_type}: {name} ({spec['type']}/{spec['fieldType']})")
        return "planned"

    current = existing.get(name)
    if current is None:
        hs.request("POST", f"/crm/v3/properties/{object_type}", json=payload)
        log(f"[new]  {object_type}: created {name}")
        return "created"

    if current.get("type") != spec["type"]:
        log(
            f"[warn] {object_type}: {name} exists as {current.get('type')}, "
            f"expected {spec['type']}. Left unchanged; check it by hand."
        )
        return "conflict"

    # Add any dropdown options that are missing, keep the ones already there.
    if spec.get("options") and spec["type"] == "enumeration":
        have = {o["value"] for o in current.get("options", [])}
        missing = [o for o in spec["options"] if o["value"] not in have]
        if missing:
            merged = current.get("options", []) + missing
            hs.request(
                "PATCH",
                f"/crm/v3/properties/{object_type}/{name}",
                json={"options": merged},
            )
            log(f"[upd]  {object_type}: added {len(missing)} option(s) to {name}")
            return "updated"

    log(f"[ok]   {object_type}: {name} already exists")
    return "unchanged"


def run(hs, dry_run=False, allow_production=False, log=print):
    if not dry_run:
        portal = hs.portal_id()
        log(f"Connected to HubSpot account {portal}")
        if portal == PRODUCTION_PORTAL_ID and not allow_production:
            raise HubSpotError(
                "This key belongs to the LIVE Diablo Sugar Free account. "
                "Stopping. Use a test account key, or pass --allow-production "
                "when you really mean to set up the live account."
            )

    summary = {}
    for object_type, specs in PROPERTIES.items():
        ensure_group(hs, object_type, dry_run, log)
        existing = {}
        if not dry_run:
            results = hs.request("GET", f"/crm/v3/properties/{object_type}")["results"]
            existing = {p["name"]: p for p in results}
        for spec in specs:
            outcome = ensure_property(hs, object_type, spec, existing, dry_run, log)
            summary[outcome] = summary.get(outcome, 0) + 1
    log("Summary: " + json.dumps(summary))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="show what would be created, change nothing")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="allow running against the live Diablo HubSpot account",
    )
    args = parser.parse_args(argv)

    try:
        hs = None if args.dry_run else HubSpot()
        summary = run(hs, dry_run=args.dry_run, allow_production=args.allow_production)
    except HubSpotError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 1 if summary.get("conflict") else 0


if __name__ == "__main__":
    sys.exit(main())
