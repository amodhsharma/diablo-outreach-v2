"""Import new research files into HubSpot and record the result in the queue.

Runs by itself when the outreachResearch skill saves files to research/<date>/. Each new
JSON file is checked again with the skill's strict check: a file that fails is rejected
whole (nothing reaches HubSpot). A file that passes is added to HubSpot as "Awaiting
review" (gate 1) and the email details go into data/company_notes.json. Each Channel's line
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

from . import research_queue as rq
from .common import (
    ROOT, PipelineError, check_target, clean_category, country_of, enum_value, now_iso,
    save_company_notes,
)
from .hubspot_client import HubSpot, HubSpotError

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


def already_in_hubspot(hs, domains, names=()):
    """Domains and names (lower case) that already belong to a HubSpot company."""
    found_domains, found_names = set(), set()
    for prop, values, out in (("domain", domains, found_domains), ("name", names, found_names)):
        values = sorted({v for v in values if v})
        for i in range(0, len(values), 50):
            rows = hs.search("companies",
                             [{"propertyName": prop, "operator": "IN", "values": values[i:i + 50]}],
                             ["domain", "name"], max_results=500)
            for r in rows:
                v = r["properties"].get(prop)
                if v:
                    out.add(v.lower())
    return found_domains, found_names


def hubspot_records(data):
    """(HubSpot company properties, email notes keyed by domain) for every company."""
    records, notes = [], {}
    for c in data["companies"]:
        channel = c["channel_category"][0]
        has_domain = c["domain"] != check_output.NO_DOMAIN
        props = {
            "name": c["name"],
            "country": country_of(data["location"]),
            "diablo_market": data["location"],
            "diablo_channel_category": enum_value(clean_category(channel)),
            "diablo_tier": enum_value(f"Tier {c['tier']}"),
            "diablo_outreach_status": "awaiting_review" if has_domain else "no_domain",
        }
        if has_domain:
            props["domain"] = c["domain"]
            notes[c["domain"]] = {
                "name": c["name"], "based_out_of": c["based_out_of"] or "",
                "market": data["location"], "category": clean_category(channel),
                "channels": c["channel_category"], "fit_rationale": c["fit_rationale"] or "",
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


def import_file(path, rows, hs, settings, log=print):
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
    created = existing = 0
    done = [ch for ch in data["channels"] if ch["status"] == "done"]
    if data["companies"]:
        for ch in done:
            label = clean_category(ch["channel"])
            if hs.ensure_option("companies", "diablo_channel_category", label, enum_value(label)):
                log(f"New Channel '{label}' added to the HubSpot dropdown")
        records, notes = hubspot_records(data)
        domains, names = already_in_hubspot(
            hs, [r.get("domain") for r in records], [r["name"] for r in records if not r.get("domain")])
        new = [r for r in records if (r["domain"].lower() not in domains if r.get("domain")
                                      else r["name"].lower() not in names)]
        hs.batch_create("companies", new)
        save_company_notes({r["domain"]: notes[r["domain"]] for r in new if r.get("domain")})
        created, existing = len(new), len(records) - len(new)

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
    return (f"{name}: {created} companies added to HubSpot as Awaiting review or No domain, "
            f"{existing} already in HubSpot")


def run(target, hs, files=None, log=print):
    rows = rq.load()
    files = [Path(f) if Path(f).is_absolute() else ROOT / f for f in files] if files else pending_files(rows)
    if not files:
        log("No new research files to import.")
        return []
    check_target(hs, target)
    settings = rq.load_research_settings()
    results = []
    for f in files:
        line = import_file(f, rows, hs, settings, log=log)
        log(line)
        results.append(line)
    rq.save(rows)
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description="Import new research files into HubSpot")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--file", action="append", default=[], help="a research JSON file (default: all new ones)")
    args = p.parse_args(argv)
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
