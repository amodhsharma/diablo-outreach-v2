"""Keep research going by itself: add the next city from the automatic list to the queue.

data/auto_markets.csv is a list of cities in the UK, the EU, Canada and South America, shuffled
once into a random order that takes turns between the regions (agreed 12 Oct 2026). People can
remove or reorder lines; the next city is always the first one that is not left out and not
already in the queue.

A city is added only when all of these hold (settings: auto_markets in config/settings.yaml):
  - the automatic list is switched on;
  - nothing is Waiting in the research queue (markets added by hand with 2a always come first);
  - fewer than `max_per_day` automatic cities were added today;
  - fewer than `pause_when_awaiting_review` companies are waiting for review in HubSpot, so the
    team is never buried in companies nobody has looked at.

Usage:
    python -m outreach.auto_markets --target test
"""

import argparse
import csv
import os
import sys

from . import research_queue as rq
from .common import ROOT, load_settings

POOL = ROOT / "data" / "auto_markets.csv"
AUTO_BY = rq.AUTO_BY


def load_pool(path=None):
    with open(path or POOL, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("location") or "").strip()]


def country_of(location):
    return location.split(",")[-1].strip()


def next_city(rows, pool, exclude=()):
    """The first city on the list that has never been in the queue and is not in a left-out
    country (auto_markets.exclude_countries, or data/excluded_countries.txt)."""
    excluded = {rq.countries.find(c) or c for c in exclude} | rq.excluded_countries()
    used = {rq.norm_location(r["location"]) for r in rows}
    for line in pool:
        location = rq.capitalise(line["location"])
        if (rq.countries.find(country_of(location)) or country_of(location)) in excluded:
            continue
        if rq.norm_location(location) in used:
            continue
        return location
    return None


def top_up(rows, pool, cfg, awaiting_review, today=None):
    """Add at most one city. Returns (job_id or None, a plain-words message)."""
    today = today or rq.today()
    if not cfg.get("enabled"):
        return None, "The automatic city list is switched off (auto_markets.enabled in config/settings.yaml)."
    if any(r["status"] == rq.WAITING for r in rows):
        return None, "Research still has work waiting in the queue, so no city was added."
    added_today = {r["job_id"] for r in rows if r["added_by"] == AUTO_BY and r["added_on"] == today}
    if len(added_today) >= int(cfg.get("max_per_day", 1)):
        return None, "Today's automatic city has already been added."
    limit = int(cfg.get("pause_when_awaiting_review", 100))
    if awaiting_review is not None and awaiting_review >= limit:
        return None, (f"{awaiting_review} companies are waiting for review in HubSpot (the limit is {limit}), "
                      "so no city was added. Review them and the list carries on by itself.")
    location = next_city(rows, pool, cfg.get("exclude_countries") or [])
    if not location:
        return None, "Every city on the automatic list has been researched. Add more lines to data/auto_markets.csv."
    job_id, new, _ = rq.add(rows, location, cfg.get("channels") or "distributors, wholesalers, retailers",
                            wanted=cfg.get("companies_wanted") or "", added_by=AUTO_BY, on=today)
    return job_id, f"Added {job_id}: {location} ({', '.join(r['channel'] for r in new)})."


def awaiting_review_count(target):
    from .common import check_target
    from .hubspot_client import HubSpot
    hs = HubSpot()
    check_target(hs, target)
    return hs.count("companies", [{"propertyName": "diablo_outreach_status", "operator": "EQ",
                                   "value": "awaiting_review"}])


def main(argv=None):
    p = argparse.ArgumentParser(description="Add the next city from the automatic list to the research queue")
    p.add_argument("--target", default="test", choices=["test", "live"])
    args = p.parse_args(argv)
    cfg = load_settings().get("auto_markets") or {}
    rows = rq.load()
    try:
        awaiting = awaiting_review_count(args.target) if os.environ.get("HUBSPOT_TOKEN") else None
    except Exception as err:  # without HubSpot the other rules still apply
        print(f"Could not count the companies waiting for review: {err}", file=sys.stderr)
        awaiting = None
    job_id, message = top_up(rows, load_pool(), cfg, awaiting)
    if job_id:
        rq.save(rows)
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## Automatic city list\n\n{message}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
