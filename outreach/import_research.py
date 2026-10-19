"""Import new research files into HubSpot and record the result in the queue.

Runs by itself when the outreachResearch skill saves files to research/<date>/. Each new
JSON file is checked again with the skill's strict check: a file that fails is rejected
whole (nothing reaches HubSpot). A file that passes is added to HubSpot with Lead Source
AUTO-OUTREACH and Lead Status "New", waiting for a person to set "GATE1: Approved for outreach"
(gate 1); the email details go into data/company_notes.json. Companies already in HubSpot
are never added again. Each Channel's line
in research/queue.csv is marked Done, Done fewer than wanted or On hold. A failed Channel
goes back to Waiting once, so the next run tries it again by itself; a second failure
marks it Failed.

Usage:
    python -m outreach.import_research --target test            # every file not yet imported
    python -m outreach.import_research --target test --file research/2026-10-09/J0001_....json
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

from . import known_companies
from . import research_queue as rq
from .common import (
    ROOT, PipelineError, check_target, clean_category, clean_domain, industry_type, known_file, load_settings,
    now_iso, save_company_notes, split_location,
)
from .hubspot_client import HubSpot, HubSpotError
from .import_checks import INBOX_NOTE, Checker
from .schema import INDUSTRY_TYPE, TIER
from .stages import LeadStatus

SKILL = ROOT / "skills" / "outreachResearch"


def _checker():
    spec = importlib.util.spec_from_file_location("check_output", SKILL / "scripts" / "check_output.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_output = _checker()


def relative(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def pending_files(rows):
    """Research JSON files that no queue line points to yet, oldest first."""
    imported = {r["output_file"] for r in rows if r["output_file"]}
    files = sorted((ROOT / "research").glob("*/*.json"))
    return [f for f in files if relative(f) not in imported]


def job_of(path):
    match = re.match(r"(J\d{4,})_", Path(path).name)
    return match.group(1) if match else None


def already_in_hubspot(hs, records, target="live"):
    """Indexes of the records that already exist in HubSpot. Two checks:
    1. the full "already in HubSpot" list of that account (data/known_companies.csv for live,
       data/known_companies_test.csv for test; every company in the account,
       refreshed every 3 hours) with websites and names cleaned up, so "www.", "Ltd" or "PLC"
       never hide a match (names only count within the same country);
    2. a live look-up in HubSpot of each website and name, which catches anything added since."""
    # The list of the account being imported into (19 Oct 2026: one list per account).
    known = known_companies.load_index(known_file(target) if target == "test" else None)
    found = set()
    for i, r in enumerate(records):
        if known_companies.matches(known, r.get("domain"), r.get("name"), r.get("country")):
            found.add(i)
    domains = {}
    names = {}
    for i, r in enumerate(records):
        if r.get("domain"):
            d = r["domain"].lower()
            for v in (d, "www." + d):
                domains.setdefault(v, []).append(i)
        names.setdefault(r["name"], []).append(i)
    for prop, index in (("domain", domains), ("website", domains), ("name", names)):
        values = sorted(index)
        for j in range(0, len(values), 50):
            chunk = values[j:j + 50]
            if prop == "website":
                chunk = [f"{scheme}{v}" for v in chunk for scheme in ("http://", "https://")]
            rows = hs.search("companies", [{"propertyName": prop, "operator": "IN", "values": chunk}],
                             ["domain", "name", "website"], max_results=500)
            for row in rows:
                p = row["properties"]
                hits = set()
                d = clean_domain(p.get("domain")) or clean_domain(p.get("website"))
                if d:
                    hits.update(domains.get(d, []))
                if p.get("name"):
                    hits.update(i for n, ids in names.items() if n.lower() == p["name"].lower() for i in ids)
                found.update(hits)
    return found


def hubspot_records(data, statuses):
    """(HubSpot company properties, email notes keyed by domain) for every company. The
    AUTO-OUTREACH tag is added when the records are created (hubspot_client.TagGuard)."""
    records, notes = [], {}
    city, country = split_location(data["location"])
    for c in data["companies"]:
        channel = c["channel_category"][0]
        has_domain = c["domain"] != check_output.NO_DOMAIN
        props = {
            "name": c["name"],
            "country": country,
            INDUSTRY_TYPE: industry_type(channel),
            TIER: f"tier_{c['tier']}",
            **statuses.props("companies", "found" if has_domain else "missing_info"),
        }
        if city:
            props["city"] = city
        if has_domain:
            props["domain"] = c["domain"]
            notes[c["domain"]] = {
                "name": c["name"], "based_out_of": c["based_out_of"] or "",
                "market": data["location"], "category": clean_category(channel),
                "channels": c["channel_category"], "fit_rationale": c["fit_rationale"] or "",
                "what_they_do_well": c["what_they_do_well"],
                "distributes": c["distributes"] or "", "channels_supplied": c["channels_supplied"] or "",
                "sf_brands_carried": c["sf_brands_carried"] or "", "added": now_iso()[:10],
                "research_file": data.get("_file", ""),
            }
        records.append(props)
    return records, notes


def _mark_rejected(rows, job_id, path, reason):
    changed = []
    for r in [r for r in rows if r["job_id"] == job_id and r["status"] == rq.WAITING]:
        changed.append(rq.record_failure(rows, job_id, r["channel"], reason, output_file=relative(path)))
    return changed


def import_file(path, rows, hs, settings, log=print, checker=None, target="live"):
    """Import one file. Returns a short result line for the summary."""
    path = Path(path)
    name = relative(path)
    job_id = job_of(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        reason = f"Rejected: the research file could not be read ({err})"
        changed = _mark_rejected(rows, job_id, path, reason) if job_id else []
        return f"{name}: {reason}" + ("" if changed else " (no waiting job matched it)")
    report = path.with_name(path.stem + "_report.md")
    errors = check_output.check_final(data, report.read_text(encoding="utf-8") if report.exists() else None)
    job_id = data.get("job_id") if isinstance(data, dict) and isinstance(data.get("job_id"), str) else job_id
    job_rows = [r for r in rows if r["job_id"] == job_id]
    if not job_rows:
        return f"{name}: skipped, job {job_id} is not in the queue"
    if not any(r["status"] == rq.WAITING for r in job_rows):
        return f"{name}: skipped, job {job_id} has no Waiting Channel (already finished or cancelled)"
    if errors:
        shown = "; ".join(errors[:3]) + (f"; and {len(errors) - 3} more" if len(errors) > 3 else "")
        _mark_rejected(rows, job_id, path, f"Rejected by the strict check: {shown}")
        return f"{name}: REJECTED by the strict check, nothing added to HubSpot. {shown}"

    data["_file"] = name
    created = existing = missing = inbox = 0
    dropped = []
    if data["companies"]:
        statuses = LeadStatus(hs)
        records, notes = hubspot_records(data, statuses)
        known = already_in_hubspot(hs, records, target)
        checker = checker or default_checker(log)
        checker.prefetch(r.get("domain") for i, r in enumerate(records) if i not in known)
        new = []
        for i, r in enumerate(records):
            if i in known:
                continue
            # Website and Apollo checks: a company nobody could email never reaches gate 1.
            decision, reason = checker.check(r.get("domain"), data["companies"][i].get("confidence"), r.get("name"))
            if decision == "drop":
                dropped.append(f"{r['name']} ({reason})")
                continue
            if decision == "keep" and reason and r.get("domain"):  # e.g. the company inbox note
                notes[r["domain"]]["import_check"] = reason
                inbox += reason == INBOX_NOTE
            if decision == "missing_info":
                r.update(statuses.props("companies", "missing_info"))
                if r.get("domain"):
                    notes[r["domain"]]["import_check"] = reason
                missing += 1
            new.append(r)
        hs.create_tagged("companies", new)
        save_company_notes({r["domain"]: notes[r["domain"]] for r in new if r.get("domain")})
        created, existing = len(new), len(known)
        for d in dropped:
            log(f"Not added (low confidence and {d})")

    # A retry's file replaces the earlier one: point finished lines at the new file.
    for r in rows:
        if r["job_id"] == job_id and r["output_file"] in data["replaces"]:
            r["output_file"] = name
    floor_setting = int(settings.get("min_floor", 30))
    for ch in data["channels"]:
        line = next((r for r in job_rows if rq.norm_channel(r["channel"]) == rq.norm_channel(ch["channel"])
                     and r["status"] == rq.WAITING), None)
        if not line:
            continue
        if ch["status"] == "done":
            floor = min(floor_setting, int(ch["companies_wanted"]))
            if ch["companies_found"] < floor:
                status, reason = rq.DONE_FEWER, f"{ch['companies_found']} found, floor {floor}; see the report"
            else:
                status, reason = rq.DONE, f"{ch['companies_found']} found"
        elif ch["status"] == "on_hold":
            status, reason = rq.ON_HOLD, ch["reason"]
        else:
            rq.record_failure(rows, job_id, line["channel"], ch["reason"], ran_on=data["run_date"],
                              output_file=name)
            continue
        rq.set_status(rows, job_id, line["channel"], status, reason, ran_on=data["run_date"], output_file=name)
    return (f"{name}: {created} companies added to HubSpot ({created - missing} as New, {missing} as Missing Info: "
            f"no working website or nobody in Apollo), {existing} already in HubSpot, {len(dropped)} left out "
            "(low confidence and failed a check)" + (f": {'; '.join(dropped)}" if dropped else "")
            + (f". {inbox} of the New ones have nobody in Apollo; their website's contact address will be "
               "emailed" if inbox else ""))


def default_checker(log=print):
    """The website and Apollo checks, as set in config/settings.yaml (import_checks)."""
    cfg = load_settings().get("import_checks") or {}
    apollo = None
    if cfg.get("apollo", True):
        if os.environ.get("APOLLO_API_KEY"):
            from .apollo_client import Apollo
            apollo = Apollo()
        else:
            log("APOLLO_API_KEY is not set, so the Apollo pre-check is skipped this time")
    return Checker(cfg, apollo=apollo, log=log)


def run(target, hs, files=None, log=print, checker=None):
    rows = rq.load()
    files = [Path(f) if Path(f).is_absolute() else ROOT / f for f in files] if files else pending_files(rows)
    if not files:
        log("No new research files to import.")
        return []
    check_target(hs, target)
    settings = rq.load_research_settings()
    checker = checker if checker is not None else default_checker(log)
    results = []
    for f in files:
        line = import_file(f, rows, hs, settings, log=log, checker=checker, target=target)
        log(line)
        results.append(line)
        rq.save(rows)  # after every file, so a run cut short never redoes finished files
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description="Import new research files into HubSpot")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--file", action="append", default=[], help="a research JSON file (default: all new ones)")
    p.add_argument("--skip-if-not-configured", action="store_true",
                   help="exit quietly when a key is missing (used by the automatic runs)")
    args = p.parse_args(argv)
    if args.skip_if_not_configured and not (os.environ.get("HUBSPOT_TOKEN")):
        print("Research import skipped: a key it needs is not added yet.")
        return 0
    lines = []
    try:
        hs = HubSpot()
        lines = run(args.target, hs, args.file or None)
        code = 0
    except (PipelineError, HubSpotError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        lines, code = [f"ERROR: {err}"], 1
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Research import\n\n" + "\n".join(f"- {line}" for line in lines or ["Nothing to import."])
                     + "\n\n## The queue (newest first)\n\n" + rq.markdown(rq.load()) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
