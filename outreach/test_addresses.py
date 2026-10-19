"""Strain test helper (agreed 19 Oct 2026): give the test companies' contacts the test addresses.

TEST ACCOUNT ONLY: it refuses the live HubSpot account. Run it after button 3 has found the
contacts, before mail writing. It takes approved (GATE1) companies whose AUTO-OUTREACH contacts
are still New or "New, Personal line filled":

  - each case typed into the button gets one company: 3 contacts each, except the LAST case, which
    is the one-contact case (1 contact);
  - a case is a letter and a number, e.g. e1. The letter is the round of the test (c in the second
    strain test, e from 19 Oct 2026, then f, g ...): a new letter for each restart keeps the
    addresses apart from Instantly's emails of an earlier round;
  - the first contacts by Outreach order get plus addresses on the case's mailbox, e.g.
    name+e1p1@x.com, name+e1p2@x.com, name+e1p3@x.com;
  - any further contacts at those companies become Unqualified, so only the test addresses are
    ever emailed.

The mailboxes are typed into the button when it is run (never stored in the repository):
    e1=a@x.com, e2=b@x.com, e3=c@x.com, e4=d@x.com, e5=e@x.com
Companies can be named in case order (optional); otherwise they are picked by name, those with the
most contacts first. Approved companies that are not used are listed, so they can be set to
Unqualified before anyone is approved at gate 2.

Usage:
    python -m outreach.test_addresses --mailboxes "e1=...,e2=..." [--companies "A; B; ..."] [--dry-run]
"""

import argparse
import os
import re
import sys

from .common import PipelineError, check_target, step_summary
from .hubspot_client import HubSpot, HubSpotError
from .next_in_line import COMPANY_PROPS, contacts_by_company, rank_of
from .schema import LEAD_STATUS
from .stages import LeadStatus

CASE = re.compile(r"^([a-z])([1-9])$")
EMAIL = re.compile(r"^[^@\s+]+@[^@\s]+\.[A-Za-z]{2,}$")


def contacts_needed(cases):
    """{case: contacts needed}: 3 each, the last case (the one-contact case) 1."""
    cases = list(cases)
    return {case: (1 if len(cases) > 1 and i == len(cases) - 1 else 3) for i, case in enumerate(cases)}


def parse_mailboxes(text):
    """{"e1": "a@x.com", ...} in case order, from "e1=a@x.com, e2=..." (spaces, commas, semicolons or
    new lines). Every case uses the same letter (the round); at least one case is needed."""
    out = {}
    for part in re.split(r"[,;\n]+", text or ""):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise PipelineError(f'"{part}" is not in the form e1=name@domain')
        case, email = (x.strip() for x in part.split("=", 1))
        case = case.lower()
        if not CASE.match(case):
            raise PipelineError(f'"{case}" is not a case: a letter and a number, e.g. e1')
        if not EMAIL.match(email):
            raise PipelineError(f'"{email}" for {case} is not a plain email address (no "+" part)')
        out[case] = email.lower()
    if not out:
        raise PipelineError("No mailbox given: type at least one case, e.g. e1=name@domain")
    letters = {case[0] for case in out}
    if len(letters) > 1:
        raise PipelineError(f"Use one letter for every case (the round of the test), not {', '.join(sorted(letters))}")
    return {case: out[case] for case in sorted(out, key=lambda c: int(c[1:]))}


def plus(email, case, n):
    name, domain = email.split("@", 1)
    return f"{name}+{case}p{n}@{domain}"


def mask(email):
    name, _, domain = (email or "").partition("@")
    return f"{name[:1]}***{name[name.find('+'):] if '+' in name else ''}@{domain}" if domain else "(none)"


def choose(companies, people, names=None, cases=None):
    """{case: company} for the cases being run."""
    cases = contacts_needed(cases or [])
    usable = [c for c in companies if people.get(c["id"])]
    if names:
        wanted = [n.strip().lower() for n in names if n.strip()]
        if len(wanted) != len(cases):
            raise PipelineError(f"Name exactly {len(cases)} companies, in case order {', '.join(cases)}")
        by_name = {(c["properties"].get("name") or "").strip().lower(): c for c in usable}
        chosen = {}
        for case, name in zip(cases, wanted):
            company = by_name.get(name) or next((c for n, c in by_name.items() if name in n), None)
            if company is None:
                raise PipelineError(f'No approved company with new contacts is called "{name}"')
            chosen[case] = company
    else:
        usable.sort(key=lambda c: (-len(people[c["id"]]), (c["properties"].get("name") or "").lower()))
        chosen, used = {}, set()
        for case, need in sorted(cases.items(), key=lambda kv: -kv[1]):  # the 3-contact cases first
            fits = [c for c in usable if c["id"] not in used and len(people[c["id"]]) >= need]
            if need == 1:  # the one-contact case takes the smallest company left (best: exactly one)
                fits.sort(key=lambda c: len(people[c["id"]]))
            company = fits[0] if fits else None
            if company is None:
                raise PipelineError(f"Not enough approved companies with at least {need} new contacts for {case}. "
                                    "Approve more companies at gate 1 and press button 3 first.")
            chosen[case] = company
            used.add(company["id"])
    for case, company in chosen.items():
        if len(people[company["id"]]) < cases[case]:
            raise PipelineError(f'{company["properties"].get("name")} has fewer than {cases[case]} new contacts '
                                f"for {case}")
    if len({c["id"] for c in chosen.values()}) != len(chosen):
        raise PipelineError("The same company was named for two cases")
    return chosen


def run(target, hs, mailboxes, names=None, dry_run=False, log=print):
    if target != "test":
        raise PipelineError("The test addresses are for the test account only. Nothing was done.")
    needed = contacts_needed(mailboxes)
    check_target(hs, "test")
    statuses = LeadStatus(hs)
    companies = hs.tagged_search("companies", [statuses.filter("companies", "approved")], COMPANY_PROPS,
                                 max_results=500)
    everyone = contacts_by_company(hs, [c["id"] for c in companies]) if companies else {}
    people = {cid: sorted([p for p in ps if statuses.of("contacts", p) in ("found", "copy_ready")], key=rank_of)
              for cid, ps in everyone.items()}
    chosen = choose(companies, people, names, cases=list(mailboxes))
    updates, rows = [], []
    for case, company in sorted(chosen.items()):
        name = company["properties"].get("name")
        for n, person in enumerate(people[company["id"]], start=1):
            if n <= needed[case]:
                address = plus(mailboxes[case], case, n)
                updates.append((person["id"], {"email": address}))
                rows.append(f"| {case} | {name} | {n} | {person['properties'].get('jobtitle') or ''} | {mask(address)} |")
            else:
                updates.append((person["id"], statuses.props("contacts", "closed")))
                rows.append(f"| {case} | {name} | {n} | {person['properties'].get('jobtitle') or ''} | "
                            "not used: set to Unqualified |")
    unused = [c["properties"].get("name") for c in companies
              if c["id"] not in {x["id"] for x in chosen.values()} and people.get(c["id"])]
    if not dry_run:
        for contact_id, props in updates:  # one by one, so one refused address does not stop the rest
            try:
                hs.update_tagged("contacts", [(contact_id, props)])
            except HubSpotError as err:
                log(f"HubSpot refused contact {contact_id}: {str(err)[:200]}")
                rows.append(f"| - | - | - | contact {contact_id} | REFUSED by HubSpot, change it by hand |")
    summary = ("## Test addresses" + (" (dry run: nothing changed)" if dry_run else "") + "\n\n"
               "| Case | Company | Order | Job title | Now |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    if unused:
        summary += ("\n**Approved companies not used in the test** (their contacts still have real addresses; "
                    "set them to Unqualified before gate 2): " + "; ".join(unused) + "\n")
    step_summary(summary)
    log(summary)
    return {"cases": {k: v["properties"].get("name") for k, v in chosen.items()}, "updated": len(updates),
            "unused": unused}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--mailboxes", default=os.environ.get("TEST_MAILBOXES", ""))
    p.add_argument("--companies", default=os.environ.get("TEST_COMPANIES", ""))
    p.add_argument("--target", default="test")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    try:
        names = [x for x in re.split(r"[;\n]+", args.companies) if x.strip()] or None
        run(args.target, HubSpot(), parse_mailboxes(args.mailboxes), names, dry_run=args.dry_run)
    except (PipelineError, HubSpotError) as err:
        print(f"::error::{err}")
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
