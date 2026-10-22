"""Step 1 of a research run: pick the job and write every prompt, ready for Claude.

Reads research/queue.csv (never changes it), data/known_companies.csv and
config/exclude.txt, then writes into the work folder:
  plan.json            what this run will do
  exclusions.txt       every company already in HubSpot, for the checks (the prompts list
                       the nearest ones, at most max_exclusions_in_prompt)
  location_prompt.md   for the manager: market structure and barriers to entry
  channel_N_prompt.md  one per Channel, for the helpers

Usage (from the repository's top folder):
    python3 skills/outreachResearch/scripts/prepare_run.py                    # scheduled run
    python3 skills/outreachResearch/scripts/prepare_run.py --manual           # oldest waiting job
    python3 skills/outreachResearch/scripts/prepare_run.py --manual --location "Mumbai, India"
    python3 skills/outreachResearch/scripts/prepare_run.py --manual --job J0003

Exit code 0 = a plan was written; 3 = nothing to do (no waiting job, or this run already finished
max_jobs_per_run jobs). Jobs this run already finished (run_lock.py) are skipped.
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
# Which template a typed Channel uses: the first whose "matches:" words appear in it. The five
# specialist rule sheets (22 Oct 2026, prompt version 5 only) come first, so "kosher food distributors"
# uses the kosher sheet rather than the distributor one; a prompt version without them skips them.
TEMPLATE_ORDER = ("kosher_shop", "kosher_distributor", "halal_distributor", "petrol_convenience", "hospital_shop",
                  "marketplace_seller", "wholesaler", "distributor", "retailer")
LOCATION_SEARCHES = 20  # searches for the manager's market structure and barriers

# 22 Oct 2026 ("Add a market" covers the whole market): the job that lists the country's other main
# cities asks the manager for them too; GitHub then queues a lighter search of each city.
CITIES_SECTION = """

MAIN CITIES (this job only)
Also save a JSON file at {{CITIES_FILE}}: the country's main business cities, where food importers,
wholesalers and shop chains are based, at most {{MAX_CITIES}}, the most important first, each with the
main language spoken there. Use the country's usual spelling
in English. Exactly this shape:
[{"city": "Hamburg", "language": "German"}, {"city": "Munich", "language": "German"}]
Use no more than five of your searches for it, or none if you already know the cities well.
"""

# A follow-up search (a channel searched harder filled all its places last time).
FOLLOW_UP_SECTION = """

FOLLOW-UP SEARCH
An earlier search of this channel in {{MARKET}} filled all its places. Search again with new angles:
other search words and local-language terms, other directories, association member lists, trade show
exhibitor lists and business listings, smaller and regional players, and kinds of business within this
channel the first search did not cover. The companies it found are on the exclusion list: never list
them again.
"""


def ist_today():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    except Exception:  # no time zone data: fall back to UTC + 5:30
        return (dt.datetime.utcnow() + dt.timedelta(hours=5, minutes=30)).date().isoformat()


def slug(text, limit=60):
    out = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return out[:limit].strip("-") or "unnamed"


def read_template(name, suffix=None):
    """A Channel template from the prompt version in settings.yaml (suffix "_2" or "")."""
    if suffix is None:
        suffix = rq.prompt_suffix(rq.load_research_settings())
    text = (SKILL / "prompts" / "channels" / f"{name}{suffix}.md").read_text(encoding="utf-8")
    head, _, body = text.partition("---\n")
    words = []
    for line in head.splitlines():
        if line.lower().startswith("matches:"):
            words = [w.strip().lower() for w in line.split(":", 1)[1].split(",") if w.strip()]
    return words, body.strip()


def choose_template(channel, suffix=None):
    """The closest template for a typed Channel, else "general"."""
    text = " " + " ".join(re.findall(r"[a-z0-9&-]+", channel.lower())) + " "
    if suffix is None:
        suffix = rq.prompt_suffix(rq.load_research_settings())
    for name in TEMPLATE_ORDER:
        if not (SKILL / "prompts" / "channels" / f"{name}{suffix}.md").exists():
            continue  # a specialist sheet this prompt version does not have
        words, _ = read_template(name, suffix)
        if any(w in text for w in words):
            return name
    return "general"


def plural(text):
    return text if text.lower().endswith("s") else text + "s"


def country_of(location):
    return location.split(",")[-1].strip()


def pipeline_target():
    """The account the pipeline works on now ("test" or "live"), as button 2 last wrote it in
    data/pipeline_target.txt. Unknown means test."""
    path = ROOT / "data" / "pipeline_target.txt"
    try:
        value = path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "test"
    return "live" if value == "live" else "test"


def exclusion_lines(country, limit, target=None):
    """(lines for the prompt, every line for the checks, how many known).

    The prompt names at most `limit` companies: config/exclude.txt first, then HubSpot companies
    for the same country, then every company the pipeline itself added or that is a customer.
    The checks (work/exclusions.txt, used by each helper's own check and by the merge) hold
    every company in HubSpot: same-country companies by name and website, all others by
    website, so a company already in HubSpot is dropped even when the prompt could not list it.

    Test account (agreed 19 Oct 2026): no list at all, so a test run simply takes the first
    companies it finds; only the live account is checked against its 40,000+ companies."""
    lines, seen = [], set()
    if (target or pipeline_target()) != "live":
        return [], [], 0

    def add(out, name, domain=""):
        domain = clean_domain(domain) if domain else NO_DOMAIN
        key = (name.strip().lower(), domain)
        if key in seen or not (name.strip() or domain != NO_DOMAIN):
            return
        seen.add(key)
        if name.strip() and domain != NO_DOMAIN:
            out.append(f"- {name.strip()} ({domain})")
        elif name.strip():
            out.append(f"- {name.strip()}")
        else:
            out.append(f"- {domain}")

    exclude_file = ROOT / "config" / "exclude.txt"
    if exclude_file.exists():
        for line in exclude_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                add(lines, line)
    known_file = ROOT / "data" / "known_companies.csv"
    known = []
    if known_file.exists():
        with open(known_file, newline="", encoding="utf-8") as fh:
            known = list(csv.DictReader(fh))
    same_country = [k for k in known if k.get("country", "").strip().lower() == country.lower()]
    in_pipeline = [k for k in known if k.get("why") in ("auto-outreach", "pipeline", "suppressed", "customer")
                   and k.get("country", "").strip().lower() != country.lower()]
    for k in same_country + in_pipeline:
        add(lines, k.get("name", ""), k.get("domain", ""))
    prompt = lines[:limit]
    full = list(lines)
    for k in known:  # every other company, by its website
        if k.get("domain"):
            add(full, "", k["domain"])
    return prompt, full, len(lines)


def earlier_finds(rows, line):
    """Companies the earlier searches of this Location and channel found (for a follow-up search),
    as "- Name (domain)" lines, read from their research files."""
    out, seen = [], set()
    for r in rows:
        if r["output_file"] and rq.same_scope(r, line) and r["job_id"] != line["job_id"]:
            path = ROOT / r["output_file"]
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for c in data.get("companies", []):
                key = (c.get("name") or "").lower()
                if key and key not in seen:
                    seen.add(key)
                    domain = c.get("domain")
                    out.append(f"- {c['name']} ({domain})" if domain and domain != NO_DOMAIN else f"- {c['name']}")
    return out


def output_paths(run_date, job_id, location, channels):
    folder = ROOT / "research" / run_date
    base = f"{job_id}_{run_date}_{slug(location, 40)}_{slug('-'.join(channels), 80)}"
    name, n = base, 2
    while (folder / f"{name}.json").exists():
        name = f"{base}-{n}"
        n += 1
    return folder / f"{name}.json", folder / f"{name}_report.md"


def build(job_id=None, location=None, manual=False, work=None, today=None, skip=()):
    settings = rq.load_research_settings()
    rows = rq.load()
    job_id, lines = rq.waiting_job(rows, job_id=job_id, location=location, skip=skip)
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
    max_deep = int(settings.get("max_searches_deep", max_searches))
    list_cities = any(line.get("list_cities") == "yes" for line in lines)
    target = pipeline_target()
    excl, full, total_known = exclusion_lines(country, int(settings.get("max_exclusions_in_prompt", 500)), target)
    (work / "exclusions.txt").write_text("\n".join(full) + ("\n" if full else ""), encoding="utf-8")
    exclude_text = "\n".join(excl) or "none"

    suffix = rq.prompt_suffix(settings)  # "_2" for the new prompts, "" for the originals
    base_prompt = (SKILL / "prompts" / f"channel_prompt{suffix}.md").read_text(encoding="utf-8")
    channels = []
    for i, line in enumerate(lines, 1):
        wanted = int(line["companies_wanted"] or settings.get("default_companies", 60))
        floor = min(int(settings.get("min_floor", 30)), wanted)
        entry = {
            "index": i, "channel": line["channel"], "template": choose_template(line["channel"], suffix),
            "depth": line.get("depth", ""),
            "companies_wanted": wanted, "floor": floor, "status": "run", "reason": "",
            "prompt_file": "", "output_file": str(work / f"channel_{i}.json"),
        }
        other = rq.is_repeat_now(rows, line)
        if other:
            entry["status"] = "on_hold"
            entry["reason"] = (f"Already covered by {other['job_id']} ({other['status']}, "
                               f"{other['ran_on'] or other['added_on']}); press Approve a repeat to run it")
        else:
            _, rules = read_template(entry["template"], suffix)
            check = (f"python3 skills/outreachResearch/scripts/check_output.py part {entry['output_file']} "
                     f"--exclusions {work / 'exclusions.txt'}")
            if rq.prompt_version(settings) >= 3:
                check += " --catalogue"  # 21 Oct 2026: each company must sell something from our catalogue
            harder = line.get("depth") in (rq.DEEP, rq.FOLLOW_UP)  # typed in button 2: searched harder
            channel_exclude = exclude_text
            if line.get("depth") == rq.FOLLOW_UP:
                earlier = earlier_finds(rows, line)
                if earlier:
                    channel_exclude = "\n".join(earlier + excl) or "none"
            values = {
                "{{CHANNEL_RULES}}": rules,
                "{{CATEGORY_AS_TYPED}}": line["channel"],
                "{{CATEGORY}}": plural(line["channel"].lower()),
                "{{MARKET}}": job_location,
                "{{COUNTRY}}": country,
                "{{LANGUAGES}}": languages,
                "{{EXCLUDE}}": channel_exclude,
                "{{MIN}}": str(wanted),
                "{{FLOOR}}": str(floor),
                "{{MAX_SEARCHES}}": str(max_deep if harder else max_searches),
                "{{OUTPUT_FILE}}": entry["output_file"],
                "{{CHECK_COMMAND}}": check,
            }
            prompt = base_prompt + (FOLLOW_UP_SECTION if line.get("depth") == rq.FOLLOW_UP else "")
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
        if list_cities:
            loc += (CITIES_SECTION.replace("{{CITIES_FILE}}", str(work / "cities.json"))
                    .replace("{{MAX_CITIES}}", str(settings.get("max_cities_per_market", 8))))
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
        "prompt_version": rq.prompt_version(settings),
        "max_searches_per_channel": max_searches, "exclusions_listed": len(excl),
        "exclusions_known": total_known, "target": target, "work": str(work),
        "location_prompt": location_prompt, "location_file": str(work / "location.md"),
        "closing_file": str(work / "closing.md"),
        "list_cities": list_cities, "cities_file": str(work / "cities.json"),
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
    # 22 Oct 2026: a run works through the waiting jobs one after another (run_lock.py); the jobs it
    # already finished are skipped (they stay Waiting until GitHub imports them), and it stops after
    # max_jobs_per_run jobs.
    import run_lock
    done = run_lock.done_in_this_run()
    limit = int(rq.load_research_settings().get("max_jobs_per_run", 8))
    if len(done) >= limit:
        print(f"RUN LIMIT REACHED: this run has finished {len(done)} jobs ({', '.join(done)}), the most "
              f"for one run; the next run carries on with the rest.")
        return NOTHING_TO_DO
    plan = build(args.job or None, args.location or None, args.manual, args.work or None, skip=done)
    if not plan:
        what = f" for {args.job or args.location}" if (args.job or args.location) else ""
        print(f"NOTHING TO DO: no job is waiting in the queue{what}.")
        return NOTHING_TO_DO
    print(f"Job {plan['job_id']}: {plan['location']} ({plan['run_type']} run, {plan['run_date']})")
    if plan.get("target") == "live":
        print(f"Exclusion list: {plan['exclusions_listed']} companies "
              f"(of {plan['exclusions_known']} known)")
    else:
        print("Test account: no 'already in HubSpot' list; the first companies found are used")
    for c in plan["channels"]:
        if c["status"] == "run":
            how = {rq.DEEP: ", searched harder", rq.FOLLOW_UP: ", follow-up search"}.get(c.get("depth"), "")
            print(f"- Channel {c['index']}: {c['channel']} -> template {c['template']}, "
                  f"{c['companies_wanted']} wanted{how}, prompt {c['prompt_file']}")
        else:
            print(f"- Channel {c['index']}: {c['channel']} -> ON HOLD: {c['reason']}")
    for old in plan["replaces"]:
        print(f"Retry: this run replaces {old}")
    if plan.get("list_cities"):
        print(f"This job also lists the country's main cities: save them to {plan['cities_file']} "
              "(the location prompt says how)")
    print(f"Plan saved to {Path(plan['work']) / 'plan.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
