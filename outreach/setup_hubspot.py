"""Button 1: set up a HubSpot account for the outreach pipeline (agreed 13 Oct 2026).

What it adds, and nothing else:
  - contacts: the fields "Outreach personal line", "Outreach company note" (added 15 Oct 2026)
    and "Outreach order" (group "Diablo outreach");
  - Lead Status: the choices the pipeline needs that the account does not have yet. In the live
    account that is "GATE1: Approved for outreach" (companies), "New, Personal line filled" and "GATE2: Approved to send"
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

from .common import PRODUCTION_PORTAL_ID, step_summary  # the live account; refused without --allow-production
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
LIVE_NEW_CHOICES = {"companies": {"GATE1: Approved for outreach",
                                  "Contacted, but no response, unqualified",  # 21 Oct 2026
                                  "Missing info on Apollo"},  # 23 Oct 2026
                    "contacts": {"New, Personal line filled", "GATE2: Approved to send",
                                 "Forward sent", "Reminder sent",  # these two added 14 Oct 2026
                                 # the rest of a company once someone there has answered (19 Oct 2026)
                                 "Colleague replied: positive", "Colleague replied: negative",
                                 "Colleague replied",
                                 "Colleague opted out",  # 19 Oct 2026
                                 "Unqualified company",  # 21 Oct 2026
                                 "Contacted, but no response, unqualified"}}  # 21 Oct 2026


def ensure_lead_status(hs, object_type, existing, plan, live=False):
    """Add the Lead Status choices the pipeline needs, matched by their label. In the live account
    only the agreed choices can be added; anything else missing is reported instead."""
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
            plan.note("conflict", f'{object_type}: the live Lead Status has no "{label}" choice. Only the '
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


# The private app's scopes (the same 9 for the test and the live account).
SCOPES = [
    "crm.objects.companies.read", "crm.objects.companies.write",
    "crm.objects.contacts.read", "crm.objects.contacts.write",
    "crm.schemas.companies.read", "crm.schemas.companies.write",
    "crm.schemas.contacts.read", "crm.schemas.contacts.write",
    "crm.objects.owners.read",
]


def key_guide(secret="HUBSPOT_TOKEN_TEST"):
    """How to get the right HubSpot key, shown on every button 1 run (agreed 14 Oct 2026)."""
    scopes = "\n".join(f"   - `{s}`" for s in SCOPES)
    return f"""### How to get the HubSpot key (the test account's key, never the developer account's)

1. Log in to HubSpot. In your main (developer) account go to **Development > Testing > Test accounts**.
   Create a new test account only if you need one.
2. Click the test account to open it. Check the account name at the top left is the test account.
3. Inside the test account go to **Development > Legacy apps > Create legacy app** and choose **Private**.
   Give it a name, for example "Outreach pipeline".
4. On the **Scopes** tab tick exactly these 9:
{scopes}
5. Click **Create app**, open the **Auth** tab, click **Show token** and **Copy**.
6. In GitHub: **Settings > Secrets and variables > Actions**, open **{secret}**, click **Update**,
   paste the key and save.
7. Run button 1 again with **Dry run** ticked; when it is green, run it once more unticked.

For the live account (only when testing is finished): steps 3 to 7 in the live Diablo account
itself, saved as `HUBSPOT_TOKEN_LIVE`."""


def explain(err, secret="HUBSPOT_TOKEN_TEST"):
    """A plain reason and what to do, for a failed button 1 run."""
    text = str(err)
    if "HUBSPOT_TOKEN is not set" in text:
        return (f"The GitHub secret `{secret}` is empty, so there is no key to use.",
                "Follow the steps below to get the key and save it in GitHub.")
    if " 401" in text or "Could not work out which HubSpot account" in text:
        return ("HubSpot did not accept the key. It is wrong, it was copied only in part, or it belongs "
                "to an account that has been deleted.",
                f"Get a fresh key with the steps below and replace `{secret}` in GitHub.")
    if " 403" in text:
        return ("The key works, but the app is missing one of the 9 scopes.",
                "In the test account open the legacy app, tick every scope in step 4 below, save, "
                f"then copy the key again into `{secret}` (it may change).")
    if "LIVE Diablo Sugar Free account" in text:
        return ("The key belongs to the LIVE Diablo account, but you chose the test account.",
                f"Put the test account's key in `{secret}` (steps below). Choose \"live\" only when "
                "you mean the live account.")
    return (f"HubSpot replied: {text[:300]}", "If the steps below do not fix it, send this message to Claude.")


def write_result(status, reason=None, fix=None, lines=(), secret="HUBSPOT_TOKEN_TEST"):
    """The box at the top of the run's page: the result, why, what to do, and the key steps."""
    parts = [f"## Button 1 result: {status}"]
    if reason:
        parts.append(f"**Why:** {reason}")
    if fix:
        parts.append(f"**What to do:** {fix}")
    if lines:
        parts.append("**What it found:**\n\n" + "\n".join(f"- {line}" for line in lines))
    parts.append(key_guide(secret))
    step_summary("\n\n".join(parts))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="list what would be added, change nothing")
    parser.add_argument("--allow-production", action="store_true",
                        help="allow running against the live Diablo HubSpot account")
    args = parser.parse_args(argv)
    secret = "HUBSPOT_TOKEN_LIVE" if args.allow_production else "HUBSPOT_TOKEN_TEST"
    lines = []

    def log(text):
        print(text)
        lines.append(text)

    try:
        no_key = False
        try:
            hs = HubSpot()
        except HubSpotError:
            if not args.dry_run:
                raise
            hs, no_key = None, True
        summary = run(hs, dry_run=args.dry_run, allow_production=args.allow_production, log=log)
    except HubSpotError as err:
        reason, fix = explain(err, secret)
        print(f"::error::{reason} {fix}")
        print(f"ERROR: {err}", file=sys.stderr)
        write_result("FAILED", reason, fix, lines, secret)
        return 1
    warnings = [line for line in lines if line.startswith("[warn]")]
    if warnings:
        reason = "HubSpot would not take some changes; each one is listed below with what to do."
        print(f"::error::{reason}")
        write_result("FAILED", reason, "Do what each [warn] line says, then run button 1 again.", lines, secret)
        return 1
    if no_key:
        reason = (f"There is no key in `{secret}`, so this dry run only listed the plan from the code. "
                  "It did not check your HubSpot account.")
        print(f"::warning::{reason}")
        write_result("NOT CHECKED (no key)", reason, "Save the key with the steps below, then run the dry "
                     "run again.", lines, secret)
        return 0
    status = "worked (dry run: nothing was changed)" if args.dry_run else "worked"
    fix = ("Run button 1 again with Dry run unticked." if args.dry_run and summary.get("created", 0)
           + summary.get("updated", 0) else "Nothing more to do for this account.")
    write_result(status, None, fix, lines, secret)
    return 0


if __name__ == "__main__":
    sys.exit(main())
