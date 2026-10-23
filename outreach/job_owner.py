"""The HubSpot owner of everything the research jobs bring in (agreed 23 Oct 2026, Ariel).

"The jobs" are the research jobs J0001 to the latest: a company counts when a job added it to HubSpot
(its domain is in data/company_notes.json, which every job import fills, or it carries a Job Number).
Every company a job adds, and every contact button 3 adds at such a company, gets the owner set in
config/settings.yaml (assignment.job_owner_id, a HubSpot owner ID). Job companies and their contacts
with no owner get it at the start of every run of button 3, so the earlier jobs are filled in too. A
record that already has an owner (a team member who took it over) keeps it, and a contact with no
owner follows its company's owner when the company has one. AUTO-OUTREACH records that did not come
from a job (for example from the earlier version of the pipeline) are left alone.
"""

from .common import load_company_notes
from .schema import JOB_NUMBER

OWNER = "hubspot_owner_id"


def job_owner(settings):
    """The owner ID as text, or "" when none is set."""
    value = ((settings or {}).get("assignment") or {}).get("job_owner_id")
    return str(value).strip() if value not in (None, "") else ""


def is_job_company(props, notes=None):
    """True when a research job added this company (J0001 onwards)."""
    props = props.get("properties", props) or {}
    notes = load_company_notes() if notes is None else notes
    domain = (props.get("domain") or "").strip().lower()
    return bool(props.get(JOB_NUMBER)) or bool(domain and domain in notes)


def fill_owners(hs, owner, log=print, limit=5000, notes=None):
    """Give the job companies and their contacts that have no owner the job owner. Returns
    {"companies": n, "contacts": n}."""
    done = {"companies": 0, "contacts": 0}
    if not owner:
        return done
    notes = load_company_notes() if notes is None else notes
    no_owner = [{"propertyName": OWNER, "operator": "NOT_HAS_PROPERTY"}]
    companies = [r for r in hs.tagged_search("companies", no_owner, [OWNER, "domain", JOB_NUMBER], max_results=limit)
                 if not (r.get("properties") or {}).get(OWNER) and is_job_company(r, notes)]
    if companies:
        hs.update_tagged("companies", [(r["id"], {OWNER: owner}) for r in companies])
        done["companies"] = len(companies)
    contacts = [r for r in hs.tagged_search("contacts", no_owner, [OWNER], max_results=limit)
                if not (r.get("properties") or {}).get(OWNER)]
    if contacts:
        links = hs.associated_ids("contacts", "companies", [str(r["id"]) for r in contacts])
        ids = sorted({c for cs in links.values() for c in cs})
        info = {str(c["id"]): c for c in hs.tagged_read("companies", ids, [OWNER, "domain", JOB_NUMBER])} if ids else {}
        updates = []
        for r in contacts:
            mine = [info[c] for c in links.get(str(r["id"])) or [] if c in info and is_job_company(info[c], notes)]
            if not mine:
                continue  # not at a job company: left alone
            company_owner = next(((c.get("properties") or {}).get(OWNER) for c in mine
                                  if (c.get("properties") or {}).get(OWNER)), None)
            updates.append((r["id"], {OWNER: company_owner or owner}))
        if updates:
            hs.update_tagged("contacts", updates)
            done["contacts"] = len(updates)
    if done["companies"] or done["contacts"]:
        log(f"Gave the job owner to {done['companies']} companies and {done['contacts']} contacts from the research "
            "jobs that had no owner")
    return done
