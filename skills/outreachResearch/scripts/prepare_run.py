"""Step 1 of a research run: pick the job and write every prompt, ready for Claude.

Reads research/queue.csv (never changes it), data/known_companies.csv and
config/exclude.txt, then writes into the work folder:
  plan.json            what this run will do
  exclusions.txt       the companies the prompts tell Claude to leave out
  location_prompt.md   for the manager: market structure and barriers to entry
  channel_N_prompt.md  one per Channel, for the helpers

Usage (from the repository's top folder):
    python3 skills/outreachResearch/scripts/prepare_run.py                    # scheduled run
    python3 skills/outreachResearch/scripts/prepare_run.py --manual           # oldest waiting job
    python3 skills/outreachResearch/scripts/prepare_run.py --manual --location "Mumbai, India"
    python3 skills/outreachResearch/scripts/prepare_run.py --manual --job J0003

Exit code 0 = a plan was written; 3 = nothing to do (no waiting job).
"""

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
ROOT = SKILL.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from outreach import research_queue as rq  # noqa: E402
from check_output import NO_DOMAIN, clean_domain  # noqa: E402

NOTHING_TO_DO = 3
# Which template a typed Channel uses: the first whose "matches:" words appear in it.
TEMPLATE_ORDER = ("marketplace_seller", "wholesaler", "distributor", "retailer")
LOCATION_SEARCHES = 20  # searches for the manager's market structure and barriers


def ist_today():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    except Exception:  # no time zone data: fall back to UTC + 5:30
        return (dt.datetime.utcnow() + dt.timedelta(hours=5, minutes=30)).date().isoformat()


def slug(text, limit=60):
    out = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return out[:limit].strip("-") or "unnamed"


def read_template(name):
    text = (SKILL / "prompts" / "channels" / f"{name}.md").read_text(encoding="utf-8")
    head, _, body = text.partition("---\n")
    words = []
    for line in head.splitlines():
        if line.lower().startswith("matches:"):
            words = [w.strip().lower() for w in line.split(":", 1)[1].split(",") if w.strip()]
    return words, body.strip()


def choose_template(channel):
    """The closest of the four templates for a typed Channel, else "general"."""
    text = " " + " ".join(re.findall(r"[a-z0-9&-]+", channel.lower())) + " "
    for name in TEMPLATE_ORDER:
        words, _ = read_template(name)
        if any(w in text for w in words):
            return name
    return "general"


def plural(text):
    return text if text.lower().endswith("s") else text + "s"


def country_of(location):
    return location.split(",")[-1].strip()


def exclusion_lines(country, limit):
    """Companies to leave out: config/exclude.txt first, then HubSpot companies for the same
    country, then every other company already in the pipeline, suppressed or a customer."""
    lines, seen = [], set()

    def add(name, domain=""):
        domain = clean_domain(domain) if domain else NO_DOMAIN
        key = (name.strip().lower(), domain)
        if key in seen or not (name.strip() or domain != NO_DOMAIN):
            return
        seen.add(key)
        if name.strip() and domain != NO_DOMAIN:
            lines.append(f"- {name.strip()} ({domain})")
        else:
            lines.append(f"- {name.strip() or domain}")

    exclude_file = ROOT / "config" / "exclude.txt"
    if exclude_file.exists():
        for line in exclude_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                add(line)
    known_file = ROOT / "data" / "known_companies.csv"
    known = []
    if known_file.exists():
        with open(known_file, newline="", encoding="utf-8") as fh:
            known = list(csv.DictReader(fh))
    same_country = [k for k in known if k.get("country", "").strip().lower() == country.lower()]
    in_pipeline = [k for k in known if k.get("why") in ("pipeline", "suppressed", "customer")]
    for k in same_country + in_pipeline:
        add(k.get("name", ""), k.get("domain", ""))
    return lines[:limit], len(lines)


def output_paths(run_date, job_id, location, channels):
    folder = ROOT / "research" / run_date
    base = f"{job_id}_{run_date}_{slug(location, 40)}_{slug('-'.join(channels), 80)}"
    name, n = base, 2
    while (folder / f"{name}.json").exists():
        name = f"{base}-{n}"
        n += 1
    return folder / f"{name}.json", folder / f"{name}_report.md"


def build(job_id=None, location=None, manual=False, work=None, today=None):
    settings = rq.load_research_settings()
    rows = rq.load()
    job_id, lines = rq.waiting_job(rows, job_id=job_id, location=location)
    if not job_id:
        return None
    work = Path(work or ROOT / "work")
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("*"):
        if old.is_file():
            old.unlink()

    run_date = today or ist_today()
    job_location = lines[0]["location"]
    country = country_of(job_location)
    languages = lines[0]["languages"] or "the main local languages"
    max_searches = int(settings.get("max_searches_per_channel", 60))
    excl, total_known = exclusion_lines(country, int(settings.get("max_exclusions_in_prompt", 500)))
    (work / "exclusions.txt").write_text("\n".join(excl) + ("\n" if excl else ""), encoding="utf-8")
    exclude_text = "\n".join(excl) or "none"

    base_prompt = (SKILL / "prompts" / "channel_prompt.md").read_text(encoding="utf-8")
    channels = []
    for i, line in enumerate(lines, 1):
        wanted = int(line["companies_wanted"] or settings.get("default_companies", 60))
        floor = min(int(settings.get("min_floor", 30)), wanted)
        entry = {
            "index": i, "channel": line["channel"], "template": choose_template(line["channel"]),
            "companies_wanted": wanted, "floor": floor, "status": "run", "reason": "",
            "prompt_file": "", "output_file": str(work / f"channel_{i}.json"),
        }
        other = rq.is_repeat_now(rows, line)
        if other:
            entry["status"] = "on_hold"
            entry["reason"] = (f"Already covered by {other['job_id']} ({other['status']}, "
                               f"{other['ran_on'] or other['added_on']}); press Approve a repeat to run it")
        else:
            _, rules = read_template(entry["template"])
            check = (f"python3 skills/outreachResearch/scripts/check_output.py part {entry['output_file']} "
                     f"--exclusions {work / 'exclusions.txt'}")
            values = {
                "{{CHANNEL_RULES}}": rules,
                "{{CATEGORY_AS_TYPED}}": line["channel"],
                "{{CATEGORY}}": plural(line["channel"].lower()),
                "{{MARKET}}": job_location,
                "{{COUNTRY}}": country,
                "{{LANGUAGES}}": languages,
                "{{EXCLUDE}}": exclude_text,
                "{{MIN}}": str(wanted),
                "{{FLOOR}}": str(floor),
                "{{MAX_SEARCHES}}": str(max_searches),
                "{{OUTPUT_FILE}}": entry["output_file"],
                "{{CHECK_COMMAND}}": check,
            }
            prompt = base_prompt
            for key, value in values.items():
                prompt = prompt.replace(key, value)
            left = re.findall(r"\{\{[A-Z_]+\}\}", prompt)
            if left:
                raise SystemExit(f"Prompt for {line['channel']} still has placeholders: {left}")
            entry["prompt_file"] = str(work / f"channel_{i}_prompt.md")
            Path(entry["prompt_file"]).write_text(prompt, encoding="utf-8")
        channels.append(entry)

    running = [c for c in channels if c["status"] == "run"]
    location_prompt = ""
    if running:
        loc = (SKILL / "prompts" / "location_prompt.md").read_text(encoding="utf-8")
        for key, value in {
            "{{MARKET}}": job_location, "{{COUNTRY}}": country,
            "{{CHANNEL_LIST}}": ", ".join(c["channel"] for c in running),
            "{{MAX_SEARCHES}}": str(LOCATION_SEARCHES), "{{OUTPUT_FILE}}": str(work / "location.md"),
        }.items():
            loc = loc.replace(key, value)
        location_prompt = str(work / "location_prompt.md")
        Path(location_prompt).write_text(loc, encoding="utf-8")

    # A retry replaces the earlier run's files for this job: the new file keeps that run's
    # finished Channels and adds the ones tried again, and the old files are removed.
    replaces = sorted({r["output_file"] for r in lines if rq.is_retry(r)})
    all_channels = [r["channel"] for r in rows if r["job_id"] == job_id and r["status"] != rq.CANCELLED]
    json_path, report_path = output_paths(run_date, job_id, job_location, all_channels)
    plan = {
        "job_id": job_id, "location": job_location, "country": country, "languages": languages,
        "run_date": run_date, "run_type": "manual" if manual else "scheduled",
        "max_searches_per_channel": max_searches, "exclusions_listed": len(excl),
        "exclusions_known": total_known, "work": str(work),
        "location_prompt": location_prompt, "location_file": str(work / "location.md"),
        "closing_file": str(work / "closing.md"),
        "output_json": str(json_path.relative_to(ROOT)), "output_report": str(report_path.relative_to(ROOT)),
        "replaces": replaces,
        "channels": channels,
    }
    (work / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return plan


def main(argv=None):
    p = argparse.ArgumentParser(description="Pick the next research job and write its prompts")
    p.add_argument("--manual", action="store_true", help="a manual run (not the scheduled run)")
    p.add_argument("--job", default="", help="run this job ID instead of the oldest")
    p.add_argument("--location", default="", help="run the oldest waiting job for this Location")
    p.add_argument("--work", default="", help="work folder (default: work/ in the repository)")
    args = p.parse_args(argv)
    plan = build(args.job or None, args.location or None, args.manual, args.work or None)
    if not plan:
        what = f" for {args.job or args.location}" if (args.job or args.location) else ""
        print(f"NOTHING TO DO: no job is waiting in the queue{what}.")
        return NOTHING_TO_DO
    print(f"Job {plan['job_id']}: {plan['location']} ({plan['run_type']} run, {plan['run_date']})")
    print(f"Exclusion list: {plan['exclusions_listed']} companies "
          f"(of {plan['exclusions_known']} known)")
    for c in plan["channels"]:
        if c["status"] == "run":
            print(f"- Channel {c['index']}: {c['channel']} -> template {c['template']}, "
                  f"{c['companies_wanted']} wanted, prompt {c['prompt_file']}")
        else:
            print(f"- Channel {c['index']}: {c['channel']} -> ON HOLD: {c['reason']}")
    for old in plan["replaces"]:
        print(f"Retry: this run replaces {old}")
    print(f"Plan saved to {Path(plan['work']) / 'plan.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
