"""Button 1: set up a HubSpot account for the outreach pipeline (agreed 13 Oct 2026).

What it adds, and nothing else:
  - contacts: the fields "Outreach personal line" and "Outreach order" (group "Diablo outreach");
  - Lead Status: the choices the pipeline needs that the account does not have yet. In the live
    account that is "Approved for outreach" (companies), "Copy ready" and "Approved to send"
    (contacts). Existing choices are never changed, renamed, reordered or removed;
  - in a test account only: Lead Source and Industry Type, created to match the live account.
    The live account already has them, so there they are only checked.

Safe to run more than once: it only adds what is missing. It never deletes or renames anything
and never touches a company or contact record. A dry run reads the account and lists exactly
what would be added, changing nothing.

Usage:
    python -m outreach.setup_hubspot --dry-run          # list what would be added (reads the account)
    python -m outreach.setup_hubspot                    # add it (test account)
    python -m outreach.setup_hubspot --allow-production # only when you mean the live account
"""

import argparse
import json
import sys

from .common import PRODUCTION_PORTAL_ID  # the live account; refused without --allow-production
from .hubspot_client import HubSpot, HubSpotError
from .schema import GROUP_LABEL, GROUP_NAME, LEAD_STATUS, MIRRORED_PROPERTIES, NEW_PROPERTIES, PROPERTIES
from .stages import NEW_OPTION_VALUES, STAGES


class Plan:
    def __init__(self, dry_run, log):
        self.dry_run, self.log = dry_run, log
        self.summary = {}

    def note(self, outcome, text):
        self.summary[outcome] = self.summary.get(outcome, 0) + 1
        tag = {"created": "[new] ", "updated": "[upd] ", "unchanged": "[ok]  ", "conflict": "[warn]"}[outcome]
        if self.dry_run and outcome in ("created", "updated"):
            tag = "[would add]"
        self.log(f"{tag} {text}")


def ensure_group(hs, object_type, plan):
    groups = hs.request("GET", f"/crm/v3/properties/{object_type}/groups")["results"]
    if any(g["name"] == GROUP_NAME for g in groups):
        plan.note("unchanged", f"{object_type}: group '{GROUP_LABEL}' already exists")
        return
    if not plan.dry_run:
        hs.request("POST", f"/crm/v3/properties/{object_type}/groups",
                   json={"name": GROUP_NAME, "label": GROUP_LABEL, "displayOrder": -1})
    plan.note("created", f"{object_type}: group '{GROUP_LABEL}'")


def add_options(hs, object_type, name, current, missing, plan):
    """Append missing dropdown choices; the existing ones are sent back exactly as they were."""
    if not missing:
        return
    if not plan.dry_run:
        start = max([int(o.get("displayOrder") or 0) for o in current] + [len(current) - 1]) + 1
        new = [dict(o, displayOrder=start + i) for i, o in enumerate(missing)]
        hs.request("PATCH", f"/crm/v3/properties/{object_type}/{name}", json={"options": current + new})
    for o in missing:
        plan.note("updated", f"{object_type}: {name}: add the choice \"{o['label']}\"")


def ensure_property(hs, object_type, spec, existing, plan, add_missing_options=True, may_create=True):
    name = spec["name"]
    current = existing.get(name)
    if current is None and not may_create:
        plan.note("conflict", f"{object_type}: {spec['label']} ({name}) is missing in the live account. It belongs "
                              "to the team, so it is not created here; check it by hand.")
        return
    if current is None:
        if not plan.dry_run:
            hs.request("POST", f"/crm/v3/properties/{object_type}", json=dict(spec, formField=False))
        plan.note("created", f"{object_type}: field {spec['label']} ({name})")
        return
    if current.get("type") != spec["type"]:
        plan.note("conflict", f"{object_type}: {name} exists as {current.get('type')}, expected "
                              f"{spec['type']}. Left unchanged; check it by hand.")
        return
    if spec.get("options") and add_missing_options:
        have = {str(o["value"]) for o in current.get("options", [])}
        missing = [o for o in spec["options"] if str(o["value"]) not in have]
        if missing:
            add_options(hs, object_type, name, current.get("options", []), missing, plan)
            return
    plan.note("unchanged", f"{object_type}: field {name} already exists")


# The only Lead Status choices the live account may receive (agreed 13 Oct 2026).
LIVE_NEW_CHOICES = {"companies": {"Approved for outreach"}, "contacts": {"Copy ready", "Approved to send"}}


def ensure_lead_status(hs, object_type, existing, plan, live=False):
    """Add the Lead Status choices the pipeline needs, matched by their label. In the live account
    only the three agreed choices can be added; anything else missing is reported instead."""
    current = existing.get(LEAD_STATUS)
    if current is None:
        plan.note("conflict", f"{object_type}: HubSpot's Lead Status field is missing in this account; "
                              "the pipeline cannot run here.")
        return
    options = current.get("options", [])
    labels = {str(o["label"]).strip().lower() for o in options}
    values = {str(o["value"]) for o in options}
    missing = []
    for label in STAGES[object_type].values():
        if label.lower() in labels:
            continue
        if live and label not in LIVE_NEW_CHOICES[object_type]:
            plan.note("conflict", f'{object_type}: the live Lead Status has no "{label}" choice. Only the three '
                                  "agreed choices are ever added to live, so this one was not; check it by hand.")
            continue
        value = NEW_OPTION_VALUES[object_type][label]
        if value in values:
            plan.note("conflict", f"{object_type}: Lead Status already uses the value {value} for another "
                                  f'choice, so "{label}" was not added. Add it by hand.')
            continue
        missing.append({"label": label, "value": value, "hidden": False})
    if missing and (current.get("modificationMetadata") or {}).get("readOnlyOptions"):
        for o in missing:
            plan.note("conflict", f'{object_type}: HubSpot does not let a key add choices to Lead Status in this '
                                  f'account. Add "{o["label"]}" by hand: Settings > Properties > Lead Status.')
    elif missing:
        add_options(hs, object_type, LEAD_STATUS, options, missing, plan)
    else:
        plan.note("unchanged", f"{object_type}: Lead Status already has every choice the pipeline uses")


def run(hs, dry_run=False, allow_production=False, log=print):
    plan = Plan(dry_run, log)
    if hs is None:  # no key: show the plan from the code alone
        for object_type in ("companies", "contacts"):
            for spec in PROPERTIES[object_type]:
                log(f"[plan] {object_type}: field {spec['label']} ({spec['name']})")
            for label in STAGES[object_type].values():
                log(f"[plan] {object_type}: Lead Status choice \"{label}\" (added only if missing)")
        return {"planned": 1}
    portal = hs.portal_id()
    live = portal == PRODUCTION_PORTAL_ID
    log(f"Connected to HubSpot account {portal}" + (" (the LIVE account)" if live else ""))
    if live and not allow_production and not dry_run:
        raise HubSpotError(
            "This key belongs to the LIVE Diablo Sugar Free account. Stopping. Use a test account "
            "key, or choose the live account on purpose.")
    for object_type in ("companies", "contacts"):
        existing = {p["name"]: p for p in hs.request("GET", f"/crm/v3/properties/{object_type}")["results"]}
        for spec in MIRRORED_PROPERTIES[object_type]:
            # In live these fields belong to the team: only checked, never given new choices.
            ensure_property(hs, object_type, spec, existing, plan, add_missing_options=not live, may_create=not live)
        if NEW_PROPERTIES[object_type]:
            ensure_group(hs, object_type, plan)
            for spec in NEW_PROPERTIES[object_type]:
                ensure_property(hs, object_type, spec, existing, plan)
        ensure_lead_status(hs, object_type, existing, plan, live=live)
    log("Summary: " + json.dumps(plan.summary))
    return plan.summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="list what would be added, change nothing")
    parser.add_argument("--allow-production", action="store_true",
                        help="allow running against the live Diablo HubSpot account")
    args = parser.parse_args(argv)
    try:
        try:
            hs = HubSpot()
        except HubSpotError:
            if not args.dry_run:
                raise
            hs = None
        summary = run(hs, dry_run=args.dry_run, allow_production=args.allow_production)
    except HubSpotError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 1 if summary.get("conflict") else 0


if __name__ == "__main__":
    sys.exit(main())
