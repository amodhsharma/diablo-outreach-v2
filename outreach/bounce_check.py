"""Bounce check, read only (agreed 17 Nov 2026, Ariel).

Button 4 stores no real reason for most bounces: it asks Instantly for the emails linked to the address,
and the "undeliverable" notice from the other side's mail server was not among them. This check finds out
where Instantly keeps those notices. For every bounced lead in the Diablo campaigns it asks Instantly in
four ways and reports which way found the notice and what the notice says:

    A  as button 4 asks today: the emails linked to the address
    B  the same, in every Unibox tab (focused and others)
    C  a search for the address, in every Unibox tab
    D  the sending mailbox's received emails in the 3 days after the send, kept when they mention the
       address (only when A to C found nothing, and for the first few bounces to compare)

Nothing is changed anywhere: HubSpot and Instantly are only read, and nothing is saved in the repository.
The run's page shows HubSpot contact IDs, our own sending mailboxes and the reasons, with every email
address in a reason replaced by <address>; never a prospect's address or name.

The reason is sorted into one of these kinds:
    Address does not exist, Domain cannot receive email, Inbox full, Blocked by their mail system,
    Temporary problem, Other reason, Reason could not be read
"""

import datetime as dt
import re
import sys
import time

from .common import step_summary
from .corrupt import FULL, _full_text, _is_notice, bounce_message, kind_of_bounce
from .next_in_line import instantly_view, parse_time

EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
# The receiving domain has no working mail system (no MX record, a DNS failure, an unknown host).
NO_MAIL = re.compile(
    r"(servfail|dns (type '?mx'? )?(lookup|error)|mx (record|lookup)|no mx\b|nxdomain|"
    r"domain (name )?(not found|does not exist|couldn'?t be found)|host (not found|unknown)|"
    r"unrouteable (address|domain)|name or service not known|no route to host)", re.I)
# A full mailbox, beyond the wordings button 4 knows (outreach/corrupt.py is not changed by this check).
FULL_MORE = re.compile(r"(inbox (is )?(full|out of storage)|out of storage|storage (space )?(is )?full|\b5\.2\.2\b|"
                       r"recipient inbox full)", re.I)
# Instantly's code for the recipient's email provider (lead.esp_code).
ESP = {0: "In queue", 1: "Google", 2: "Microsoft", 3: "Zoho", 8: "Other provider", 9: "Yahoo", 10: "Yandex",
       12: "Web.de", 13: "Libero.it", 999: "Other (own mail server)", 1000: "No mail system found"}
KINDS = (("dead", "Address does not exist"), ("no_mail", "Domain cannot receive email"), ("full", "Inbox full"),
         ("policy", "Blocked by their mail system"), ("temporary", "Temporary problem"),
         ("other", "Other reason"), ("unread", "Reason could not be read"))
METHODS = (("A", "linked to the address (as button 4 reads today)"), ("B", "linked to the address, every tab"),
           ("C", "search for the address, every tab"), ("D", "sending mailbox after the send"))
PAUSE = 3.5  # seconds between email reads: Instantly allows 20 a minute, so button 4 is never crowded out
COMPARE_FIRST = 5  # D is also tried for the first few bounces even when A to C found the notice


def mask(text):
    return EMAIL.sub("<address>", text or "")


def kind_of(text, esp=None):
    """One of KINDS for a bounce notice's text (and the provider code when no notice was found)."""
    if not (text or "").strip():
        return "no_mail" if esp == 1000 else "unread"
    if NO_MAIL.search(text):
        return "no_mail"
    if FULL.search(text) or FULL_MORE.search(text):
        return "full"
    return {"dead": "dead", "policy": "policy", "temporary": "temporary"}.get(kind_of_bounce(text), "other")


def last_step(lead):
    """(our sending mailbox, time the email went) from Instantly's lead, either may be None."""
    step = ((lead or {}).get("status_summary") or {}).get("lastStep") or {}
    when = parse_time(step.get("timestamp_executed") or (lead or {}).get("timestamp_last_contact"))
    return step.get("from"), when


def _iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Reader:
    """Reads Instantly's email list gently, and never writes."""

    def __init__(self, api, pause=PAUSE, sleep=time.sleep):
        self.api, self.pause, self.sleep, self.calls = api, pause, sleep, 0

    def emails(self, params, pages=3):
        items, cursor = [], None
        for _ in range(pages):
            p = dict(params, limit=100)
            if cursor:
                p["starting_after"] = cursor
            if self.calls:
                self.sleep(self.pause)
            self.calls += 1
            data = self.api.request("GET", "/emails", params=p) or {}
            batch = data.get("items") or []
            items.extend(batch)
            cursor = data.get("next_starting_after")
            if not cursor or not batch:
                break
        return items

    def full(self, email):
        if (email.get("body") or {}) or not email.get("id"):
            return email
        self.sleep(self.pause)
        self.calls += 1
        got = self.api.get_email(email["id"]) if hasattr(self.api, "get_email") else None
        return {**email, **got} if got else email


def _notices(items):
    return [e for e in items if e.get("ue_type") not in (1, 3) and _is_notice(e)]


def probe(reader, address, lead, try_d):
    """{method: (found, error)} and the first notice's full text."""
    sender, sent = last_step(lead)
    asks = {"A": {"lead": address}, "B": {"lead": address, "mode": "emode_all"},
            "C": {"search": address, "mode": "emode_all"}}
    found, text = {}, ""
    for m, params in asks.items():
        try:
            hits = _notices(reader.emails(params))
            found[m] = (bool(hits), None)
            if hits and not text:
                text = _full_text(reader.full(hits[0]))
        except Exception as err:  # a way Instantly refuses is itself a finding
            found[m] = (False, str(err)[:120])
    if (try_d or not any(f for f, _ in found.values())) and sender and sent:
        params = {"eaccount": sender, "mode": "emode_all", "min_timestamp_created": _iso(sent - dt.timedelta(minutes=10)),
                  "max_timestamp_created": _iso(sent + dt.timedelta(days=3))}
        try:
            hit = None
            for e in _notices(reader.emails(params, pages=5))[:15]:
                e = reader.full(e)
                if address in _full_text(e).lower():
                    hit = e
                    break
            found["D"] = (bool(hit), None)
            if hit and not text:
                text = _full_text(hit)
        except Exception as err:
            found["D"] = (False, str(err)[:120])
    return found, text


def run(hs, instantly, emails_api, settings, log=print, limit=500, sleep=time.sleep):
    prefix = settings["sync"]["campaign_prefix"]
    view = instantly_view(instantly, prefix)
    names = {c["id"]: c.get("name") or "" for c in instantly.list_campaigns()}
    bounced = sorted(((e, l) for e, l in view.items() if l.get("status") == -1),
                     key=lambda x: last_step(x[1])[1] or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
                     reverse=True)[:limit]
    log(f"{len(bounced)} bounced leads in the Diablo campaigns")
    rows = hs.tagged_read("contacts", [e for e, _ in bounced], ["email", "jobtitle"], id_property="email") \
        if bounced else []
    ids = {(r["properties"].get("email") or "").lower(): r["id"] for r in rows}
    reader = Reader(emails_api, sleep=sleep)
    out, per_method, per_kind = [], {m: 0 for m, _ in METHODS}, {k: 0 for k, _ in KINDS}
    for n, (address, lead) in enumerate(bounced):
        found, text = probe(reader, address, lead, try_d=n < COMPARE_FIRST)
        sender, sent = last_step(lead)
        esp = lead.get("esp_code")
        kind = kind_of(text, esp)
        per_kind[kind] += 1
        for m, (hit, _) in found.items():
            per_method[m] += hit
        row = {"contact": ids.get(address) or "not an AUTO-OUTREACH contact",
               "campaign": names.get(lead.get("_campaign_id"), "").replace(prefix, "").strip(" |") or "?",
               "sender": sender or "?", "sent": sent.strftime("%d %b %Y") if sent else "?",
               "provider": ESP.get(esp, f"code {esp}"), "kind": dict(KINDS)[kind],
               "found": ", ".join(m for m, (hit, _) in found.items() if hit) or "none",
               "refused": "; ".join(f"{m}: {mask(e)}" for m, (_, e) in found.items() if e),
               "reason": mask(bounce_message(text))[:160] if text else ""}
        out.append(row)
        log(f"Contact {row['contact']} | {row['campaign']} | sent {row['sent']} from {row['sender']} | "
            f"{row['provider']} | found by: {row['found']} | {row['kind']}"
            + (f" | {row['reason']}" if row["reason"] else "") + (f" | refused: {row['refused']}" if row["refused"] else ""))
    lines = ["# Bounce check (read only)", "", f"{len(out)} bounced leads read; nothing was changed.", "",
             "## Which way found the bounce notice", "", "| Way | Found |", "|---|---|"]
    lines += [f"| {m}: {label} | {per_method[m]} |" for m, label in METHODS]
    lines += ["", "## Kind of bounce", "", "| Kind | Bounces |", "|---|---|"]
    lines += [f"| {label} | {per_kind[k]} |" for k, label in KINDS]
    lines += ["", "## Every bounce", "", "| Contact | Campaign | Sent | From | Provider | Found by | Kind | Reason |",
              "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {r['contact']} | {r['campaign']} | {r['sent']} | {r['sender']} | {r['provider']} | {r['found']} | "
              f"{r['kind']} | {r['reason'].replace('|', '/')}{(' (refused: ' + r['refused'] + ')') if r['refused'] else ''} |"
              for r in out]
    step_summary("\n".join(lines))
    log(f"Found by way: {per_method}; kinds: {per_kind}; Instantly email reads: {reader.calls}")
    return {"rows": out, "methods": per_method, "kinds": per_kind}


def main(argv=None):
    import argparse
    import os
    from .common import PipelineError, check_target, load_settings
    from .hubspot_client import HubSpot
    from .instantly_client import Instantly, InstantlyError
    p = argparse.ArgumentParser(description="Read where Instantly keeps bounce notices (changes nothing)")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--limit", type=int, default=500)
    args = p.parse_args(argv)
    key = os.environ.get("INSTANTLY_EMAILS_KEY")
    if not key:
        print("ERROR: the GitHub secret INSTANTLY_EMAILS_KEY is needed to read the bounce notices", file=sys.stderr)
        return 1
    try:
        hs = HubSpot()
        check_target(hs, args.target)
        run(hs, Instantly(), Instantly(api_key=key), load_settings(), limit=args.limit)
    except (PipelineError, InstantlyError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
