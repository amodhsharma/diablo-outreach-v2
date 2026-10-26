"""Every AUTO-OUTREACH contact linked to its company (agreed 26 Oct 2026, Ariel).

So that typing a company's name in HubSpot's Contacts finds its people, and the "Primary company"
column is never empty:
  - button 3 links every contact it adds to its company as the contact's Primary company, and fills
    its "Company name";
  - at the start of every run of button 3, each AUTO-OUTREACH contact is checked:
      * no Company name: the name of its AUTO-OUTREACH company is filled in;
      * linked to its AUTO-OUTREACH company but no Primary company at all: that company becomes its
        Primary company;
      * not linked to any company: it is linked (as Primary) to the one AUTO-OUTREACH company whose
        website matches its email address; when none or several match, the run's summary lists it
        to be linked by hand.
Only empty fields are filled and a Primary company already set is never changed. Only AUTO-OUTREACH
records are touched.
"""

from .hubspot_client import PRIMARY_COMPANY

LIMIT = 5000


def _domain(email):
    return str(email or "").split("@")[-1].strip().lower() if "@" in str(email or "") else ""


def _plain(domain):
    domain = str(domain or "").strip().lower()
    for prefix in ("https://", "http://"):
        domain = domain[len(prefix):] if domain.startswith(prefix) else domain
    domain = domain.split("/")[0]
    return domain[4:] if domain.startswith("www.") else domain


def fill_primary(hs, log=print, limit=LIMIT):
    """Returns {"primary_set": n, "names_filled": n, "linked": n, "unlinked": [contact IDs]}."""
    done = {"primary_set": 0, "names_filled": 0, "linked": 0, "unlinked": []}
    contacts = hs.tagged_search("contacts", [], ["email", "company"], max_results=limit)
    if not contacts:
        return done
    types = hs.associated_types("contacts", "companies", [str(c["id"]) for c in contacts])
    company_ids = sorted({co for links in types.values() for co in links})
    ours = {str(r["id"]): r.get("properties", {})
            for r in hs.tagged_read("companies", company_ids, ["name", "domain"])} if company_ids else {}
    by_domain = {}
    loose = [c for c in contacts if not types.get(str(c["id"]))]
    if loose:  # the AUTO-OUTREACH companies, by website, for contacts linked to none
        for r in hs.tagged_search("companies", [], ["name", "domain"], max_results=limit):
            d = _plain((r.get("properties") or {}).get("domain"))
            if d:
                by_domain.setdefault(d, []).append(r)
                ours.setdefault(str(r["id"]), r.get("properties", {}))
    primary, names = [], []
    for c in contacts:
        cid, p = str(c["id"]), c.get("properties") or {}
        links = types.get(cid) or {}
        mine = [co for co in links if co in ours]
        target = None
        if not links:
            matches = by_domain.get(_domain(p.get("email")), [])
            if len(matches) == 1:
                target = str(matches[0]["id"])
                primary.append((cid, target))
                done["linked"] += 1
            else:
                done["unlinked"].append(cid)
        elif mine:
            target = next((co for co in mine if PRIMARY_COMPANY in links[co]), mine[0])
            if not any(PRIMARY_COMPANY in t for t in links.values()):
                primary.append((cid, target))
                done["primary_set"] += 1
        name = (ours.get(target) or {}).get("name") if target else ""
        if name and not (p.get("company") or "").strip():
            names.append((cid, {"company": name}))
            done["names_filled"] += 1
    hs.associate_primary_tagged(primary)
    hs.update_tagged("contacts", names)
    if primary or names:
        log(f"Contacts and their companies: {done['primary_set']} given their Primary company, {done['linked']} linked "
            f"to the company of their website, {done['names_filled']} given their Company name")
    if done["unlinked"]:
        log(f"{len(done['unlinked'])} AUTO-OUTREACH contacts are linked to no company and no single company has "
            "their website: link them by hand (listed on the run's summary page)")
    return done
