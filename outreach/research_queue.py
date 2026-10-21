"""The research queue: research/queue.csv, one line per Location and Channel.

Lines are never deleted, so the file is also the record of everything covered.
Only GitHub jobs change this file (the four queue buttons and the import job).
The outreachResearch skill only reads it.

This module uses the Python standard library only, so the skill can use it too.

Usage (from the GitHub buttons):
    python -m outreach.research_queue add --location "Mumbai, India" --channels "distributors, retailers" \
        (several cities, one job each: --location "Hamburg, Munich, Cologne, Germany")
        --languages "Hindi, Marathi" --wanted 60 --by ariel
    python -m outreach.research_queue cancel --job J0003 [--channel retailers]
    python -m outreach.research_queue retry --job J0003 [--channel retailers]
    python -m outreach.research_queue approve --job J0003 [--channel retailers] --by ariel
    python -m outreach.research_queue show
"""

import argparse
import csv
import datetime as dt
import os
import re
import sys
from pathlib import Path

from . import countries

ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = ROOT / "research" / "queue.csv"
# The highest job ID ever given (21 Oct 2026): job IDs never start again at J0001 when the queue is
# cleared, so "Job Number" in HubSpot always points to one job.
LAST_ID_FILE = ROOT / "research" / "last_job_id.txt"
EXCLUDED_FILE = ROOT / "data" / "excluded_countries.txt"
SETTINGS_FILE = ROOT / "skills" / "outreachResearch" / "settings.yaml"

COLUMNS = [
    "job_id", "location", "channel", "languages", "companies_wanted", "added_by", "added_on",
    "status", "reason", "approved_by", "ran_on", "output_file", "attempts",
]

WAITING = "Waiting"
ON_HOLD = "On hold: already covered"
DONE = "Done"
DONE_FEWER = "Done, fewer than wanted"
FAILED = "Failed"
CANCELLED = "Cancelled"
STATUSES = (WAITING, ON_HOLD, DONE, DONE_FEWER, FAILED, CANCELLED)

# A Location and Channel counts as covered once a line for it is waiting or done.
COVERED = (WAITING, DONE, DONE_FEWER)

# Jobs added by the automatic city list (outreach/auto_markets.py) carry this in added_by.
# A market added by hand always runs before them.
AUTO_BY = "automatic city list"

# A failed Channel is retried once by itself at the next run; after that it stays Failed
# until someone presses "Retry a failed job".
AUTO_RETRIES = 1


class QueueError(RuntimeError):
    """A problem the person pressing the button needs to fix."""


# ---- settings (a flat "name: number" file, read without extra packages) ----

def load_research_settings(path=None):
    values = {}
    path = Path(path or SETTINGS_FILE)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" in line:
            key, value = (part.strip() for part in line.split(":", 1))
            if value:
                values[key] = int(value) if value.isdigit() else value
    # Prompt version 2 (agreed 14 Oct 2026) has its own numbers; version 1 keeps the originals.
    if prompt_version(values) >= 2:
        for key in ("default_companies", "min_floor"):
            if f"{key}_2" in values:
                values[key] = values[f"{key}_2"]
    return values


def prompt_version(settings):
    """1 = the original research prompts, 2 = the _2 prompts (the default when not set),
    3 = the _3 prompts (21 Oct 2026: Diablo's hard rules and catalogue)."""
    value = str(settings.get("prompt_version", 2)).strip()
    return {"1": 1, "3": 3}.get(value, 2)


def prompt_suffix(settings):
    """The ending of the research prompt files to use: "" for version 1, "_2" or "_3"."""
    version = prompt_version(settings)
    return "" if version == 1 else f"_{version}"


# ---- matching rules -------------------------------------------------------

def tidy(text):
    """Single spaces and tidy commas: "  Mumbai ,India " -> "Mumbai, India"."""
    parts = [" ".join(p.split()) for p in str(text or "").split(",")]
    return ", ".join(p for p in parts if p)


_SMALL_WORDS = {"and", "of", "the", "de", "da", "del", "la", "le", "upon", "on"}


def capitalise(text):
    """Capitals for a Location typed all in lower case: "dublin, ireland" -> "Dublin, Ireland".
    Parts typed with capitals are kept, and the country is written the usual way for the
    name typed ("usa" -> "USA"; UK stays UK, it is not changed to United Kingdom)."""
    parts = []
    for part in tidy(text).split(", "):
        if part == part.lower():
            words = part.split(" ")
            part = " ".join(w if (i and w in _SMALL_WORDS) else w[:1].upper() + w[1:]
                            for i, w in enumerate(words))
        parts.append(part)
    if parts and countries.spelling(parts[-1]):
        parts[-1] = countries.spelling(parts[-1])
    return ", ".join(parts)


def check_country(location):
    """Stop if the last part of a Location is not a country we know, suggesting the closest."""
    country = tidy(location).split(", ")[-1]
    if countries.find(country):
        return
    close = countries.suggest(country)
    hint = f" Did you mean {' or '.join(close)}?" if close else ""
    raise QueueError(
        f'"{country}" is not a country I know.{hint} Type the Location with the country last, '
        'after a comma, e.g. "Mumbai, India". Nothing was added.')


def excluded_countries(path=None):
    """Countries Diablo does not look for leads in (data/excluded_countries.txt), as the
    standard country names."""
    path = Path(path or EXCLUDED_FILE)
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            names.add(countries.find(line) or line)
    return names


def check_not_excluded(location, excluded=None):
    """Stop if the Location is in a country on the do-not-research list."""
    country = tidy(location).split(", ")[-1]
    name = countries.find(country) or country
    if name in (excluded if excluded is not None else excluded_countries()):
        raise QueueError(
            f"{name} is on the list of countries we do not look for leads in "
            "(data/excluded_countries.txt). Nothing was added.")


def norm_location(text):
    """Locations match as written, ignoring capitals and spaces only.
    "UK" and "United Kingdom" stay different."""
    return tidy(text).lower()


def _singular(word):
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def norm_channel(text):
    """Channels match ignoring capitals, spaces, punctuation and singular or plural,
    so "Wholesaler" matches "wholesalers". Any other difference in wording is a new Channel."""
    words = re.findall(r"[a-z0-9&]+", str(text or "").lower())
    return " ".join(_singular(w) for w in words)


def same_scope(a, b):
    return (norm_location(a["location"]) == norm_location(b["location"])
            and norm_channel(a["channel"]) == norm_channel(b["channel"]))


# ---- file ----------------------------------------------------------------

def load(path=None):
    path = Path(path or QUEUE_FILE)
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [{c: (row.get(c) or "") for c in COLUMNS} for row in csv.DictReader(fh)]


def save(rows, path=None):
    path = Path(path or QUEUE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in COLUMNS})


def today():
    return dt.date.today().isoformat()


def last_job_number(path=None):
    """The highest job number ever given, from research/last_job_id.txt (0 when there is none)."""
    try:
        text = Path(path or LAST_ID_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return 0
    return int(text[1:]) if re.fullmatch(r"J\d+", text) else 0


def save_last_job_id(rows, path=None):
    numbers = [int(r["job_id"][1:]) for r in rows if re.fullmatch(r"J\d+", r["job_id"])]
    top = max(numbers + [last_job_number(path)])
    if top:
        Path(path or LAST_ID_FILE).write_text(f"J{top:04d}\n", encoding="utf-8")


def next_job_id(rows):
    numbers = [int(r["job_id"][1:]) for r in rows if re.fullmatch(r"J\d+", r["job_id"])]
    numbers.append(last_job_number())
    return f"J{max(numbers) + 1:04d}"


def covered_by(rows, row):
    """The first earlier line that already covers this Location and Channel, or None."""
    for other in rows:
        if other is row or other["job_id"] == row["job_id"]:
            continue
        if other["status"] in COVERED and same_scope(other, row):
            return other
    return None


def _cover_reason(other):
    when = other["ran_on"] or other["added_on"]
    return f"Already covered by {other['job_id']} ({other['status']}, {when})"


# ---- button actions ------------------------------------------------------

def add(rows, location, channels, languages="", wanted="", added_by="", on=None, default_wanted=60):
    """Add one job (one line per Channel). Returns (job_id, new lines, warnings)."""
    location = capitalise(location)
    if not re.search(r"[A-Za-z]", location):
        raise QueueError('Location is empty: type a country, region or city, country last, e.g. "Mumbai, India"')
    check_country(location)
    check_not_excluded(location)
    names = [" ".join(c.split()) for c in str(channels or "").split(",")]
    names = [c for c in names if c]
    if not names:
        raise QueueError('Channels is empty: type one or more, separated by commas, e.g. "distributors, retailers"')
    for name in names:
        if len(name) > 60:
            raise QueueError(f'Channel "{name[:40]}..." is too long: keep each Channel under 60 characters')
    wanted = str(wanted or "").strip() or str(default_wanted)
    if not wanted.isdigit() or not 1 <= int(wanted) <= 200:
        raise QueueError("Companies wanted per Channel must be a whole number from 1 to 200")

    job_id = next_job_id(rows)
    new, warnings, seen = [], [], set()
    for name in names:
        if norm_channel(name) in seen:
            warnings.append(f'"{name}" was typed twice in this job; it was added once.')
            continue
        seen.add(norm_channel(name))
        row = {c: "" for c in COLUMNS}
        row.update({
            "job_id": job_id, "location": location, "channel": name,
            "languages": " ".join(str(languages or "").split()), "companies_wanted": wanted,
            "added_by": added_by, "added_on": on or today(), "status": WAITING,
        })
        other = covered_by(rows + new, row)
        if other:
            row["status"] = ON_HOLD
            row["reason"] = _cover_reason(other)
            warnings.append(
                f'"{name}" in {location} is already covered by job {other["job_id"]}. '
                f'It is on hold until someone presses "Approve a repeat".'
            )
        new.append(row)
    rows.extend(new)
    return job_id, new, warnings


def split_locations(location):
    """Several cities typed in one box (20 Oct 2026): "Hamburg, Munich, Cologne, Germany" is one job
    per city: ["Hamburg, Germany", "Munich, Germany", "Cologne, Germany"]. Semicolons work as commas.
    One or two parts ("Germany", "Lyon, France") stay one job."""
    parts = tidy(str(location or "").replace(";", ",")).split(", ")
    parts = [p for p in parts if p]
    if len(parts) <= 2:
        return [", ".join(parts)]
    country = parts[-1]
    out, seen = [], set()
    for city in parts[:-1]:
        if city.lower() not in seen:
            seen.add(city.lower())
            out.append(f"{city}, {country}")
    return out


def add_many(rows, location, channels, languages="", wanted="", added_by="", on=None, default_wanted=60):
    """add() for every city typed in the Location box, one job each. All or nothing: if one city is
    refused (e.g. a misspelt country), no job is added. Returns [(job_id, new lines, warnings)]."""
    trial = list(rows)
    results = [add(trial, place, channels, languages, wanted, added_by, on, default_wanted)
               for place in split_locations(location)]
    rows[:] = trial
    return results


def _select(rows, job_id, channel=None):
    job_id = str(job_id or "").strip().upper()
    if not job_id:
        raise QueueError("Type the job ID, e.g. J0003 (it is in the first column of research/queue.csv)")
    found = [r for r in rows if r["job_id"] == job_id]
    if not found:
        raise QueueError(f"There is no job {job_id} in the queue")
    if channel and channel.strip():
        found = [r for r in found if norm_channel(r["channel"]) == norm_channel(channel)]
        if not found:
            raise QueueError(f'Job {job_id} has no Channel "{channel.strip()}"')
    return found


def _change(rows, job_id, channel, allowed, new_status, describe, **extra):
    chosen = _select(rows, job_id, channel)
    changed = [r for r in chosen if r["status"] in allowed]
    if not changed:
        states = ", ".join(sorted({r["status"] for r in chosen}))
        raise QueueError(f"Nothing to {describe}: the lines chosen are {states}")
    for r in changed:
        r["status"] = new_status
        r.update(extra)
    return changed


def cancel(rows, job_id, channel=None):
    return _change(rows, job_id, channel, (WAITING, ON_HOLD), CANCELLED, "cancel",
                   reason="Cancelled by a person")


def retry(rows, job_id, channel=None):
    """One more try. The earlier file stays recorded so the new run replaces it."""
    return _change(rows, job_id, channel, (FAILED,), WAITING, "retry", reason="Retry pressed")


def approve_repeat(rows, job_id, channel=None, by=""):
    return _change(rows, job_id, channel, (ON_HOLD,), WAITING, "approve",
                   reason="Repeat approved", approved_by=by or "someone")


# ---- used by the skill and the import job -------------------------------

def is_retry(row):
    """A Waiting line that has run before (it failed and is being tried again)."""
    return row["status"] == WAITING and bool(row["output_file"])


def waiting_job(rows, job_id=None, location=None):
    """The job to research: the one named, else a retry first, else the oldest with a Waiting
    line, markets added by hand before automatic ones (optionally only for one Location). Returns (job_id, its Waiting lines) or (None, [])."""
    waiting = [r for r in rows if r["status"] == WAITING]
    if job_id:
        job_id = job_id.strip().upper()
        waiting = [r for r in waiting if r["job_id"] == job_id]
    if location:
        waiting = [r for r in waiting if norm_location(r["location"]) == norm_location(location)]
    if not waiting:
        return None, []
    first = min(waiting, key=lambda r: (not is_retry(r), r["added_by"] == AUTO_BY, r["added_on"], r["job_id"]))
    return first["job_id"], [r for r in waiting if r["job_id"] == first["job_id"]]


def is_repeat_now(rows, row):
    """At run time: a Waiting line nobody approved, whose scope another job has since finished."""
    if row["approved_by"]:
        return None
    for other in rows:
        if (other["job_id"] != row["job_id"] and other["status"] in (DONE, DONE_FEWER)
                and same_scope(other, row)):
            return other
    return None


def record_failure(rows, job_id, channel, reason, ran_on="", output_file=""):
    """A Channel failed: back to Waiting for one automatic retry, else Failed.
    Returns the line, or None when it is not in the queue."""
    for r in rows:
        if r["job_id"] == job_id and norm_channel(r["channel"]) == norm_channel(channel):
            r["attempts"] = str(int(r["attempts"] or 0) + 1)
            again = int(r["attempts"]) <= AUTO_RETRIES
            r["status"] = WAITING if again else FAILED
            r["reason"] = (f"Failed once ({reason}); it runs again by itself at the next run" if again
                           else f"Failed again: {reason}")
            if ran_on:
                r["ran_on"] = ran_on
            if output_file:
                r["output_file"] = output_file
            return r
    return None


def set_status(rows, job_id, channel, status, reason="", ran_on="", output_file=""):
    """Record a result for one line. Returns the line, or None when it is not in the queue."""
    for r in rows:
        if r["job_id"] == job_id and norm_channel(r["channel"]) == norm_channel(channel):
            r["status"] = status
            r["reason"] = reason
            if ran_on:
                r["ran_on"] = ran_on
            if output_file:
                r["output_file"] = output_file
            return r
    return None


def markdown(rows, limit=30):
    """The newest lines as a table, for the run summary page."""
    head = "| Job | Location | Channel | Wanted | Status | Reason | Ran on |\n|---|---|---|---|---|---|---|\n"
    body = "".join(
        f"| {r['job_id']} | {r['location']} | {r['channel']} | {r['companies_wanted']} | "
        f"{r['status']} | {r['reason']} | {r['ran_on']} |\n"
        for r in rows[-limit:][::-1]
    )
    return head + (body or "| | The queue is empty | | | | | |\n")


def _summary(text):
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(description="Change the research queue")
    sub = p.add_subparsers(dest="action", required=True)
    a = sub.add_parser("add")
    a.add_argument("--location", required=True)
    a.add_argument("--channels", required=True)
    a.add_argument("--languages", default="")
    a.add_argument("--wanted", default="")
    a.add_argument("--by", default="")
    for name in ("cancel", "retry", "approve"):
        s = sub.add_parser(name)
        s.add_argument("--job", required=True)
        s.add_argument("--channel", default="")
        s.add_argument("--by", default="")
    sub.add_parser("show")
    args = p.parse_args(argv)

    rows = load()
    try:
        if args.action == "add":
            settings = load_research_settings()
            results = add_many(rows, args.location, args.channels, args.languages, args.wanted, args.by,
                               default_wanted=settings.get("default_companies", 60))
            lines = []
            for job_id, new, warnings in results:
                lines += [f"## Job {job_id} added", ""]
                lines += [f"- {r['channel']} in {r['location']}: **{r['status']}**" for r in new]
                if warnings:
                    lines += ["", "### Warnings", ""] + [f"- {w}" for w in warnings]
                lines.append("")
            _summary("\n".join(lines))
        elif args.action == "cancel":
            changed = cancel(rows, args.job, args.channel)
            _summary(f"Cancelled: {', '.join(r['channel'] for r in changed)} ({args.job.upper()})")
        elif args.action == "retry":
            changed = retry(rows, args.job, args.channel)
            _summary(f"Back to Waiting: {', '.join(r['channel'] for r in changed)} ({args.job.upper()})")
        elif args.action == "approve":
            changed = approve_repeat(rows, args.job, args.channel, args.by)
            _summary(f"Repeat approved, now Waiting: {', '.join(r['channel'] for r in changed)} "
                     f"({args.job.upper()})")
    except QueueError as err:
        _summary(f"ERROR: {err}")
        return 1
    if args.action != "show":
        save(rows)
        save_last_job_id(rows)
    _summary("\n## The queue (newest first)\n\n" + markdown(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
