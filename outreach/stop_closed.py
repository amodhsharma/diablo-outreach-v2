"""Stop every email to the people at a company you have closed (agreed 17 Nov 2026, Ariel).

At every run of buttons 3 and 4, every AUTO-OUTREACH company on one of the closed Lead Statuses below is
swept: any introduction of one of its people that is still waiting in a Diablo campaign in Instantly (added
but not yet sent) is taken out of Instantly at once, and their contacts get the label that says why
(sync.close_company_contacts, e.g. "Unqualified company"). Nobody at the company is emailed again: the
reminders and the next people only ever go to companies still being emailed.

    Unqualified (you rejected it)                     Unqualified: Channel no longer targeted
    Unqualified: Employee response negative           Unqualified: Employee Opted-out/Blocklist
    Unqualified: Contacted, but no response

An email that has already gone cannot be called back; the campaigns hold only the introduction (the reminder
is sent by button 4 itself), so nothing more follows from Instantly.
"""

from .hubspot_client import tagged
from .schema import LEAD_STATUS
from .next_in_line import contacts_by_company, instantly_view

CLOSED = ("closed", "channel_paused", "said_no", "opted_out", "no_response")


def run(hs, instantly, settings, statuses, log=print, leads=None):
    """Returns {"companies": n closed companies looked at, "pulled": n waiting introductions taken out}."""
    out = {"companies": 0, "pulled": 0}
    if instantly is None:
        return out
    companies = []
    for stage in CLOSED:
        if statuses.has("companies", stage):
            companies += hs.tagged_search("companies", [statuses.filter("companies", stage)], ["name", LEAD_STATUS],
                                          max_results=5000)
    out["companies"] = len(companies)
    if not companies:
        return out
    view = leads if leads is not None else instantly_view(instantly, settings["sync"]["campaign_prefix"])
    waiting = {e: l for e, l in view.items() if not l.get("timestamp_last_contact") and l.get("id")}
    if not waiting:
        return out
    everyone = contacts_by_company(hs, [c["id"] for c in companies])
    for company in companies:
        name = (company.get("properties") or {}).get("name") or "A company"
        label = statuses.label("companies", (company.get("properties") or {}).get(LEAD_STATUS)) or "closed"
        for c in everyone.get(company["id"]) or []:
            if not tagged(c.get("properties")):
                continue
            email = ((c.get("properties") or {}).get("email") or "").lower()
            lead = waiting.get(email)
            if not lead:
                continue
            try:
                instantly.delete_lead(lead["id"])
            except Exception as err:  # tried again at the next run
                log(f"{name}: could not take contact {c['id']}'s waiting introduction out of Instantly: "
                    f"{str(err)[:200]}")
                continue
            waiting.pop(email, None)
            view.pop(email, None)
            out["pulled"] += 1
            title = (c.get("properties") or {}).get("jobtitle") or "contact"
            log(f"{name} is closed ({label}): the {title}'s introduction was still waiting in Instantly, so it was "
                "taken out and will not be sent")
    if out["pulled"]:
        log(f"{out['pulled']} waiting introduction(s) at closed companies taken out of Instantly")
    return out
