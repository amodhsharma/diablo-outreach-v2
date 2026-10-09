"""Button 6: a health check of Instantly, in plain words.

1. Mailboxes: every sending mailbox connected to Instantly, whether it can send, how its
   warm-up is going, its sender name and daily limit, which campaigns use it, and a short list
   of anything that needs attention.
2. Campaigns: whether each Diablo campaign is sending and if not why (Instantly's own
   diagnosis), with the leads counted by status.
3. HubSpot: what 4b would do right now with the contacts set to Approved to send, and why.

Writes the answer to diagnostics/instantly_status.md and to the run's summary page. Changes
nothing in Instantly or HubSpot. No lead email addresses are written: leads are counts only.

Usage:
    python -m outreach.check_instantly
"""

import json
import os
import sys
from collections import Counter

from .common import ROOT, load_settings, now_iso
from .instantly_client import Instantly, InstantlyError

OUT = ROOT / "diagnostics" / "instantly_status.md"
CAMPAIGN_STATUS = {0: "Draft", 1: "Active", 2: "Paused", 3: "Completed", 4: "Running subsequences",
                   -99: "Suspended", -1: "Accounts unhealthy", -2: "Bounce protect"}
LEAD_STATUS = {1: "Active", 2: "Paused", 3: "Completed", -1: "Bounced", -2: "Unsubscribed", -3: "Skipped"}

# Mailboxes (Instantly API v2 account fields).
ACCOUNT_STATUS = {1: "On", 2: "Paused", 3: "Paused briefly for maintenance", -1: "Connection error",
                  -2: "Soft bounce error", -3: "Sending error"}
WARMUP_STATUS = {0: "Off", 1: "On", -1: "Banned from the warm-up network", -2: "Spam folder not found",
                 -3: "Permanently suspended"}
READY_SCORE = 95          # warm-up score a mailbox should reach before it sends campaigns
SPAM_WARNING = 0.05       # warn when 5% or more of warm-up emails land in spam
MAIN_DOMAIN = "diablosugarfree.com"  # never send cold email from the company's own domain


def lead_label(lead):
    status = LEAD_STATUS.get(lead.get("status"), f"status {lead.get('status')}")
    contacted = "emailed" if lead.get("timestamp_last_contact") else "not yet emailed"
    replied = ", replied" if (lead.get("email_reply_count") or 0) > 0 else ""
    return f"{status}, {contacted}{replied}"


def diablo_campaigns(instantly, prefix):
    """Every Diablo campaign, with its full details (mailboxes, sequence, status)."""
    out = []
    for camp in instantly.list_campaigns():
        if not (camp.get("name") or "").startswith(prefix):
            continue
        try:
            camp = {**camp, **instantly.request("GET", f"/campaigns/{camp['id']}")}
        except (InstantlyError, AttributeError):
            pass
        out.append(camp)
    return out


# ---- 1. mailboxes ----------------------------------------------------------

def mailbox_verdict(acc):
    """Ready, Warming up or Problem, with the reasons (plain words) for anything not right."""
    problems, notes = [], []
    status, warm, score = acc.get("status"), acc.get("warmup_status"), acc.get("stat_warmup_score")
    if status != 1:
        label = ACCOUNT_STATUS.get(status, f"status {status}")
        if status in (2, 3):
            problems.append(f"{label}: it sends nothing until it is switched back on")
        else:
            problems.append(f"{label}: it cannot send, and replies to it are not picked up. "
                            "Reconnect it in Instantly, Email Accounts")
    if acc.get("setup_pending"):
        problems.append("Set-up is not finished in Instantly")
    if warm in (-1, -2, -3):
        problems.append(f"Warm-up: {WARMUP_STATUS[warm]}")
    elif warm == 0:
        notes.append("Warm-up is off: keep it on, also while the mailbox sends campaigns")
    if (acc.get("email") or "").lower().endswith("@" + MAIN_DOMAIN):
        problems.append(f"This is the main company domain ({MAIN_DOMAIN}): never use it for cold email")
    if problems:
        return "Problem", problems + notes
    if score is None or score < READY_SCORE:
        shown = "no score yet" if score is None else f"score {score:g}"
        notes.insert(0, f"Warm-up {shown}: not ready for campaigns yet (aim for {READY_SCORE} or more)")
        return "Warming up", notes
    return "Ready", notes


def mailboxes_section(accounts, campaigns, analytics, settings, current_name):
    """The Mailboxes part of the report. analytics is None when Instantly would not give it."""
    used_by = {}
    for camp in campaigns:
        for email in camp.get("email_list") or []:
            used_by.setdefault(email.lower(), []).append(camp.get("name"))
    current = next((c for c in campaigns if c.get("name") == current_name), None)
    for_new = {e.lower() for e in settings["send"].get("sending_accounts") or []}

    rows, attention, tally = [], [], Counter()
    for acc in sorted(accounts, key=lambda a: (a.get("email") or "").lower()):
        email = (acc.get("email") or "").lower()
        verdict, reasons = mailbox_verdict(acc)
        tally[verdict] += 1
        camps = used_by.get(email, [])
        if verdict == "Ready":
            if current and current_name not in camps:
                reasons.append(f"Ready but not used by this month's campaign ({current_name}): open the "
                               "campaign, Settings, Accounts To Use, and add it")
            elif not current and email not in for_new:
                reasons.append("Ready but 4b will not give it to new campaigns: ask for it to be added to the "
                               "sending mailboxes")
        elif camps:
            reasons.append(f"Used by {', '.join(camps)} although it is not ready: take it out of the campaign "
                           "until it is")
        name = " ".join(x for x in (acc.get("first_name"), acc.get("last_name")) if x and x.strip())
        if not name:
            reasons.append("Sender name not set: emails show only the address. Set it in Instantly, "
                           "Email Accounts, the mailbox, Settings")
        warm = (analytics or {}).get(acc.get("email")) or (analytics or {}).get(email) or {}
        inbox, spam = warm.get("landed_inbox") or 0, warm.get("landed_spam") or 0
        if inbox + spam:
            placed = f"{inbox / (inbox + spam):.0%} inbox ({inbox} of {inbox + spam})"
            if spam / (inbox + spam) >= SPAM_WARNING:
                reasons.append(f"{spam} of {inbox + spam} warm-up emails landed in spam "
                               f"({spam / (inbox + spam):.0%})")
        else:
            placed = "no numbers yet" if analytics is not None else "could not be read"
        score = acc.get("stat_warmup_score")
        rows.append("| " + " | ".join([
            email, f"**{verdict}**", ACCOUNT_STATUS.get(acc.get("status"), str(acc.get("status"))),
            WARMUP_STATUS.get(acc.get("warmup_status"), str(acc.get("warmup_status"))),
            "none yet" if score is None else f"{score:g}", placed, name or "not set",
            "not set" if acc.get("daily_limit") is None else f"{acc['daily_limit']:g}",
            ", ".join(camps) or "none",
        ]) + " |")
        attention += [f"- **{email}**: {r}" for r in reasons]

    lines = ["## Mailboxes", ""]
    if not accounts:
        return "\n".join(lines + ["- No mailboxes are connected to Instantly.", ""]) + "\n"
    lines.append(f"{len(accounts)} mailbox{'es' if len(accounts) != 1 else ''}: {tally['Ready']} ready, {tally['Warming up']} warming up, "
                 f"{tally['Problem']} with a problem.")
    lines += ["", "### Needs attention", ""] + (attention or ["- Nothing: every mailbox looks healthy."])
    lines += ["", "### Every mailbox", "",
              "| Mailbox | Verdict | Sending | Warm-up | Warm-up score | Warm-up emails landing in inbox "
              "| Sender name | Daily limit | Campaigns using it |",
              "|---|---|---|---|---|---|---|---|---|", *rows, "",
              f"Ready means: sending on, no errors, warm-up score {READY_SCORE} or more (Instantly's health "
              "mark out of 100). The inbox numbers come from Instantly's warm-up emails between mailboxes, "
              "not from real prospects, so they are an early warning rather than a promise.", ""]
    return "\n".join(lines) + "\n"


def mailboxes(instantly, campaigns, settings):
    try:
        accounts = instantly.list_accounts()
    except InstantlyError as err:
        hint = ""
        if "scope" in str(err).lower():
            hint = ("The Instantly key cannot read mailboxes. Make a read-only Instantly key with the "
                    "scope accounts:read and save it as the GitHub secret INSTANTLY_ACCOUNTS_KEY "
                    "(steps in docs/instantly_accounts_key.md). ")
        return f"## Mailboxes\n\n- Could not be read. {hint}Instantly said: {err}\n"
    try:
        analytics = instantly.warmup_analytics([a["email"] for a in accounts if a.get("email")]) if accounts else {}
    except InstantlyError:
        analytics = None
    from .send import campaign_name
    return mailboxes_section(accounts, campaigns, analytics, settings,
                             campaign_name(settings["sync"]["campaign_prefix"]))


# ---- 2. campaigns ----------------------------------------------------------

def campaigns_section(instantly, campaigns):
    lines = []
    if not campaigns:
        lines += ["## Campaigns", "", "- No Diablo campaigns yet: 4b creates one when it first sends.", ""]
    for camp in campaigns:
        cid = camp["id"]
        lines += [f"## Campaign: {camp.get('name')}", "",
                  f"- Campaign status: {CAMPAIGN_STATUS.get(camp.get('status'), camp.get('status'))}"]
        try:
            data = instantly.request("GET", f"/campaigns/{cid}/sending-status", params={"with_ai_summary": "true"})
        except InstantlyError as err:
            data = None
            lines.append(f"- Sending status could not be read: {err}")
        summary = (data or {}).get("summary") or {}
        diag = (data or {}).get("diagnostics") or {}
        if summary:
            lines.append(f"- Instantly says: **{summary.get('status')}**. {summary.get('status_message') or ''}".rstrip())
            if summary.get("ai_summary"):
                lines.append(f"- Instantly's explanation: {summary['ai_summary']}")
            if summary.get("last_healthy_send_at"):
                lines.append(f"- Last healthy send: {summary['last_healthy_send_at']}")
        for key in ("schedule_status", "campaign_daily_limit", "new_lead_limit", "accounts_summary",
                    "leads_status", "follow_ups_waiting", "issue_tracking"):
            if key in diag and diag[key] not in (None, {}, []):
                lines.append(f"- {key}: `{json.dumps(diag[key], ensure_ascii=False)[:600]}`")
        if camp.get("email_list") is not None:
            lines.append(f"- Mailboxes it sends from: {', '.join(camp['email_list']) or 'none'}")
        leads = instantly.list_leads(cid)
        counts = Counter(lead_label(l) for l in leads)
        lines.append(f"- Leads: {len(leads)}" + ("".join(f"\n  - {n} {label}" for label, n in counts.most_common())))
        steps = ((camp.get("sequences") or [{}])[0] or {}).get("steps") or []
        bodies = [len(((s.get("variants") or [{}])[0] or {}).get("body") or "") for s in steps]
        lines.append(f"- Emails in the sequence: {len(steps)} (characters in each body: {bodies})")
        lines.append("")
    return "\n".join(lines) + "\n"


def run(instantly, settings, accounts_api=None):
    """accounts_api reads the mailboxes: a separate read-only key (INSTANTLY_ACCOUNTS_KEY) when
    set, so the key that sends emails never needs more access than it has."""
    campaigns = diablo_campaigns(instantly, settings["sync"]["campaign_prefix"])
    head = f"# Instantly health check\n\nChecked {now_iso()} (UTC).\n\n"
    return (head + mailboxes(accounts_api or instantly, campaigns, settings) + "\n"
            + campaigns_section(instantly, campaigns))


# ---- 3. HubSpot ------------------------------------------------------------

KEEP = ("Skipped", "Waiting", "[dry run]", "Instantly")


def hubspot_section(settings, target):
    """What 4b would do right now with the contacts set to Approved to send, and why."""
    from . import send
    from .hubspot_client import HubSpot
    lines = []

    def collect(text):
        for line in str(text).splitlines():
            if line.startswith(KEEP) or "contacts approved to send" in line or "wait their turn" in line:
                lines.append(f"- {line}")

    send.run(target, settings, HubSpot(), None, dry_run=True, log=collect)
    return "## Approved to send in HubSpot (what 4b would do now)\n\n" + ("\n".join(lines) or "- Nothing") + "\n"


def main(argv=None):
    settings = load_settings()
    try:
        key = os.environ.get("INSTANTLY_ACCOUNTS_KEY")
        text = run(Instantly(), settings, Instantly(api_key=key) if key else None)
    except InstantlyError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    if os.environ.get("HUBSPOT_TOKEN"):
        try:
            text += "\n" + hubspot_section(settings, os.environ.get("TARGET") or "test")
        except Exception as err:  # the Instantly part is still useful on its own
            text += f"\n## Approved to send in HubSpot\n\n- Could not be read: {err}\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
