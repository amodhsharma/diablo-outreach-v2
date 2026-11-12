"""The first email to someone a reply pointed us to (agreed 12 Nov 2026, Ariel, after Taste Organic).

When a reply hands us to someone else ("the person to contact for new products is ... bishnu@..."), the new
person's first email is not the normal introduction through the campaign. It is a forward of that reply, so they
see their colleague's own words naming them, with a short note on top (templates/referral.json, or
send.templates.referral in config/settings.yaml):

    Hi Bishnu,

    Your colleague Matt kindly passed on your details as the person who looks after new products, so I am
    sharing our note with you below.
    ... (catalogue, a call with our Strategy Director, the booking link)

    ---------- Forwarded message ---------
    (the colleague's reply, with our earlier emails under it)

It goes from the mailbox that received the reply, at the run of button 4 that switches to the new person (or
the next one), once:
  - the new person is still AUTO-OUTREACH and not yet emailed (New, a line written, or GATE2);
  - their company is open (GATE1, Contact located, Attempted to Contact, or closed as no response); a company
    still paused on In Progress waits until it goes back into the loop;
  - they have not opted out (HubSpot or Instantly's blocklist) and their company has a Country.
The person is then on "Forward sent" and their company on "Attempted to Contact"; the loop carries on from there
as for anyone reached by a forward (their reminder a week later, then "no response"). Until it has gone, button 4
never gives them the normal introduction (send.py).

data/referrals.json ("intro") remembers who is waiting and when it went: HubSpot IDs and dates only.

To queue one by hand (a reply handled before 12 Nov 2026):
    python -m outreach.referral_intro --contact <new person's HubSpot ID> --referrer <replier's HubSpot ID>
"""

import argparse
import sys

from . import referrals
from .schema import LEAD_STATUS, ORDER

TEMPLATE = "templates/referral.json"
WAITING = ("", "found", "copy_ready", "approved")  # not yet emailed
OPEN = ("", "approved", "located", "in_outreach", "no_response")
PROPS = ["email", "firstname", "lastname", "jobtitle", LEAD_STATUS, ORDER, "hs_email_optout"]


def entries(path=None):
    return (referrals.load(path).get("intro") or {})


def waiting_ids(path=None):
    """The contacts whose referral email has not gone yet: button 4 never gives them the normal introduction."""
    return {cid for cid, e in entries(path).items() if not e.get("sent") and not e.get("dropped")}


def queue(contact_id, referrer_id, company_id="", day=None, path=None):
    state = referrals.load(path)
    state.setdefault("intro", {})[str(contact_id)] = {"from": str(referrer_id), "company": str(company_id or ""),
                                                      "day": day or referrals.today_india()}
    referrals.save(state, path)


def referrer_phrase(first_name):
    first = (first_name or "").strip()
    return f"Your colleague {first}" if first else "A colleague of yours"


def note(person, company, settings, referrer_first, mailbox=None, notes=None):
    """(html, text) of the note on top of the forward."""
    from .sync import _fill
    p = person["properties"]
    greeting = (p.get("firstname") or "").strip() or " ".join(
        x for x in ((p.get("firstname") or "").strip(), (p.get("lastname") or "").strip()) if x) or "there"
    path = (settings["send"].get("templates") or {}).get("referral") or TEMPLATE
    return _fill(path, person, company, settings, notes,
                 extra={"greeting_name": greeting, "referrer": referrer_phrase(referrer_first)}, mailbox=mailbox)


def send(hs, emails_api, statuses, settings, log=print, leads=None, blocked=None, path=None, now=None):
    """Send the referral emails that are due (see the top). Returns how many went."""
    from .common import load_company_notes
    from .next_in_line import tagged_company_of
    from .reply_forward import their_reply
    from .stages import COMPANY_STOPPED, EMAILED
    from .sync import add_forwarded, forward_subject, is_blocked
    state = referrals.load(path)
    todo = {cid: e for cid, e in (state.get("intro") or {}).items() if not e.get("sent") and not e.get("dropped")}
    if not todo:
        return 0
    if emails_api is None or not hasattr(emails_api, "forward"):
        log(f"{len(todo)} referral emails wait: they need the GitHub secret INSTANTLY_EMAILS_KEY")
        return 0
    day = referrals.today_india(now)
    people = {str(r["id"]): r for r in hs.tagged_read("contacts", list(todo), PROPS)}
    owner_of, companies = tagged_company_of(hs, list(people), referrals.COMPANY_FIELDS) if people else ({}, {})
    notes = load_company_notes()
    include = bool((settings["send"].get("rotation") or {}).get("forward_include_original"))
    sent = 0

    def drop(cid, why):
        state["intro"][cid]["dropped"] = f"{day}: {why}"
        log(f"A referral email will not go ({why})")

    for cid, entry in todo.items():
        person = people.get(cid)
        if person is None:
            drop(cid, "the person is no longer AUTO-OUTREACH in HubSpot")
            continue
        p = person["properties"]
        email = (p.get("email") or "").strip().lower()
        stage = statuses.of("contacts", person)
        if stage in EMAILED or email in (leads or {}):
            drop(cid, "the person has already been emailed")
            continue
        if stage not in WAITING:
            drop(cid, f"the person's Lead Status is now {p.get(LEAD_STATUS)}")
            continue
        if str(p.get("hs_email_optout") or "").lower() == "true" or (blocked is not None and is_blocked(email, blocked)):
            drop(cid, "the person has opted out")
            continue
        company_id = owner_of.get(cid)
        company = companies.get(company_id) if company_id else None
        if company is None:
            log("A referral email waits: the person is not linked to an AUTO-OUTREACH company; tried again next run")
            continue
        cp = company.get("properties") or {}
        cstage = statuses.of("companies", company)
        if cstage == "replied":
            log(f"{cp.get('name')}: the referral email waits until the company is back in the loop")
            continue
        if cstage in COMPANY_STOPPED or cstage not in OPEN:
            drop(cid, f"its company's Lead Status is {cp.get(LEAD_STATUS)}")
            continue
        if not (cp.get("country") or "").strip():
            log(f"{cp.get('name')}: the referral email waits: fill in the company's Country")
            continue
        ref = next(iter(hs.batch_read("contacts", [entry.get("from")], ["email", "firstname"])), None)
        ref_email = ((ref or {}).get("properties") or {}).get("email") or ""
        try:
            reply, original = their_reply(emails_api, ref_email) if ref_email else (None, None)
        except Exception as err:
            log(f"{cp.get('name')}: the reply naming the new person could not be read ({str(err)[:150]}); "
                "tried again next run")
            continue
        if not reply:
            log(f"{cp.get('name')}: the reply naming the new person was not found in Instantly; tried again next run")
            continue
        html, text = note(person, cp, settings, ((ref or {}).get("properties") or {}).get("firstname"),
                          mailbox=reply.get("eaccount"), notes=notes)
        if include:
            html, text = add_forwarded(html, text, reply)
        try:
            emails_api.forward(reply, email, forward_subject(original or reply), html, text)
        except Exception as err:
            log(f"{cp.get('name')}: Instantly refused the referral email ({str(err)[:150]}); tried again next run")
            continue
        props = statuses.props_or("contacts", "forwarded", "in_outreach")
        if not str(p.get(ORDER) or "").strip():
            props = dict(props, **{ORDER: "1"})
        hs.update_tagged("contacts", [(cid, props)])
        if cstage in ("", "approved", "located", "no_response"):
            hs.update_tagged("companies", [(company_id, statuses.props("companies", "in_outreach"))])
        state["intro"][cid]["sent"] = day
        referrals.save(state, path)
        sent += 1
        log(f"{cp.get('name')}: the {p.get('jobtitle') or 'new contact'} got their first email, a forward of the "
            "reply that named them, naming the colleague who replied")
    referrals.save(state, path)
    return sent


def main(argv=None):
    a = argparse.ArgumentParser(description="Queue a referral email by hand (IDs only)")
    a.add_argument("--contact", required=True, help="HubSpot ID of the person to email")
    a.add_argument("--referrer", required=True, help="HubSpot ID of the colleague whose reply named them")
    a.add_argument("--company", default="", help="HubSpot ID of the person's company (optional)")
    args = a.parse_args(argv)
    queue(args.contact, args.referrer, args.company)
    print(f"Queued: contact {args.contact}, named by contact {args.referrer}. It goes at the next run of button 4.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
