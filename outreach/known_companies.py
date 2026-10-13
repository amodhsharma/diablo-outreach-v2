"""Button 2f: keep data/known_companies.csv, the list of every company already in HubSpot.

Research and the research import use it so a company already in HubSpot is never added again
(agreed 13 Oct 2026). The live account holds about 46,000 companies, more than HubSpot's search
can return (10,000), so:

  - the first run, a run on Sunday (India time) and a run after the account changed read every
    company with HubSpot's plain list (no limit; about 2 minutes);
  - every other run only asks for companies added or changed since the last run (seconds).
    Deleted or merged companies leave the list at the next full read.

Each row holds the company's record ID, name, cleaned website, country and why it is known:
"auto-outreach" (Lead Source AUTO-OUTREACH), "customer" (Lifecycle Stage Customer) or "other".
No people's names or emails are saved. Reading only: this job never changes HubSpot.

Usage:
    python -m outreach.known_companies --target test
    python -m outreach.known_companies --target test --full
"""

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys

from .common import KNOWN_FILE, PipelineError, check_target, clean_domain
from .hubspot_client import HubSpot, HubSpotError
from .schema import TAG, TAG_PROPERTY

COLUMNS = ["id", "name", "domain", "country", "why"]
STATE_FILE = KNOWN_FILE.with_name("known_companies_state.json")
PROPS = ["name", "domain", "website", "country", "lifecyclestage", TAG_PROPERTY]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
# A changes-only read bigger than this falls back to a full read (HubSpot's search stops at 10,000).
MAX_CHANGES = 9000

# Words left out when comparing company names ("Noble Foods Ltd" = "noble foods").
_SUFFIXES = {"ltd", "limited", "llc", "inc", "plc", "pvt", "private", "co", "company", "gmbh", "sa",
             "srl", "sro", "bv", "ag", "llp", "corp", "corporation", "pte", "fze", "fzco", "fzc",
             "spa", "sl", "the", "and", "kg", "nv", "ab", "oy", "aps", "sas", "sarl", "doo", "kft",
             "ltda", "eirl", "sac", "spzoo", "gmbhcokg", "bvba", "sprl", "as"}


def norm_name(name):
    """Company name for matching: lower case, no punctuation or legal endings
    ("WM MORRISON SUPERMARKETS P L C" -> "wm morrison supermarkets",
    "Kilargo Sp. z o.o." -> "kilargo")."""
    text = str(name or "").lower().replace("&", " and ")
    text = re.sub(r"\bsp\.?\s*z\.?\s*o\.?\s*o\.?", " spzoo ", text)
    words = re.findall(r"[a-z0-9]+", text)
    joined = []  # spaced-out initials become one word: "p l c" -> "plc", "b v" -> "bv"
    for w in words:
        if len(w) == 1 and w.isalpha() and joined and joined[-1][1]:
            joined[-1] = (joined[-1][0] + w, True)
        else:
            joined.append((w, len(w) == 1 and w.isalpha()))
    words = [w for w, _ in joined]
    kept = [w for w in words if w not in _SUFFIXES]
    return " ".join(kept or words)


def why_of(p):
    if str(p.get(TAG_PROPERTY) or "").strip() == TAG:
        return "auto-outreach"
    if (p.get("lifecyclestage") or "") == "customer":
        return "customer"
    return "other"


def row_of(rec):
    p = rec.get("properties", {})
    return {
        "id": str(rec["id"]),
        "name": (p.get("name") or "").strip(),
        "domain": clean_domain(p.get("domain")) or clean_domain(p.get("website")) or "",
        "country": (p.get("country") or "").strip(),
        "why": why_of(p),
    }


def load(path=None):
    path = path or KNOWN_FILE
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return {r["id"]: r for r in rows if r.get("id")}


def save(rows, path=None):
    path = path or KNOWN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["name"].lower(), r["domain"], r["id"]))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(ordered)


def load_state(path=None):
    try:
        return json.loads((path or STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state, path=None):
    (path or STATE_FILE).write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def needs_full(state, portal, now, force=False):
    if force or not state or str(state.get("portal")) != str(portal) or not state.get("last_run"):
        return True
    today = now.astimezone(IST).date()
    if today.weekday() == 6 and state.get("last_full") != today.isoformat():
        return True  # Sunday, India time
    last_full = state.get("last_full") or "2000-01-01"
    return (today - dt.date.fromisoformat(last_full)).days >= 7


def changed_since(hs, since):
    """Companies added or changed since `since` (a datetime), oldest first."""
    ms = str(int(since.timestamp() * 1000))
    return hs.search("companies", [{"propertyName": "hs_lastmodifieddate", "operator": "GTE", "value": ms}],
                     PROPS, max_results=MAX_CHANGES + 1,
                     sorts=[{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}])


def run(target, hs, path=None, state_path=None, log=print, force_full=False, now=None):
    portal = check_target(hs, target)
    now = now or dt.datetime.now(dt.timezone.utc)
    state = load_state(state_path)
    rows = load(path)
    full = needs_full(state, portal, now, force_full)
    if not full:
        # Read from a few minutes before the last run, so nothing saved at that moment is missed.
        since = dt.datetime.fromisoformat(state["last_run"]) - dt.timedelta(minutes=10)
        changes = changed_since(hs, since)
        if len(changes) > MAX_CHANGES:
            log(f"More than {MAX_CHANGES} companies changed since the last run; reading them all instead")
            full = True
        else:
            for rec in changes:
                row = row_of(rec)
                if row["name"] or row["domain"]:
                    rows[row["id"]] = row
            log(f"{len(changes)} companies added or changed since the last run")
    if full:
        rows = {}
        for rec in hs.list_all("companies", PROPS):
            row = row_of(rec)
            if row["name"] or row["domain"]:
                rows[row["id"]] = row
        state["last_full"] = now.astimezone(IST).date().isoformat()
        log(f"Read every company in HubSpot: {len(rows)}")
    state.update(portal=str(portal), last_run=now.replace(microsecond=0).isoformat())
    save(rows, path)
    save_state(state, state_path)
    log(f"data/known_companies.csv now lists {len(rows)} companies")
    return rows


# ---- matching, used by research and the research import ----------------------------------

def country_key(country):
    """"UK", "England" and "United Kingdom" are the same country."""
    from .countries import find
    text = (country or "").strip()
    return (find(text) or text).lower() if text else ""


def index(rows):
    """{"domains": set, "names": {country: set of cleaned names}} for fast matching."""
    domains, names = set(), {}
    for r in rows:
        if r.get("domain"):
            domains.add(r["domain"].lower())
        n = norm_name(r.get("name"))
        if n:
            names.setdefault(country_key(r.get("country")), set()).add(n)
    return {"domains": domains, "names": names}


def load_index(path=None):
    return index(load(path).values())


def matches(idx, domain, name, country):
    """True when a company is already known: the same website anywhere, or the same cleaned
    name in the same country (or a known company with no country)."""
    d = clean_domain(domain)
    if d and d in idx["domains"]:
        return True
    n = norm_name(name)
    if not n:
        return False
    return n in idx["names"].get(country_key(country), set()) or n in idx["names"].get("", set())


def main(argv=None):
    p = argparse.ArgumentParser(description="Save the list of companies already in HubSpot")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--full", action="store_true", help="read every company, not just the changes")
    p.add_argument("--skip-if-not-configured", action="store_true")
    args = p.parse_args(argv)
    if args.skip_if_not_configured and not os.environ.get("HUBSPOT_TOKEN"):
        print("The HubSpot key is not added yet; skipping.")
        return 0
    try:
        run(args.target, HubSpot(), force_full=args.full)
    except (PipelineError, HubSpotError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
