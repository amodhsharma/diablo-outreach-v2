"""The strict check for outreachResearch output. Standard library only.

Two kinds of file are checked:
  part   one helper's file for one Channel (work/channel_N.json)
  final  the merged file saved to research/<date>/ (and, optionally, its report)

Usage:
    python3 check_output.py part work/channel_1.json
    python3 check_output.py final research/2026-10-09/J0001_mumbai-india_retailers.json \
        --report research/2026-10-09/J0001_mumbai-india_retailers_report.md \
        --exclusions work/exclusions.txt

Prints PASSED, or FAILED with one plain line per problem. Exit code 0 or 1.
The GitHub import job runs the same checks before anything reaches HubSpot.
"""

import argparse
import json
import re
import sys
from pathlib import Path

FORMAT = "outreachResearch v1"

# The fields every company must have in a helper's file, in this order.
PART_COMPANY_KEYS = [
    "name", "domain", "tier", "tier_rank", "distributes", "channels_supplied",
    "sf_brands_carried", "competing_brand_flag", "fit_rationale", "confidence", "source_urls",
]
# The final file adds channel_category: 12 fields per company.
FINAL_COMPANY_KEYS = [
    "name", "domain", "channel_category", "tier", "tier_rank", "distributes", "channels_supplied",
    "sf_brands_carried", "competing_brand_flag", "fit_rationale", "confidence", "source_urls",
]
PART_KEYS = ["channel", "searches_used", "tier_logic", "checked_and_excluded", "shortfall_note", "companies"]
FINAL_KEYS = ["format", "job_id", "location", "run_date", "run_type", "channels", "companies"]
CHANNEL_KEYS = ["channel", "template", "status", "reason", "companies_wanted", "companies_found",
                "searches_used"]
CHANNEL_STATUSES = ("done", "failed", "on_hold")

# How each field is named to people (in error messages and the report).
LABELS = {
    "name": "Company name",
    "domain": "Domain of the found company",
    "channel_category": "Channel",
    "tier": "Tier",
    "tier_rank": "Rank within the tier",
    "distributes": "What they distribute",
    "channels_supplied": "Retailers or channels they supply",
    "sf_brands_carried": "Sugar free brands carried",
    "competing_brand_flag": "Carries a direct competitor",
    "fit_rationale": "Why they fit Diablo",
    "confidence": "Confidence",
    "source_urls": "Found the company from",
}

NO_DOMAIN = "no domain"
_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+\d{1,3}[\s.-]?\(?\d[\d\s().-]{6,}\d")
_DASHES = ("—", "–")

# Pages that are never a company's own website.
DIRECTORY_SITES = (
    "indiamart.com", "tradeindia.com", "justdial.com", "linkedin.com", "facebook.com",
    "instagram.com", "volza.com", "importgenius.com", "zaubacorp.com", "tofler.in",
    "exportersindia.com", "google.com", "amazon.com", "amazon.co.uk", "amazon.in",
    "amazon.de", "amazon.ae", "temu.com", "noon.com", "flipkart.com", "ebay.com",
    "ebay.co.uk", "alibaba.com", "yelp.com", "yellowpages.com", "x.com", "twitter.com",
    "youtube.com", "tiktok.com", "wikipedia.org", "crunchbase.com", "bloomberg.com",
    "dnb.com", "opencorporates.com", "companieshouse.gov.uk",
)


# ---- helpers shared with prepare_run.py and finalise.py ----------------------

def clean_domain(value):
    """A bare domain like abc.com, or "no domain". Strips https://, www. and page paths.
    A directory, marketplace or social page is not the company's own site: "no domain"."""
    if value is None:
        return NO_DOMAIN
    text = str(value).strip().lower()
    if text in ("", NO_DOMAIN, "none", "null", "n/a", "na", "unknown", "-"):
        return NO_DOMAIN
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/")[0].split("?")[0].split("#")[0].split(":")[0]
    text = re.sub(r"^www\d*\.", "", text).strip(". ")
    if not _DOMAIN.match(text):
        return NO_DOMAIN
    if any(text == d or text.endswith("." + d) for d in DIRECTORY_SITES):
        return NO_DOMAIN
    return text


_SUFFIXES = {"ltd", "limited", "llc", "inc", "plc", "pvt", "private", "co", "company", "gmbh",
             "sa", "srl", "sro", "bv", "ag", "llp", "corp", "corporation", "pte", "fze", "fzco",
             "fzc", "spa", "sl", "the", "and"}


def norm_name(name):
    """Company name for matching: lower case, no punctuation or legal suffixes."""
    words = re.findall(r"[a-z0-9]+", str(name or "").lower().replace("&", " and "))
    kept = [w for w in words if w not in _SUFFIXES]
    return " ".join(kept or words)


def load_exclusions(path):
    """Names and domains from an exclusions file: one per line, "- Name (domain)" or plain."""
    names, domains = set(), set()
    if not path or not Path(path).exists():
        return names, domains
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("-").strip()
        if not line or line.startswith("#") or line.lower() == "none":
            continue
        match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", line)
        name, domain = (match.group(1), match.group(2)) if match else (line, "")
        if clean_domain(name) != NO_DOMAIN and " " not in name.strip():
            domains.add(clean_domain(name))
        else:
            names.add(norm_name(name))
        if domain and clean_domain(domain) != NO_DOMAIN:
            domains.add(clean_domain(domain))
    names.discard("")
    return names, domains


# ---- the checks -------------------------------------------------------------

def _is_text(value):
    return value is None or isinstance(value, str)


def _keys(errors, where, obj, wanted):
    if not isinstance(obj, dict):
        errors.append(f"{where}: must be an object with the agreed fields")
        return False
    missing = [k for k in wanted if k not in obj]
    extra = [k for k in obj if k not in wanted]
    if missing:
        errors.append(f"{where}: missing field(s): {', '.join(missing)}")
    if extra:
        errors.append(f"{where}: field(s) that are not allowed: {', '.join(extra)}")
    return not missing


def _people(errors, where, obj):
    for key, value in obj.items():
        values = value if isinstance(value, list) else [value]
        for v in values:
            if not isinstance(v, str):
                continue
            if key != "source_urls" and _EMAIL.search(v):
                errors.append(f"{where}: {LABELS.get(key, key)} contains an email address; "
                              "no people, emails or phone numbers are allowed")
            if key != "source_urls" and _PHONE.search(v):
                errors.append(f"{where}: {LABELS.get(key, key)} looks like it contains a phone number; "
                              "no people, emails or phone numbers are allowed")
            if any(d in v for d in _DASHES):
                errors.append(f"{where}: {LABELS.get(key, key)} contains an em or en dash; use a "
                              "comma, full stop or hyphen")


def check_company(errors, where, c, keys, channels=None):
    if not _keys(errors, where, c, keys):
        return
    name = c["name"]
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{where}: Company name is empty")
        return
    where = f'Company "{name.strip()}"'
    domain = c["domain"]
    if not isinstance(domain, str) or (domain != NO_DOMAIN and not _DOMAIN.match(domain)):
        errors.append(f'{where}: Domain of the found company must be written like abc.com, or "no domain" '
                      f'(found "{domain}")')
    elif domain != NO_DOMAIN and clean_domain(domain) == NO_DOMAIN:
        errors.append(f'{where}: Domain of the found company "{domain}" is a directory, marketplace or '
                      'social page, not the company\'s own site; write "no domain"')
    if not isinstance(c["tier"], int) or isinstance(c["tier"], bool) or c["tier"] not in (1, 2, 3):
        errors.append(f"{where}: Tier must be 1, 2 or 3 (found {c['tier']!r})")
    if not isinstance(c["tier_rank"], int) or isinstance(c["tier_rank"], bool) or c["tier_rank"] < 1:
        errors.append(f"{where}: Rank within the tier must be a whole number from 1 (found {c['tier_rank']!r})")
    if c["confidence"] not in ("high", "medium", "low"):
        errors.append(f"{where}: Confidence must be high, medium or low (found {c['confidence']!r})")
    for key in ("distributes", "channels_supplied", "sf_brands_carried", "fit_rationale"):
        if not _is_text(c[key]):
            errors.append(f"{where}: {LABELS[key]} must be text or null")
    if not (c["fit_rationale"] or "").strip():
        errors.append(f"{where}: Why they fit Diablo is empty")
    if c["competing_brand_flag"] not in (True, False, None):
        errors.append(f"{where}: Carries a direct competitor must be true, false or null")
    urls = c["source_urls"]
    if (not isinstance(urls, list) or not urls
            or not all(isinstance(u, str) and re.match(r"^https?://\S+\.\S+", u.strip()) for u in urls)):
        errors.append(f"{where}: Found the company from must list at least one web link (https://...)")
    if "channel_category" in keys:
        cats = c["channel_category"]
        if not isinstance(cats, list) or not cats or not all(isinstance(x, str) and x.strip() for x in cats):
            errors.append(f"{where}: Channel must list at least one Channel")
        elif channels is not None:
            unknown = [x for x in cats if x not in channels]
            if unknown:
                errors.append(f"{where}: Channel {', '.join(unknown)} is not one of this job's researched Channels")
    _people(errors, where, c)


def _duplicates(errors, companies):
    by_domain, by_name = {}, {}
    for c in companies:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str):
            continue
        d = c.get("domain")
        if isinstance(d, str) and d != NO_DOMAIN:
            if d in by_domain:
                errors.append(f'Company "{c["name"]}" appears twice (same Domain of the found company as '
                              f'"{by_domain[d]}")')
            by_domain[d] = c["name"]
        n = norm_name(c["name"])
        if n in by_name:
            errors.append(f'Company "{c["name"]}" appears twice (same name as "{by_name[n]}")')
        by_name[n] = c["name"]


def _excluded(errors, companies, exclusions):
    names, domains = exclusions
    for c in companies:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str):
            continue
        if norm_name(c["name"]) in names or (c.get("domain") in domains):
            errors.append(f'Company "{c["name"]}" is on the exclusion list (already known or already in HubSpot)')


def _ranks(errors, companies, group_key):
    seen = {}
    for c in companies:
        if not isinstance(c, dict):
            continue
        key = (group_key(c), c.get("tier"), c.get("tier_rank"))
        if key in seen:
            errors.append(f'Company "{c.get("name")}" has the same Tier and Rank as "{seen[key]}"')
        seen[key] = c.get("name")


def check_part(data, exclusions=(set(), set())):
    errors = []
    if not _keys(errors, "The file", data, PART_KEYS):
        return errors
    if not isinstance(data["channel"], str) or not data["channel"].strip():
        errors.append("The file: channel is empty")
    if not isinstance(data["searches_used"], int) or data["searches_used"] < 0:
        errors.append("The file: searches_used must be a whole number")
    if not isinstance(data["tier_logic"], str) or not data["tier_logic"].strip():
        errors.append("The file: tier_logic (two or three sentences on how the tiers were cut) is empty")
    if not _is_text(data["shortfall_note"]):
        errors.append("The file: shortfall_note must be text or null")
    excluded = data["checked_and_excluded"]
    if not isinstance(excluded, list) or not all(
            isinstance(x, dict) and set(x) == {"name", "reason"} for x in excluded):
        errors.append('The file: checked_and_excluded must be a list of {"name": ..., "reason": ...}')
    companies = data["companies"]
    if not isinstance(companies, list):
        errors.append("The file: companies must be a list")
        return errors
    for i, c in enumerate(companies, 1):
        check_company(errors, f"Company {i}", c, PART_COMPANY_KEYS)
    _duplicates(errors, companies)
    _excluded(errors, companies, exclusions)
    _ranks(errors, companies, lambda c: "")
    return errors


def report_rows(text):
    """Company rows in the report's company lists (between the two markers)."""
    if "<!-- companies:start -->" not in text or "<!-- companies:end -->" not in text:
        return None
    block = text.split("<!-- companies:start -->", 1)[1].split("<!-- companies:end -->", 1)[0]
    return [ln for ln in block.splitlines() if re.match(r"^\|\s*\d+\s*\|", ln)]


def check_report(errors, text, companies):
    rows = report_rows(text)
    if rows is None:
        errors.append("Report: the company lists are missing")
        return
    if len(rows) != len(companies):
        errors.append(f"Report: the company lists show {len(rows)} companies but the JSON has {len(companies)}")
    if "{{" in text:
        errors.append("Report: a section was not filled in (a {{...}} placeholder is left)")
    match = re.search(r"## Market structure\s*\n(.*?)(?=\n## )", text, re.S)
    if not match:
        errors.append("Report: the Market structure section is missing")
    else:
        body = re.sub(r"(?m)^Sources?:.*$", "", match.group(1))
        words = len(re.findall(r"[A-Za-z0-9'%£$€-]+", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)))
        if words > 200:
            errors.append(f"Report: Market structure is {words} words; the limit is 200")
    for section in ("## Barriers to entry", "## Closing analysis"):
        if section not in text:
            errors.append(f"Report: the {section[3:]} section is missing")
    if any(d in text for d in _DASHES):
        errors.append("Report: contains an em or en dash; use a comma, full stop or hyphen")


def check_final(data, report_text=None, exclusions=(set(), set())):
    errors = []
    if not _keys(errors, "The file", data, FINAL_KEYS):
        return errors
    if data["format"] != FORMAT:
        errors.append(f'The file: format must be "{FORMAT}"')
    if not isinstance(data["job_id"], str) or not re.fullmatch(r"J\d{4,}", data["job_id"]):
        errors.append("The file: job_id must look like J0001")
    if not isinstance(data["location"], str) or not data["location"].strip():
        errors.append("The file: location is empty")
    if not isinstance(data["run_date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["run_date"]):
        errors.append("The file: run_date must be a date like 2026-10-09")
    if data["run_type"] not in ("scheduled", "manual"):
        errors.append("The file: run_type must be scheduled or manual")
    channels = data["channels"]
    done = []
    if not isinstance(channels, list) or not channels:
        errors.append("The file: channels must list at least one Channel")
        channels = []
    for i, ch in enumerate(channels, 1):
        if not _keys(errors, f"Channel {i}", ch, CHANNEL_KEYS):
            continue
        if ch["status"] not in CHANNEL_STATUSES:
            errors.append(f'Channel "{ch["channel"]}": status must be done, failed or on_hold')
        if ch["status"] in ("failed", "on_hold") and not (ch["reason"] or "").strip():
            errors.append(f'Channel "{ch["channel"]}": a {ch["status"]} Channel needs a reason')
        if ch["status"] == "done":
            done.append(ch["channel"])
    companies = data["companies"]
    if not isinstance(companies, list):
        errors.append("The file: companies must be a list")
        return errors
    for i, c in enumerate(companies, 1):
        check_company(errors, f"Company {i}", c, FINAL_COMPANY_KEYS, channels=done)
    _duplicates(errors, companies)
    _excluded(errors, companies, exclusions)
    _ranks(errors, companies, lambda c: (c.get("channel_category") or [""])[0])
    for ch in channels:
        if isinstance(ch, dict) and ch.get("status") == "done":
            found = sum(1 for c in companies if isinstance(c, dict)
                        and ch["channel"] in (c.get("channel_category") or []))
            if ch.get("companies_found") != found:
                errors.append(f'Channel "{ch["channel"]}": companies_found says {ch.get("companies_found")} '
                              f"but {found} companies list it")
    if report_text is not None:
        check_report(errors, report_text, companies)
    return errors


def main(argv=None):
    p = argparse.ArgumentParser(description="Strict check for outreachResearch output")
    p.add_argument("kind", choices=["part", "final"])
    p.add_argument("file")
    p.add_argument("--report", default="")
    p.add_argument("--exclusions", default="")
    args = p.parse_args(argv)
    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        print(f"FAILED\n- The file could not be read as JSON: {err}")
        return 1
    exclusions = load_exclusions(args.exclusions)
    if args.kind == "part":
        errors = check_part(data, exclusions)
    else:
        report = Path(args.report).read_text(encoding="utf-8") if args.report else None
        errors = check_final(data, report, exclusions)
    if errors:
        print("FAILED")
        for e in errors[:60]:
            print(f"- {e}")
        if len(errors) > 60:
            print(f"- ...and {len(errors) - 60} more")
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
