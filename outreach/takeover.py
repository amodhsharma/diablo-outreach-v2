"""Existing contacts taken over automatically (agreed 10 Nov 2026, Ariel).

Tagging every old contact AUTO-OUTREACH by hand takes too long, so at the start of every run of button 3
every contact linked to an approved AUTO-OUTREACH company (any link, not only its Primary company) that
is not AUTO-OUTREACH yet is made AUTO-OUTREACH with Lead Status New, whatever its status was, and so is
treated as a new contact for that company. The companies looked at: GATE1: Approved for outreach,
"Contact located. Queued for processing" and "Contact exists, not AUTO-OUTREACH".

Never taken over:
  - a contact marked Won, or one also linked to a company marked Won (a customer);
  - a contact who opted out: unsubscribed in HubSpot, on Instantly's blocklist, or on an opted-out status;
  - a dead address: Unqualified: Contact corrupt or Inbox Bounced, or a hard bounce in HubSpot;
  - a contact with no email address.
When Instantly's blocklist cannot be read, nobody is taken over in that run (it is tried again next run).

The owner stays as it is; the legal basis "Legitimate interest - prospect/lead" is set when it is empty.
Nothing else changes: hand_tagged.py then gives them their Outreach order (people first, then company
inboxes, after the contacts already in the loop) and linking.py their Company name, and Apollo is only
asked for the people still missing. They get a first introduction even if the team emailed them before.
"""

from .hubspot_client import tagged
from .schema import LEAD_STATUS, LEGAL_BASIS, LEGAL_BASIS_LEAD

# Company stages whose contacts are taken over.
COMPANY_STAGES = ("approved", "located", "contact_exists")
# Contact stages that mean "never write to this person again".
OPTED_OUT = ("opted_out", "colleague_opted_out")
DEAD = ("corrupt", "inbox_bounced")
WON = "won"
CONTACT_PROPS = ["email", "firstname", "lastname", LEAD_STATUS, LEGAL_BASIS, "hs_email_optout",
                 "hs_email_hard_bounce_reason_enum", "lead_source"]


def _is_won(statuses, obj, props):
    return str(statuses.label(obj, (props or {}).get(LEAD_STATUS)) or "").strip().lower() == WON


def why_not(contact, statuses, blocked, won_companies=()):
    """Why a contact is never taken over, or None."""
    from .sync import is_blocked
    p = contact.get("properties") or {}
    email = (p.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return "no email"
    if _is_won(statuses, "contacts", p) or won_companies:
        return "Won"
    stage = statuses.of("contacts", p)
    if stage in OPTED_OUT or str(p.get("hs_email_optout") or "").lower() == "true" or is_blocked(email, blocked):
        return "opted out"
    if stage in DEAD or p.get("hs_email_hard_bounce_reason_enum"):
        return "dead address"
    return None


def read_blocked(log=print):
    """Instantly's blocklist, read with the blocklist key (INSTANTLY_BLOCKLIST_KEY) or the main key."""
    from .instantly_client import Instantly
    from .sync import read_blocklist
    try:
        client = Instantly()
    except Exception:
        client = None
    return read_blocklist(client, log=log)


def run(hs, statuses, log=print, blocked=None, limit=2000):
    """Take over the contacts (see the top). blocked: Instantly's blocklist (sync.BlockList); read here when
    not given. Returns {"taken": n, "companies": {name: n}, "skipped": {reason: n}, "ids": [contact ids]}."""
    out = {"taken": 0, "companies": {}, "skipped": {}, "ids": []}
    companies = []
    for stage in COMPANY_STAGES:
        if statuses.has("companies", stage):
            companies += hs.tagged_search("companies", [statuses.filter("companies", stage)],
                                          ["name", LEAD_STATUS], max_results=limit)
    if not companies:
        return out
    names = {str(c["id"]): (c.get("properties") or {}).get("name") or "A company" for c in companies}
    links = hs.associated_ids("companies", "contacts", list(names))
    owner_of = {}
    for cid, contact_ids in links.items():
        for x in contact_ids or []:
            owner_of.setdefault(str(x), str(cid))
    if not owner_of:
        return out
    rows = hs.batch_read("contacts", sorted(owner_of), CONTACT_PROPS)
    rows = [r for r in rows if not tagged(r.get("properties"))]
    if not rows:
        return out
    if blocked is None:
        blocked = read_blocked(log)
    if getattr(blocked, "ok", True) is False:
        log(f"{len(rows)} existing contacts at approved companies are not taken over in this run: Instantly's "
            "blocklist could not be read, so it is not certain none of them opted out (tried again next run)")
        out["skipped"]["blocklist not read"] = len(rows)
        return out
    # A contact also linked to a company marked Won is a customer's person.
    theirs = hs.associated_ids("contacts", "companies", [str(r["id"]) for r in rows])
    others = sorted({c for cs in theirs.values() for c in cs or [] if str(c) not in names})
    won = {str(c["id"]) for c in (hs.batch_read("companies", others, [LEAD_STATUS]) if others else [])
           if _is_won(statuses, "companies", c.get("properties"))}
    new_value = statuses.value("contacts", "found")
    updates = []
    for r in rows:
        rid = str(r["id"])
        reason = why_not(r, statuses, blocked, [c for c in theirs.get(rid) or [] if str(c) in won])
        if reason:
            out["skipped"][reason] = out["skipped"].get(reason, 0) + 1
            continue
        props = {LEAD_STATUS: new_value}
        if not (r.get("properties") or {}).get(LEGAL_BASIS):
            props[LEGAL_BASIS] = LEGAL_BASIS_LEAD
        updates.append((rid, props))
        name = names.get(owner_of[rid], "A company")
        out["companies"][name] = out["companies"].get(name, 0) + 1
    if updates:
        hs.take_over_contacts(updates)
    out["taken"], out["ids"] = len(updates), [i for i, _ in updates]
    for name, n in sorted(out["companies"].items()):
        log(f"{name}: {n} existing contact{'s' if n != 1 else ''} made AUTO-OUTREACH and set to New")
    if out["skipped"]:
        log("Existing contacts not taken over: " + ", ".join(f"{n} {k}" for k, n in sorted(out["skipped"].items())))
    return out


def summary(result):
    """A short paragraph for button 3's summary page, or ""."""
    if not result or not (result.get("taken") or result.get("skipped")):
        return ""
    lines = [f"Existing contacts taken over (made AUTO-OUTREACH and set to New): {result.get('taken', 0)}"]
    for name, n in sorted((result.get("companies") or {}).items()):
        lines.append(f"- {name}: {n}")
    if result.get("skipped"):
        lines.append("Left as they are: " + ", ".join(f"{n} {k}" for k, n in sorted(result["skipped"].items())))
    return "\n".join(lines)
