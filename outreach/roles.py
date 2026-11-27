"""People we never email because of their job title (HARD RULE, Ariel, 27 Nov 2026).

After the follow-up step sent reminders to a People and Culture Manager and a Social Media Manager, Ariel
asked for a hard rule that stops it at once: nobody in HR, finance, IT, legal, PA and assistant roles, safety,
marketing and social media, store staff or logistics is ever emailed by the automation, whatever their
seniority. A title that also names a role we do target (buying, owner or the top of the company, commercial
or sales leadership, business development) is never blocked, so "Head of Sales and Marketing" or "Assistant
Buyer" still go.

Where it acts
    next_in_line.contact_state   such a person counts as "skipped": no introduction, no reminder, and the
                                 next person at the company moves up (the others carry on).
    pull_waiting (button 4)      their introduction still waiting in Instantly is taken out before it goes,
                                 and "Outreach stopped because" says why, once.

A person who already answered is never touched: the reply still stops the company as before. Company
inboxes are not job titles and are left as they are. The words are in config/settings.yaml under
contacts.never_email, so a role can be added or taken out without touching the code.
"""

import re

from .hubspot_client import tagged
from .schema import LEAD_STATUS, STOP_REASON

# Each group: words that put a title in it (matched as whole words or word starts, any case).
NEVER = {
    "HR": [r"\bhr\b", r"human resource", r"people\s*(?:&|and)\s*culture", r"people partner", r"people operations",
           r"\bpersonal", r"personnel", r"recruit", r"talent", r"payroll", r"ressources humaines", r"\brh\b",
           r"risorse umane"],
    "finance": [r"financ", r"accountant", r"accounting", r"accounts payable", r"accounts receivable", r"bookkeep",
                r"controller", r"controlling", r"\bcfo\b", r"treasur", r"\btax\b", r"audit", r"buchhalt",
                r"comptab", r"credit control"],
    "IT": [r"\bit\b", r"information technology", r"\bcto\b", r"\bcio\b", r"software", r"developer", r"engineer",
           r"product owner", r"devops", r"\bdata\b", r"system administrator", r"informatik", r"informatique",
           r"\btech\b", r"technology"],
    "legal": [r"legal", r"counsel", r"lawyer", r"solicitor", r"compliance", r"jurist", r"paralegal"],
    "PA or assistant": [r"assistant", r"\bpa\b", r"secretary", r"reception", r"office manager", r"\badmin\b",
                        r"administrative", r"\badministrator\b"],
    "safety": [r"safety", r"\bshe\b", r"\bhse\b", r"\behs\b", r"environment", r"arbeitssicherheit"],
    "marketing": [r"marketing", r"social media", r"communication", r"\bpr\b", r"public relations", r"\bcontent\b",
                  r"community manager", r"\bseo\b"],
    "store staff": [r"\bstore", r"shop assistant", r"cashier", r"filial", r"sales assistant", r"retail assistant",
                    r"magasin", r"verkäufer", r"barista", r"\bcrew\b"],
    "logistics": [r"logistic", r"warehouse", r"\blager", r"transport", r"fleet", r"dispatch", r"driver",
                  r"supply chain", r"inventory", r"entrepôt"],
}
# Any of these in the title and it is never blocked: the roles we do email.
TARGETED = [r"buyer", r"buying", r"purchas", r"procure", r"category", r"sourcing", r"einkauf", r"achat",
            r"acheteur", r"acquisti", r"compras", r"\bimport", r"(?<!product )\bowner", r"founder", r"\bceo\b",
            r"chief executive", r"managing director", r"\bmd\b", r"general manager", r"geschäftsführ", r"inhaber",
            r"(?<!vice )\bpresident", r"président", r"directeur général", r"director general", r"proprietor",
            r"country manager", r"commercial", r"sales director", r"director of sales", r"head of sales",
            r"business development"]
# Someone working for one of those people is still an assistant: never emailed, whatever else the title says.
ALWAYS = [r"assistant to", r"\bpa to\b", r"executive assistant", r"personal assistant", r"secretary to",
          r"office of the"]


def config(settings):
    """The groups and the targeted words, from contacts.never_email when it is there."""
    cfg = ((settings or {}).get("contacts") or {}).get("never_email") or {}
    if cfg.get("enabled") is False:
        return None
    return {"never": cfg.get("groups") or NEVER, "targeted": cfg.get("targeted") or TARGETED,
            "always": cfg.get("always") or ALWAYS}


_CFG = {"value": {"never": NEVER, "targeted": TARGETED, "always": ALWAYS}}


def use(settings):
    """Set the rule for this run from the settings (called by buttons 3 and 4)."""
    _CFG["value"] = config(settings)


def wrong_role(title, cfg=None):
    """The group a job title is never emailed for ("HR", "marketing" ...), or None."""
    cfg = _CFG["value"] if cfg is None else cfg
    text = str(title or "").strip().lower()
    if not cfg or not text or text.startswith("company inbox") or text.startswith("referred by"):
        return None
    if any(re.search(p, text) for p in cfg.get("always") or []):
        return "PA or assistant"
    if any(re.search(p, text) for p in cfg["targeted"]):
        return None
    for group, words in cfg["never"].items():
        if any(re.search(p, text) for p in words):
            return group
    return None


REASON_START = "Outreach stopped: their job title is in a role we never email"


def reason(group, day):
    return f"{REASON_START} ({group}) ({day})"


# The states a role check turns into "skipped": a person not emailed yet, or emailed with no answer.
OPEN = ("pending", "approved", "queued", "sent")


def pull_waiting(hs, instantly, statuses, log=print, leads=None, today=""):
    """Button 4: take out of Instantly every waiting introduction of a person in a role we never email, at
    companies still being emailed, and say why on their record once. Returns how many were taken out."""
    from .next_in_line import contacts_by_company, contact_state
    if _CFG["value"] is None or instantly is None:
        return 0
    companies = []
    for stage in ("approved", "located", "in_outreach"):
        if statuses.has("companies", stage):
            companies += hs.tagged_search("companies", [statuses.filter("companies", stage)], ["name", LEAD_STATUS],
                                          max_results=5000)
    if not companies:
        return 0
    view = leads if leads is not None else {}
    everyone = contacts_by_company(hs, [c["id"] for c in companies])
    pulled, notes = 0, []
    for company in companies:
        name = (company.get("properties") or {}).get("name") or "A company"
        for c in everyone.get(company["id"]) or []:
            p = c.get("properties") or {}
            group = wrong_role(p.get("jobtitle"))
            if not group or not tagged(p) or contact_state(c, statuses, view, roles=False) not in OPEN:
                continue
            lead = view.get((p.get("email") or "").lower())
            if lead and lead.get("id") and not lead.get("timestamp_last_contact"):
                try:
                    instantly.delete_lead(lead["id"])
                except Exception as err:  # tried again at the next run
                    log(f"{name}: could not take the {p.get('jobtitle')}'s waiting introduction out of Instantly: "
                        f"{str(err)[:200]}")
                    continue
                view.pop((p.get("email") or "").lower(), None)
                pulled += 1
                log(f"{name}: the {p.get('jobtitle')} ({group}) is a role we never email; their introduction was "
                    "still waiting in Instantly, so it was taken out")
            if not str(p.get(STOP_REASON) or "").startswith(REASON_START):
                notes.append((c["id"], reason(group, today)))
    if notes:
        from .sync import stop_reasons
        stop_reasons(hs, "contacts", notes, log)
        log(f"{len(notes)} contact(s) in roles we never email marked in HubSpot (Outreach stopped because)")
    return pulled
