"""Shared helpers: settings, domain clean-up, run folders and target checks."""

import datetime as dt
import json
import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"  # each job saves its files here
# Research details used to write the emails (what a company distributes, who it supplies,
# better for you brands carried, why it fits). Kept in the repository, not in HubSpot.
# The import job adds to it and saves it back; the email writing skill will read it.
NOTES_FILE = ROOT / "data" / "company_notes.json"
# The research queue: one line per Location and Channel, kept forever.
RESEARCH_DIR = ROOT / "research"
QUEUE_FILE = RESEARCH_DIR / "queue.csv"
# Companies already in HubSpot, saved every night for the research exclusion list.
KNOWN_FILE = ROOT / "data" / "known_companies.csv"

# The live Diablo Sugar Free HubSpot account.
PRODUCTION_PORTAL_ID = 147671704


class PipelineError(RuntimeError):
    """A problem the person running the job needs to fix."""


def load_settings(path=None):
    path = Path(path or ROOT / "config" / "settings.yaml")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_exclusions(path=None):
    path = Path(path or ROOT / "config" / "exclude.txt")
    if not path.exists():
        return []
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise PipelineError(
            f"{name} is not set. Add it in GitHub: Settings > Secrets and variables > Actions."
        )
    return value


_NO_DOMAIN = {"", "no domain", "none", "null", "n/a", "na", "unknown", "-"}


def clean_domain(value):
    """Return a bare domain like example.com, or None if there is no usable domain."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in _NO_DOMAIN:
        return None
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/")[0].split("?")[0].split("#")[0].split(":")[0]
    text = re.sub(r"^www\d*\.", "", text)
    text = text.strip(". ")
    if "." not in text or " " in text:
        return None
    # Directory pages are not the company's own site.
    directories = (
        "indiamart.com", "tradeindia.com", "justdial.com", "linkedin.com",
        "facebook.com", "instagram.com", "volza.com", "importgenius.com",
        "zaubacorp.com", "tofler.in", "exportersindia.com", "google.com",
    )
    if any(text == d or text.endswith("." + d) for d in directories):
        return None
    return text


def country_of(market):
    """The country part of a market: the text after the last comma ("Mumbai, India" -> "India")."""
    return str(market).split(",")[-1].strip()


def market_matches(rule_market, market):
    """True if a settings entry such as "India" or "Mumbai" applies to a market such as
    "Mumbai, India". Matches whole comma-separated parts, ignoring case."""
    wanted = [p.strip().lower() for p in str(rule_market).split(",") if p.strip()]
    parts = [p.strip().lower() for p in str(market).split(",") if p.strip()]
    return bool(wanted) and all(w in parts for w in wanted)


def slug(text, limit=60):
    out = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return out[:limit] or "unnamed"


def enum_value(label):
    """HubSpot dropdown value for a display label (matches schema.py)."""
    return re.sub(r"[^a-z0-9]+", "_", str(label).lower()).strip("_")


def clean_category(text):
    """Tidy a typed channel category: single spaces and a capital first letter.
    "  sugar free   distributor " -> "Sugar free distributor". Capitals elsewhere are
    kept (OTC stays OTC) and do not matter for matching: "Sugar Free Distributor"
    and "sugar free distributor" are the same HubSpot dropdown option."""
    label = " ".join(str(text or "").split())
    if not re.search(r"[A-Za-z]", label):
        raise PipelineError(
            'channel category is empty: type one, e.g. "Sugar free distributor"'
        )
    if len(label) > 60:
        raise PipelineError("channel category is too long: keep it under 60 characters")
    return label[0].upper() + label[1:]


def category_label(value, labels=None):
    """Display label for a stored category value, using HubSpot's dropdown labels when known."""
    if not value:
        return ""
    if labels and value in labels:
        return labels[value]
    text = value.replace("_", " ")
    return text[0].upper() + text[1:]


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def run_dir(job, label=""):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{job}" + (f"-{slug(label, 40)}" if label else "")
    path = RUNS_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def check_target(hs, target):
    """Stop if the HubSpot key does not belong to the account the person chose."""
    if target not in ("test", "live"):
        raise PipelineError("target must be test or live")
    portal = hs.portal_id()
    if target == "test" and portal == PRODUCTION_PORTAL_ID:
        raise PipelineError(
            "You chose the test account but this key belongs to the LIVE Diablo account. Stopping."
        )
    if target == "live" and portal != PRODUCTION_PORTAL_ID:
        raise PipelineError(
            f"You chose the live account but this key belongs to account {portal}. Stopping."
        )
    return portal


def load_company_notes():
    """{domain: {name, market, category, fit_rationale, distributes, channels_supplied,
    sf_brands_carried, added}} from data/company_notes.json."""
    path = Path(NOTES_FILE)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_company_notes(new_notes):
    """Add or update entries in data/company_notes.json (sorted, one company per key)."""
    if not new_notes:
        return
    notes = load_company_notes()
    notes.update(new_notes)
    path = Path(NOTES_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(notes.items())), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
