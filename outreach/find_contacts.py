"""Job 3: find contacts at approved companies with Apollo and add them to HubSpot.

Only AUTO-OUTREACH companies whose Lead Status is "GATE1: Approved for outreach" are processed (gate 1),
and only those with no contacts yet. For each company it looks at everyone Apollo holds there,
ranks them by seniority (settings: contacts.hierarchy) and keeps up to contacts.per_company
verified emails, most senior first. Each contact is created with Lead Source AUTO-OUTREACH,
Lead Status "New" and an Outreach order (1 = most senior). A company where nobody usable is
found becomes "Missing Info". An email already anywhere in HubSpot is never added again.

When Apollo has nobody usable (from 19 Oct 2026, contacts.company_inbox_fallback), the contact
address on the company's own website is added instead, as one contact with the job title
"Company inbox (from website)" (see company_inbox.py); only when that is missing too does the
company become "Missing Info". When that address uses the company's other domain (19 Oct 2026,
e.g. info@cofi.fr on comptoir-produits-italiens.fr), Apollo is searched there too first.

Apollo charges for each email revealed. Every person revealed is remembered in GitHub
(data/apollo_kept.json and data/apollo_skipped.json, by Apollo's person ID), so nobody is ever
paid for twice. Apollo IDs are not stored in HubSpot.
Usage:
    python -m outreach.find_contacts --target test
"""

import argparse
from pathlib import Path
import os
import re
import sys

from . import apollo_status, company_inbox
from .job_owner import fill_owners, is_job_company, job_notes, job_owner
from .apollo_client import Apollo, ApolloError
from .assign import Assigner
import json

from .common import (
    ROOT, PipelineError, channel_of, check_target, clean_domain, load_company_notes, load_settings, market_of,
    run_dir, write_json,
)
from .hubspot_client import HubSpot, HubSpotError
from .schema import CONTACT_SOURCE, INBOX_TITLE, LEAD_STATUS, ORDER, SOURCE_APOLLO, SOURCE_WEBSITE
from .stages import LeadStatus

COMPANY_PROPS = ["name", "domain", "city", "country", "industry_type", LEAD_STATUS, "hubspot_owner_id"]


def titles_for(category, titles):
    """Job titles for a category (any capitalisation), else the "default" list."""
    by_lower = {k.lower(): v for k, v in titles.items()}
    return by_lower.get((category or "").lower()) or by_lower.get("default") or next(iter(titles.values()))


# Apollo seniority values used for the extra "senior people" search. Large companies
# have more people than one page of results; this makes sure the top people are seen.
SENIOR_SENIORITIES = ["owner", "founder", "c_suite", "partner", "vp", "head", "director"]


def _matches(word, title):
    return re.search(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"(?![a-z0-9])", title) is not None


def hierarchy_level(title, hierarchy):
    """(level number, level name) for a job title. The level whose words match the title
    best wins (longest matching words), so "Assistant Director" is not read as "Director".
    Titles matching no level get the number after the last level."""
    title = (title or "").lower()
    best, best_len = None, 1
    for i, level in enumerate(hierarchy):
        for word in level.get("words", []):
            # ">=" so a tie goes to the less senior level ("Channel Partner Manager").
            if len(word) >= best_len and _matches(word, title):
                best, best_len = i, len(word)
    if best is None:
        return len(hierarchy), "Everyone else"
    return best, hierarchy[best].get("level", f"Level {best + 1}")


def rank_people(people, hierarchy, buying_titles, exclude_words=(), include_everyone_else=True):
    """Most senior first. Within a level, buying roles (the category's job titles) first.
    Drops excluded titles, and titles matching no level unless include_everyone_else."""
    buying = [t.lower() for t in buying_titles]
    ranked = []
    for order, person in enumerate(people):
        title = (person.get("title") or "").lower()
        if any(_matches(w, title) for w in exclude_words):
            continue
        level, name = hierarchy_level(title, hierarchy)
        if level == len(hierarchy) and not include_everyone_else:
            continue
        pref = next((i for i, t in enumerate(buying) if t in title), len(buying))
        ranked.append(((level, pref, order), dict(person, _level=name)))
    return [p for _, p in sorted(ranked, key=lambda x: x[0])]


def find_people(apollo, domain, seniorities=None, per_page=100):
    """Everyone Apollo holds at the company (free searches). A second search for senior
    people only makes sure the top people are included at large companies."""
    seen, people = set(), []
    for batch in (apollo.search_people(domain, [], SENIOR_SENIORITIES, per_page=per_page),
                  apollo.search_people(domain, [], seniorities or None, per_page=per_page)):
        for person in batch:
            if person.get("id") and person["id"] not in seen:
                seen.add(person["id"])
                people.append(person)
    return people


# People whose email was revealed (and paid for) but not kept, e.g. unverified: never revealed again.
SKIPPED_FILE = ROOT / "data" / "apollo_skipped.json"
# People whose email was revealed and kept as a HubSpot contact: never revealed again either.
KEPT_FILE = ROOT / "data" / "apollo_kept.json"


def load_skipped(path=None):
    path = path or SKIPPED_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def new_contacts_file():
    """runs/new_contacts.json: the contacts this run added, read by step 3 of button 3."""
    from . import common
    return Path(common.RUNS_DIR) / "new_contacts.json"


def save_skipped(skipped, path=None):
    path = path or SKIPPED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(skipped.items())), indent=1) + "\n", encoding="utf-8")


def run(target, settings, hs, apollo, log=print):
    check_target(hs, target)
    cfg = settings["contacts"]
    statuses = LeadStatus(hs)
    assigner = Assigner(hs, settings, log)
    out_dir = run_dir("contacts")
    try:  # 23 Oct 2026: every AUTO-OUTREACH contact carries its company's Country; never stops the run
        fill_contact_places(hs, log)
    except Exception as err:
        log(f"Could not fill in the contacts' Country: {str(err)[:200]}")
    try:  # 23 Oct 2026: AUTO-OUTREACH companies and contacts with no owner get the job owner
        fill_owners(hs, job_owner(settings), log)
    except Exception as err:
        log(f"Could not give the job owner to records with no owner: {str(err)[:200]}")
    cfg = dict(cfg, _job_owner=job_owner(settings), _job_notes=job_notes())
    approved = hs.tagged_search("companies", [statuses.filter("companies", "approved")],
                                COMPANY_PROPS + [apollo_status.STOP_REASON],
                                max_results=cfg["companies_per_run"] * 3)
    # Companies that already have their contacts wait for gate 2 and their emails, not for Apollo.
    # Only AUTO-OUTREACH contacts count (HubSpot may link a team contact by itself).
    links = hs.associated_ids("companies", "contacts", [c["id"] for c in approved]) if approved else {}
    linked = sorted({x for xs in links.values() for x in xs})
    ours = {str(r["id"]) for r in hs.tagged_read("contacts", linked, ["email"])} if linked else set()
    companies = [c for c in approved if not ours & set(links.get(str(c["id"])) or [])][:cfg["companies_per_run"]]
    log(f"{len(companies)} approved companies to process")
    notes = load_company_notes()
    skipped = load_skipped()
    kept = load_skipped(KEPT_FILE)
    before = (len(skipped), len(kept))

    credits, log_rows = 0, []
    # "Outreach contact source" exists only once button 1 has run after 19 Oct 2026; until then the
    # contacts are created without it (company inboxes are still recognised by their job title).
    cfg = dict(cfg, _source_field=bool(companies) and _has_field(hs, CONTACT_SOURCE))
    try:
        credits = _process(companies, hs, apollo, cfg, statuses, assigner, notes, skipped, kept, log_rows, log)
    finally:  # whatever happens, never lose the record of who was already paid for
        if len(skipped) != before[0]:
            save_skipped(skipped)
        if len(kept) != before[1]:
            save_skipped(kept, KEPT_FILE)
    try:  # 23 Oct 2026: "Missing info on Apollo" companies; never stops the run
        apollo_status.tidy(hs, statuses, log)
        summary_apollo = apollo_status.recheck(hs, apollo, statuses, log)
    except Exception as err:
        summary_apollo = {}
        log(f'Could not check the "Missing info on Apollo" companies again: {str(err)[:200]}')
    summary = {"companies": len(log_rows), "apollo_credits_used": credits, "rows": log_rows,
               "missing_info_on_apollo": summary_apollo}
    write_json(out_dir / "summary.json", summary)
    # The contacts just added, for step 3 of button 3 (agreed 15 Oct 2026): HubSpot's search can
    # take a minute to show new records, so the list of who needs lines adds these by their ID.
    new_ids = [i for r in log_rows for i in r.get("contact_ids", [])]
    new_contacts_file().parent.mkdir(parents=True, exist_ok=True)
    write_json(new_contacts_file(), {"contact_ids": new_ids})
    if new_ids:
        log(f"{len(new_ids)} new contacts handed to step 3, so they get their lines in this run")
    log(f"Apollo credits used (approx.): {credits}")
    return summary


def _has_field(hs, name):
    check = getattr(hs, "has_property", None)
    try:
        return bool(check("contacts", name)) if check else False
    except Exception:
        return False


def _mask(email):
    name, _, domain = (email or "").partition("@")
    return f"{name[:1]}***@{domain}" if domain else "(no email)"


NOT_LOOKED = object()


def place_of(company_props):
    """The company's Country and City for its contacts (23 Oct 2026, Ariel: contacts had no country)."""
    out = {}
    for key in ("country", "city"):
        value = (company_props.get(key) or "").strip()
        if value:
            out[key] = value
    return out


def fill_contact_places(hs, log=print, limit=2000):
    """AUTO-OUTREACH contacts with no Country get their company's Country and City (23 Oct 2026). Runs
    at the start of every button 3 run, so contacts added before this change are filled in too.
    Returns how many contacts changed."""
    rows = hs.tagged_search("contacts", [{"propertyName": "country", "operator": "NOT_HAS_PROPERTY"}],
                            ["email", "country", "city"], max_results=limit)
    if not rows:
        return 0
    ids = [str(r["id"]) for r in rows]
    links = hs.associated_ids("contacts", "companies", ids)
    company_ids = sorted({c for cs in links.values() for c in cs})
    companies = {str(r["id"]): r.get("properties", {})
                 for r in hs.tagged_read("companies", company_ids, ["country", "city"])} if company_ids else {}
    updates = []
    for r in rows:
        place = next((place_of(companies[c]) for c in links.get(str(r["id"])) or [] if c in companies
                      and place_of(companies[c]).get("country")), None)
        if place:
            current = r.get("properties", {})
            updates.append((r["id"], {k: v for k, v in place.items() if k == "country" or not current.get(k)}))
    if updates:
        hs.update_tagged("contacts", updates)
        log(f"Filled in the Country (and City) of {len(updates)} contacts from their company")
    return len(updates)


def add_company_inbox(hs, cid, name, domain, cfg, statuses, owner, log, email=NOT_LOOKED, place=None):
    """The company's website contact address as its one contact, or [] (agreed 19 Oct 2026)."""
    if email is NOT_LOOKED:
        email = company_inbox.find_inbox(domain, name=name)
    if not email:
        return []
    if hs.batch_read("contacts", [email], ["email"], id_property="email"):
        log(f"{name}: the website's contact address ({_mask(email)}) is already in HubSpot; not added again")
        return []
    record = {
        ORDER: "1",
        "email": email,
        "firstname": "",
        "lastname": "",
        "jobtitle": INBOX_TITLE,
        "company": name or "",
        **(place or {}),
        **statuses.props("contacts", "found"),
        **({"hubspot_owner_id": owner} if owner else {}),
        **({CONTACT_SOURCE: SOURCE_WEBSITE} if cfg.get("_source_field") else {}),
    }
    created = [c for c in _create_contacts(hs, [record], log) if c]
    if created:
        hs.associate_tagged("contacts", "companies", [(c["id"], cid) for c in created])
        log(f"{name}: nobody usable in Apollo; added the website's contact address ({_mask(email)}) instead")
    return created


def _create_contacts(hs, records, log):
    """Create contacts in one go; if HubSpot refuses the batch (e.g. an email it already holds as
    someone's second address), create them one by one and skip the ones it refuses."""
    try:
        return hs.create_tagged("contacts", records)
    except HubSpotError as err:
        log(f"HubSpot refused the batch ({str(err)[:200]}); adding the contacts one by one")
    created = []
    for r in records:
        try:
            created.extend(hs.create_tagged("contacts", [r]))
        except HubSpotError as err:
            log(f"Skipped one contact HubSpot refused: {str(err)[:200]}")
            created.append(None)
            continue
    return created


def _process(companies, hs, apollo, cfg, statuses, assigner, notes, skipped, kept, log_rows, log):
    credits = 0
    for company in companies:
        cid, p = company["id"], company.get("properties", {})
        name, domain = p.get("name"), clean_domain(p.get("domain"))
        row = {"company": name, "domain": domain, "contacts": 0}

        if not domain:
            hs.update_tagged("companies", [(cid, statuses.props("companies", "missing_info"))])
            row["result"] = "no domain"
            log_rows.append(row)
            continue
        if credits >= cfg["max_credits_per_run"]:
            log("Credit cap reached for this run; remaining companies stay GATE1: Approved for outreach for next time")
            break

        category = channel_of(p, notes)
        owner = p.get("hubspot_owner_id") or assigner.pick(market_of(p), category) or (
            cfg.get("_job_owner") if is_job_company(p, cfg.get("_job_notes")) else None) or None  # the job owner
        if owner and not p.get("hubspot_owner_id"):
            hs.update_tagged("companies", [(cid, {"hubspot_owner_id": owner})])
            row["owner_id"] = owner
        titles = titles_for(category, cfg["titles"])

        def ranked(where):
            return rank_people(
                find_people(apollo, where, cfg.get("seniorities"), cfg.get("search_per_page", 100)),
                cfg["hierarchy"], titles, cfg.get("exclude_words", []), cfg.get("include_everyone_else", True),
            )
        people = ranked(domain)
        # Nobody in Apollo at this website: its contact address may use the company's other domain
        # (19 Oct 2026, e.g. comptoir-produits-italiens.fr shows info@cofi.fr). Search Apollo there too.
        inbox_email = NOT_LOOKED
        if cfg.get("company_inbox_fallback") and not any(x.get("has_email", True) for x in people):
            inbox_email = company_inbox.find_inbox(domain, name=name)
            other = company_inbox.other_domain(inbox_email, domain)
            if other:
                people = ranked(other)
                row["other_domain"] = other
                log(f"{name}: nobody in Apollo at {domain}; also searched {other}, the company's other website "
                    f"({len(people)} people)")
        # Apollo says up front whether it holds an email; revealing the others wastes credits.
        # Anyone already revealed before (kept or not) is skipped, so nobody is paid for twice.
        candidates = [x for x in people if x.get("has_email", True)
                      and x["id"] not in kept and x["id"] not in skipped]
        keep, revealed, batches = [], 0, 0
        while candidates and len(keep) < cfg["per_company"] and credits < cfg["max_credits_per_run"]:
            size = min(10, cfg["per_company"] - len(keep),
                       cfg.get("max_reveals_per_company", cfg["per_company"]) - revealed,
                       cfg["max_credits_per_run"] - credits)
            if size <= 0:
                break
            batch, candidates = candidates[:size], candidates[size:]
            matches = apollo.reveal_emails([x["id"] for x in batch])
            batches += 1
            revealed += len(batch)
            credits += sum(1 for m in matches if m.get("email"))
            by_id = {m.get("id"): m for m in matches}
            for x in batch:  # keep the seniority order
                m = by_id.get(x["id"])
                if m and m.get("email") and (m.get("email_status") or "") in cfg["keep_email_statuses"]:
                    keep.append(m)
                elif m and m.get("email"):
                    skipped[x["id"]] = m.get("email_status") or "unknown"
        # Any email already in HubSpot (the team's own contacts included) is never added or changed.
        existing = {(r.get("properties", {}).get("email") or "").lower()
                    for r in hs.batch_read("contacts", [m["email"] for m in keep], ["email"], id_property="email")
                    } if keep else set()
        new_contacts, new_ids = [], []
        for m in keep:
            email = m["email"].lower()
            if email in existing:
                skipped[m["id"]] = "already in HubSpot"
                continue
            new_ids.append(m["id"])
            new_contacts.append({
                ORDER: str(len(new_contacts) + 1),
                "email": email,
                "firstname": m.get("first_name") or "",
                "lastname": m.get("last_name") or "",
                "jobtitle": m.get("title") or "",
                "company": name or "",
                **place_of(p),  # 23 Oct 2026: the company's Country and City
                **statuses.props("contacts", "found"),
                **({"hubspot_owner_id": owner} if owner else {}),
                **({CONTACT_SOURCE: SOURCE_APOLLO} if cfg.get("_source_field") else {}),
            })
        made = _create_contacts(hs, new_contacts, log) if new_contacts else []
        for apollo_id, c in zip(new_ids, made):
            kept[apollo_id] = str(c["id"]) if c else "not added"
        created = [c for c in made if c]
        if created:
            hs.associate_tagged("contacts", "companies", [(c["id"], cid) for c in created])
        inbox = False
        if not created and cfg.get("company_inbox_fallback"):
            created = add_company_inbox(hs, cid, name, domain, cfg, statuses, owner, log, email=inbox_email,
                                        place=place_of(p))
            inbox = bool(created)
        if not created:  # 23 Oct 2026: nobody in Apollo and no usable address anywhere
            hs.update_tagged("companies", [(cid, apollo_status.nowhere_props(hs, statuses))])
        elif str(p.get(apollo_status.STOP_REASON) or "").startswith(apollo_status.APOLLO_NOBODY) \
                and apollo_status.has_reason_field(hs):
            hs.update_tagged("companies", [(cid, {apollo_status.STOP_REASON: ""})])  # contacts found after all
        status = "company inbox added" if inbox else "contacts found" if created else "no contacts found"
        with_email = sum(1 for x in people if x.get("has_email", True))
        row["contact_ids"] = [str(c["id"]) for c in created]  # for the list of who needs lines
        row.update(result=status, contacts=len(created), people_found=len(people),
                   with_email=with_email, emails_revealed=revealed, verified=len(keep),
                   top_person=(keep[0].get("title") if keep else ""))
        log_rows.append(row)
        log(f"{name}: {len(people)} people, {with_email} with an email in Apollo, "
            f"{revealed} revealed, {len(keep)} verified, {len(created)} added"
            + (f" (most senior: {keep[0].get('title')})" if keep else "")
            + ("" if created else "; Lead Status set to Missing Info"))
    return credits


def main(argv=None):
    p = argparse.ArgumentParser(description="Find contacts for approved companies")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--skip-if-not-configured", action="store_true",
                   help="exit quietly when a key is missing (used by the automatic runs)")
    args = p.parse_args(argv)
    if args.skip_if_not_configured and not (os.environ.get("HUBSPOT_TOKEN") and os.environ.get("APOLLO_API_KEY")):
        print("Find people skipped: a key it needs is not added yet.")
        return 0
    try:
        run(args.target, load_settings(), HubSpot(), Apollo())
    except (PipelineError, HubSpotError, ApolloError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
