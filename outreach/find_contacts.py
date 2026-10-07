"""Job 3: find contacts at approved companies with Apollo and add them to HubSpot.

Only companies whose Outreach company status is Approved are processed (gate 1).
For each company it looks at everyone Apollo holds there, ranks them by seniority
(settings: contacts.hierarchy) and keeps up to contacts.per_company verified emails,
most senior first. Each contact gets an Outreach hierarchy rank (1 = most senior).
Usage:
    python -m outreach.find_contacts --target test
"""

import argparse
import re
import sys

from .apollo_client import Apollo, ApolloError
from .assign import Assigner
from .common import PipelineError, category_label, check_target, clean_domain, load_settings, run_dir, write_json
from .hubspot_client import HubSpot, HubSpotError

COMPANY_PROPS = [
    "name", "domain", "diablo_market", "diablo_channel_category",
    "diablo_suppress_reason", "diablo_outreach_status", "hubspot_owner_id",
]


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


def opted_out_emails(hs, emails):
    rows = hs.batch_read("contacts", emails, ["email", "diablo_contact_status"], id_property="email")
    existing = {}
    for r in rows:
        p = r.get("properties", {})
        if p.get("email"):
            existing[p["email"].lower()] = p.get("diablo_contact_status") or ""
    return existing


def run(target, settings, hs, apollo, log=print):
    check_target(hs, target)
    cfg = settings["contacts"]
    assigner = Assigner(hs, settings, log)
    out_dir = run_dir("contacts")
    companies = hs.search(
        "companies",
        [{"propertyName": "diablo_outreach_status", "operator": "EQ", "value": "approved"}],
        COMPANY_PROPS,
        max_results=cfg["companies_per_run"],
    )
    log(f"{len(companies)} approved companies to process")
    labels = hs.option_labels("companies", "diablo_channel_category") if companies else {}

    credits, log_rows = 0, []
    for company in companies:
        cid, p = company["id"], company.get("properties", {})
        name, domain = p.get("name"), clean_domain(p.get("domain"))
        row = {"company": name, "domain": domain, "contacts": 0}

        if p.get("diablo_suppress_reason"):
            hs.batch_update("companies", [(cid, {"diablo_outreach_status": "suppressed"})])
            row["result"] = "suppressed"
            log_rows.append(row)
            continue
        if not domain:
            hs.batch_update("companies", [(cid, {"diablo_outreach_status": "no_domain"})])
            row["result"] = "no domain"
            log_rows.append(row)
            continue
        if credits >= cfg["max_credits_per_run"]:
            log("Credit cap reached for this run; remaining companies stay Approved for next time")
            break

        category = category_label(p.get("diablo_channel_category"), labels)
        owner = p.get("hubspot_owner_id") or assigner.pick(p.get("diablo_market") or "", category)
        if owner and not p.get("hubspot_owner_id"):
            hs.batch_update("companies", [(cid, {"hubspot_owner_id": owner})])
            row["owner_id"] = owner
        titles = titles_for(category, cfg["titles"])
        people = rank_people(
            find_people(apollo, domain, cfg.get("seniorities"), cfg.get("search_per_page", 100)),
            cfg["hierarchy"], titles, cfg.get("exclude_words", []), cfg.get("include_everyone_else", True),
        )
        # Apollo says up front whether it holds an email; revealing the others wastes credits.
        candidates = [x for x in people if x.get("has_email", True)]
        level_of = {x["id"]: x["_level"] for x in people}
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
        existing = opted_out_emails(hs, [m["email"] for m in keep]) if keep else {}
        new_contacts = []
        for rank, m in enumerate(keep, start=1):
            email = m["email"].lower()
            if email in existing:
                continue  # already in HubSpot (and possibly opted out): never re-add or reset
            new_contacts.append({
                "diablo_hierarchy_rank": str(rank),
                "diablo_hierarchy_level": level_of.get(m.get("id"), ""),
                "email": email,
                "firstname": m.get("first_name") or "",
                "lastname": m.get("last_name") or "",
                "jobtitle": m.get("title") or "",
                "company": name or "",
                "diablo_market": p.get("diablo_market") or "",
                "diablo_contact_status": "contact_found",
                "diablo_email_status": m.get("email_status") or "",
                "diablo_apollo_id": m.get("id") or "",
                **({"hubspot_owner_id": owner} if owner else {}),
            })
        created = hs.batch_create("contacts", new_contacts) if new_contacts else []
        if created:
            hs.associate_default("contacts", "companies", [(c["id"], cid) for c in created])

        found = len(created) + sum(1 for m in keep if m["email"].lower() in existing)
        status = "contacts_found" if found else "no_contacts_found"
        hs.batch_update("companies", [(cid, {"diablo_outreach_status": status})])
        with_email = sum(1 for x in people if x.get("has_email", True))
        row.update(result=status, contacts=len(created), people_found=len(people),
                   with_email=with_email, emails_revealed=revealed, verified=len(keep),
                   top_person=(keep[0].get("title") if keep else ""))
        log_rows.append(row)
        log(f"{name}: {len(people)} people, {with_email} with an email in Apollo, "
            f"{revealed} revealed, {len(keep)} verified, {len(created)} added"
            + (f" (most senior: {keep[0].get('title')})" if keep else ""))

    summary = {"companies": len(log_rows), "apollo_credits_used": credits, "rows": log_rows}
    write_json(out_dir / "summary.json", summary)
    log(f"Apollo credits used (approx.): {credits}")
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="Find contacts for approved companies")
    p.add_argument("--target", default="test", choices=["test", "live"])
    args = p.parse_args(argv)
    try:
        run(args.target, load_settings(), HubSpot(), Apollo())
    except (PipelineError, HubSpotError, ApolloError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
