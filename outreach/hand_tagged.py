"""Contacts a person made AUTO-OUTREACH by hand (agreed 26 Oct 2026, Ariel).

Button 3 always gives the contacts it adds an "Outreach order". So an AUTO-OUTREACH contact without
one is a contact that was already in HubSpot and that a person tagged by hand. At the start of every
run of button 3 such contacts are made ready for outreach, without anyone having to do it:

  - a general address (info@, hello@, welcome@, marketing@ ...), or a contact whose name is just the
    company's name (or empty), becomes a company inbox: its Job title is set to "Company inbox (from
    website)", so its email greets "Hello to the team at <company>" and asks them to pass it on,
    instead of "Hi <company name>";
  - every one of them gets an Outreach order: the people first, most senior by job title (in the
    order the seniority list in config/settings.yaml gives), then the company inboxes, after any
    contact at the company that already has an order.

Nothing else is changed: name, email, owner and Lead Status stay as the person left them.
"""

import re

from .schema import INBOX_TITLE, LEAD_STATUS, ORDER

# The first part of an address that belongs to a company, not to a person.
GENERAL_WORDS = {
    "info", "infos", "information", "office", "contact", "contacts", "kontakt", "contacto", "contato", "contatti",
    "hello", "hallo", "hola", "hi", "mail", "email", "post", "welcome", "willkommen", "bienvenue", "marketing",
    "order", "orders", "bestellung", "bestellungen", "commande", "commandes", "shop", "store", "boutique",
    "sales", "verkauf", "vertrieb", "ventes", "vendite", "service", "kundenservice", "customerservice",
    "team", "admin", "enquiries", "inquiries", "enquiry", "general", "zentrale", "einkauf", "purchasing",
    "buying", "achats", "acquisti", "compras", "export", "business", "b2b", "wholesale", "trade", "handel",
    "support", "help", "care", "reception", "empfang", "secretariat", "sekretariat", "postmaster", "webmaster",
}
LEGAL_FORMS = {"ag", "gmbh", "sa", "sarl", "sàrl", "ltd", "llc", "inc", "kg", "co", "the", "srl", "spa", "bv", "nv"}


def _words(text):
    return [w for w in re.findall(r"[a-z0-9äöüàâçéèêëîïôûùœ]+", str(text or "").lower()) if w not in LEGAL_FORMS]


def is_general(contact, company_name=""):
    """True for a company's own address rather than a person's."""
    p = contact.get("properties", contact) or {}
    email = str(p.get("email") or "").lower()
    local = email.split("@", 1)[0]
    if any(w in GENERAL_WORDS for w in re.split(r"[._+\-0-9]+", local) if w):
        return True
    name = " ".join(x for x in (p.get("firstname"), p.get("lastname")) if x and str(x).strip())
    if not name.strip() or name.strip().lower() == email:
        # No name at all: a company address, unless the address itself is a person's (first.last@).
        return not re.fullmatch(r"[a-zäöüéèàç]{2,}[._-][a-zäöüéèàç]{2,}", local)
    company = _words(company_name)
    return bool(company) and _words(name) == company  # the company's name typed into the name fields


def _level(contact, hierarchy):
    from .find_contacts import hierarchy_level
    return hierarchy_level((contact.get("properties") or {}).get("jobtitle"), hierarchy)[0] if hierarchy else 0


def _order(value):
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def prepare(hs, settings, log=print, limit=2000):
    """Make hand-tagged AUTO-OUTREACH contacts ready for outreach (see the top). Returns
    {"contacts": n, "company_inboxes": n}."""
    done = {"contacts": 0, "company_inboxes": 0, "companies_back_to_gate1": 0}
    rows = hs.tagged_search("contacts", [{"propertyName": ORDER, "operator": "NOT_HAS_PROPERTY"}],
                            ["email", "firstname", "lastname", "jobtitle", ORDER, LEAD_STATUS], max_results=limit)
    rows = [r for r in rows if not (r.get("properties") or {}).get(ORDER)]
    if not rows:
        return done
    hierarchy = ((settings or {}).get("contacts") or {}).get("hierarchy") or []
    links = hs.associated_ids("contacts", "companies", [str(r["id"]) for r in rows])
    company_ids = sorted({c for cs in links.values() for c in cs})
    companies = {str(c["id"]): c for c in hs.tagged_read("companies", company_ids, ["name"])} if company_ids else {}
    by_company = {}
    for r in rows:
        cid = next((c for c in links.get(str(r["id"])) or [] if c in companies), None)
        if cid:
            by_company.setdefault(cid, []).append(r)
    if not by_company:
        return done
    # Contacts at those companies that already have an order keep it; the new ones come after them.
    back = hs.associated_ids("companies", "contacts", list(by_company))
    others = sorted({c for cs in back.values() for c in cs})
    ordered = {str(c["id"]): _order((c.get("properties") or {}).get(ORDER))
               for c in hs.tagged_read("contacts", others, [ORDER])} if others else {}
    updates = []
    for cid, contacts in by_company.items():
        name = (companies[cid].get("properties") or {}).get("name") or ""
        start = max([ordered.get(str(x), 0) for x in back.get(cid) or []] + [0])
        people = [(c, is_general(c, name)) for c in contacts]
        people.sort(key=lambda x: (x[1], _level(x[0], hierarchy), str(x[0]["id"])))
        for i, (c, general) in enumerate(people, start=start + 1):
            props = {ORDER: str(i)}
            if general and (c.get("properties") or {}).get("jobtitle") != INBOX_TITLE:
                props["jobtitle"] = INBOX_TITLE
                done["company_inboxes"] += 1
            updates.append((c["id"], props))
        log(f"{name}: {len(contacts)} contact(s) tagged by hand made ready for outreach ("
            f"{sum(1 for _, g in people if g)} company inbox)")
    hs.update_tagged("contacts", updates)
    done["contacts"] = len(updates)
    # 26 Oct 2026 (Ariel): their companies go back to GATE1 by themselves.
    from .apollo_status import back_to_gate1
    from .stages import LeadStatus
    done["companies_back_to_gate1"] = back_to_gate1(hs, LeadStatus(hs), list(by_company), log)
    return done
