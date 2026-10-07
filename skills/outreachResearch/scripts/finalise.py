"""Steps 3 and 4 of a research run: merge the helpers' files, then build the report.

    python3 skills/outreachResearch/scripts/finalise.py merge
        Reads work/plan.json and each helper's work/channel_N.json. Tidies domains and
        dashes, drops excluded companies, merges a company found under two Channels into
        one entry (both Channels listed), renumbers ranks and writes the final JSON to
        research/<date>/. A helper file that is missing or fails the check marks that
        Channel as failed; the other Channels carry on.

    python3 skills/outreachResearch/scripts/finalise.py report
        Builds the report next to the JSON from work/location.md, work/closing.md and the
        company lists, then runs the strict check on both files.

Run both from the repository's top folder. Standard library only.
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(HERE))

from check_output import (  # noqa: E402
    FORMAT, NO_DOMAIN, check_final, check_part, clean_domain, load_exclusions, norm_name,
)

TEXT_FIELDS = ("name", "based_out_of", "distributes", "channels_supplied", "sf_brands_carried", "fit_rationale")


def tidy_text(value):
    """No em or en dashes (Ariel's writing rule); single spaces."""
    if not isinstance(value, str):
        return value
    value = value.replace(" — ", " - ").replace("—", " - ").replace("–", "-")
    return " ".join(value.split())


def load_plan(work):
    return json.loads((Path(work) / "plan.json").read_text(encoding="utf-8"))


def _read_helper(entry, exclusions):
    """(data, None) for a usable helper file, or (None, reason)."""
    path = Path(entry["output_file"])
    if not path.exists():
        return None, "The helper did not save its file (it may have stopped early, e.g. a usage limit)"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as err:
        return None, f"The helper's file is not valid JSON ({err})"
    if isinstance(data, dict) and isinstance(data.get("companies"), list):
        for c in data["companies"]:
            if isinstance(c, dict):
                c["domain"] = clean_domain(c.get("domain"))
                for key in TEXT_FIELDS:
                    c[key] = tidy_text(c.get(key))
                if isinstance(c.get("what_they_do_well"), list):
                    c["what_they_do_well"] = [tidy_text(x) for x in c["what_they_do_well"]]
                if isinstance(c.get("confidence"), str):
                    c["confidence"] = c["confidence"].strip().lower()
    # Excluded companies are dropped here rather than failing the Channel.
    errors = check_part(data)
    if errors:
        shown = "; ".join(errors[:3]) + (f"; and {len(errors) - 3} more" if len(errors) > 3 else "")
        return None, f"The helper's file failed the strict check: {shown}"
    return data, None


def _carry_over(plan, notes):
    """On a retry: the finished Channels and companies of the earlier file(s) this run replaces.
    Returns (channel rows, companies). A file that fails the check is not reused."""
    retried = {ch["channel"] for ch in plan["channels"]}
    rows, companies = [], []
    for old in plan.get("replaces", []):
        path = ROOT / old
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if check_final(data):
            notes["warnings"].append(f"The earlier file {old} did not pass the check, so nothing was reused from it.")
            continue
        kept = [ch for ch in data["channels"] if ch["status"] == "done" and ch["channel"] not in retried]
        names = {ch["channel"] for ch in kept}
        for ch in kept:
            rows.append(ch)
            notes["channels"][ch["channel"]] = {
                "tier_logic": f"Researched in the earlier run on {data['run_date']} and kept as it was.",
                "checked_and_excluded": [], "shortfall_note": None}
        for c in data["companies"]:
            if c["channel_category"][0] in names:
                companies.append(dict(c, channel_category=[x for x in c["channel_category"] if x in names]))
        if kept:
            notes["warnings"].append(f"Retry: {', '.join(names)} kept from the earlier run on {data['run_date']}; "
                                     "only the Channels that failed were researched again.")
    return rows, companies


def merge(work):
    plan = load_plan(work)
    exclusions = load_exclusions(Path(work) / "exclusions.txt")
    names, domains = exclusions
    notes = {"channels": {}, "merged": [], "dropped": [], "warnings": []}
    entries = []
    channel_rows, carried = _carry_over(plan, notes)
    for ch in plan["channels"]:
        row = {"channel": ch["channel"], "template": ch["template"], "status": ch["status"],
               "reason": ch["reason"], "companies_wanted": ch["companies_wanted"],
               "companies_found": 0, "searches_used": 0}
        channel_rows.append(row)
        if ch["template"] == "general":
            notes["warnings"].append(f'"{ch["channel"]}" matched none of the four templates, so the general '
                                     "template was used with its own words.")
        if ch["status"] != "run":
            row["status"] = "on_hold"
            notes["warnings"].append(f'"{ch["channel"]}" was not researched: {ch["reason"]}.')
            continue
        data, problem = _read_helper(ch, exclusions)
        if problem:
            row["status"], row["reason"] = "failed", problem
            notes["warnings"].append(f'"{ch["channel"]}" failed: {problem}. Use "Retry a failed job".')
            continue
        row["status"], row["searches_used"] = "done", data["searches_used"]
        notes["channels"][ch["channel"]] = {
            "tier_logic": tidy_text(data["tier_logic"]),
            "checked_and_excluded": [{"name": tidy_text(x["name"]), "reason": tidy_text(x["reason"])}
                                     for x in data["checked_and_excluded"]],
            "shortfall_note": tidy_text(data["shortfall_note"]),
        }
        for c in data["companies"]:
            if norm_name(c["name"]) in names or c["domain"] in domains:
                notes["dropped"].append({"name": c["name"], "channel": ch["channel"],
                                         "reason": "already known, on the exclusion list"})
                continue
            entries.append((ch["index"], ch["channel"], c))

    # One entry per company; the Channel where it ranks best becomes its main Channel.
    entries.sort(key=lambda e: (e[2]["tier"], e[2]["tier_rank"], e[0]))
    merged, by_key = [], {}
    for c in carried:
        c = dict(c, _order=(0, c["tier"], c["tier_rank"]))
        merged.append(c)
        for k in ((("d", c["domain"]),) if c["domain"] != NO_DOMAIN else ()) + (("n", norm_name(c["name"])),):
            by_key.setdefault(k, c)
    for index, channel, c in entries:
        keys = [k for k in (("d", c["domain"]) if c["domain"] != NO_DOMAIN else None,
                            ("n", norm_name(c["name"]))) if k]
        found = next((by_key[k] for k in keys if k in by_key), None)
        if found:
            if channel not in found["channel_category"]:
                found["channel_category"].append(channel)
            for url in c["source_urls"]:
                if url not in found["source_urls"]:
                    found["source_urls"].append(url)
            notes["merged"].append({"name": found["name"], "also": channel})
        else:
            found = {
                "name": c["name"], "based_out_of": c["based_out_of"], "domain": c["domain"],
                "channel_category": [channel],
                "tier": c["tier"], "tier_rank": c["tier_rank"], "distributes": c["distributes"],
                "channels_supplied": c["channels_supplied"], "sf_brands_carried": c["sf_brands_carried"],
                "competing_brand_flag": c["competing_brand_flag"], "fit_rationale": c["fit_rationale"],
                "what_they_do_well": list(c["what_they_do_well"]),
                "confidence": c["confidence"], "source_urls": list(c["source_urls"]),
                "_order": (index, c["tier"], c["tier_rank"]),
            }
            merged.append(found)
        for k in keys:
            by_key.setdefault(k, found)

    # Ranks run 1, 2, 3... within each main Channel and tier.
    merged.sort(key=lambda c: c["_order"])
    counters = {}
    for c in merged:
        key = (c["channel_category"][0], c["tier"])
        counters[key] = counters.get(key, 0) + 1
        c["tier_rank"] = counters[key]
        del c["_order"]
    for row in channel_rows:
        if row["status"] == "done":
            row["companies_found"] = sum(1 for c in merged if row["channel"] in c["channel_category"])
            floor = next((ch["floor"] for ch in plan["channels"] if ch["channel"] == row["channel"]), 0)
            if row["companies_found"] < floor:
                note = notes["channels"][row["channel"]]["shortfall_note"] or "no reason given"
                notes["warnings"].append(f'"{row["channel"]}" found {row["companies_found"]} companies, '
                                         f'fewer than the floor of {floor}: {note}')

    final = {
        "format": FORMAT, "job_id": plan["job_id"], "location": plan["location"],
        "run_date": plan["run_date"], "run_type": plan["run_type"],
        "replaces": plan.get("replaces", []), "channels": channel_rows,
        "companies": merged,
    }
    out = ROOT / plan["output_json"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(final, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (Path(work) / "merge_notes.json").write_text(json.dumps(notes, indent=2, ensure_ascii=False),
                                                  encoding="utf-8")
    errors = check_final(final, None, exclusions)
    print(f"Merged file saved: {plan['output_json']}")
    for old in final["replaces"]:
        for path in (ROOT / old, (ROOT / old).with_name(Path(old).stem + "_report.md")):
            if path.exists() and path != out:
                path.unlink()
                print(f"Removed the earlier file it replaces: {path.relative_to(ROOT)}")
    for row in channel_rows:
        extra = f" ({row['reason']})" if row["reason"] else ""
        print(f"- {row['channel']}: {row['status']}, {row['companies_found']} companies{extra}")
    if notes["merged"]:
        print(f"- {len(notes['merged'])} companies were found under more than one Channel and merged")
    if notes["dropped"]:
        print(f"- {len(notes['dropped'])} companies dropped as already known")
    print("\nTier 1 companies (for the closing analysis):")
    for c in merged:
        if c["tier"] == 1:
            print(f"- {c['name']} ({c['domain']}), {c['channel_category'][0]} rank {c['tier_rank']}: "
                  f"{c['fit_rationale']}")
    print("\nCheck: " + ("PASSED" if not errors else "FAILED\n" + "\n".join(f"- {e}" for e in errors)))
    return 0 if not errors else 1


def _sections(path):
    """{"market structure": text, "barriers to entry": text} from the manager's Markdown file."""
    out = {}
    if not Path(path).exists():
        return out
    text = tidy_lines(Path(path).read_text(encoding="utf-8"))
    for match in re.finditer(r"^##\s+(.+?)\s*\n(.*?)(?=^##\s|\Z)", text, re.S | re.M):
        out[match.group(1).strip().lower()] = match.group(2).strip()
    return out


def tidy_lines(text):
    return text.replace(" — ", " - ").replace("—", " - ").replace("–", "-")


def report(work):
    plan = load_plan(work)
    final = json.loads((ROOT / plan["output_json"]).read_text(encoding="utf-8"))
    notes = json.loads((Path(work) / "merge_notes.json").read_text(encoding="utf-8"))
    location = _sections(plan["location_file"])
    closing_path = Path(plan["closing_file"])
    closing = tidy_lines(closing_path.read_text(encoding="utf-8")).strip() if closing_path.exists() else ""
    closing = re.sub(r"^##\s+Closing analysis\s*\n", "", closing, flags=re.I).strip()
    not_written = "Not available for this run: {}."
    done = [c for c in final["channels"] if c["status"] == "done"]

    lines = [f"# Research report: {final['location']}", "",
             f"Job {final['job_id']} | {final['run_type'].capitalize()} run | {final['run_date']}", ""]
    lines += ["| Channel | Template | Status | Companies | Searches |", "|---|---|---|---|---|"]
    for ch in final["channels"]:
        status = {"done": "Done", "failed": "Failed", "on_hold": "On hold"}[ch["status"]]
        lines.append(f"| {ch['channel']} | {ch['template'].replace('_', ' ')} | {status} | "
                     f"{ch['companies_found']} of {ch['companies_wanted']} wanted | {ch['searches_used']} |")
    lines += ["", "## Warnings", ""]
    lines += [f"- {w}" for w in notes["warnings"]] or ["- None."]

    lines += ["", "## Market structure", "",
              location.get("market structure") or not_written.format("the market structure was not written")]

    lines += ["", "## Companies by Channel", "",
              "Full details for every company (Domain of the found company, what they distribute, why they "
              "fit, Found the company from) are in the JSON file next to this report.", "",
              "<!-- companies:start -->"]
    for ch in final["channels"]:
        mine = [c for c in final["companies"] if c["channel_category"][0] == ch["channel"]]
        lines += ["", f"### {ch['channel']}", ""]
        if ch["status"] != "done":
            lines.append(f"Not researched: {ch['reason']}")
            continue
        lines.append(notes["channels"].get(ch["channel"], {}).get("tier_logic") or "")
        also = sum(1 for c in final["companies"]
                   if ch["channel"] in c["channel_category"][1:])
        if also:
            lines += ["", f"{also} more {'company' if also == 1 else 'companies'} found for this Channel "
                          f"{'is' if also == 1 else 'are'} listed under another Channel."]
        for tier in (1, 2, 3):
            tier_rows = [c for c in mine if c["tier"] == tier]
            if not tier_rows:
                continue
            lines += ["", f"**Tier {tier}**", "", "| Rank | Company |", "|---|---|"]
            for c in sorted(tier_rows, key=lambda c: c["tier_rank"]):
                extra = f" (also: {', '.join(c['channel_category'][1:])})" if len(c["channel_category"]) > 1 else ""
                lines.append(f"| {c['tier_rank']} | {c['name'].replace('|', '/')}{extra} |")
    lines += ["", "<!-- companies:end -->", "", "## Checked and excluded", ""]
    any_excluded = False
    for ch in done:
        items = notes["channels"].get(ch["channel"], {}).get("checked_and_excluded") or []
        dropped = [d for d in notes["dropped"] if d["channel"] == ch["channel"]]
        parts = [f"{x['name']} ({x['reason']})" for x in items] + [f"{d['name']} ({d['reason']})" for d in dropped]
        if parts:
            any_excluded = True
            lines.append(f"- **{ch['channel']}:** " + "; ".join(parts) + ".")
    if not any_excluded:
        lines.append("- None.")
    lines += ["", "## Closing analysis", "",
              closing or not_written.format("no companies were found to compare"),
              "", "## Barriers to entry", "",
              location.get("barriers to entry") or not_written.format("the barriers were not written"), ""]

    text = "\n".join(lines)
    report_path = ROOT / plan["output_report"]
    report_path.write_text(text, encoding="utf-8")
    errors = check_final(final, text, load_exclusions(Path(work) / "exclusions.txt"))
    print(f"Report saved: {plan['output_report']}")
    print("Check: " + ("PASSED" if not errors else "FAILED\n" + "\n".join(f"- {e}" for e in errors)))
    return 0 if not errors else 1


def main(argv=None):
    p = argparse.ArgumentParser(description="Merge the helpers' files, then build the report")
    p.add_argument("step", choices=["merge", "report"])
    p.add_argument("--work", default=str(ROOT / "work"))
    args = p.parse_args(argv)
    return merge(args.work) if args.step == "merge" else report(args.work)


if __name__ == "__main__":
    sys.exit(main())
