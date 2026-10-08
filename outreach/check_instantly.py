"""Button 6: explain why Instantly is or is not sending, campaign by campaign, and what 4b
would do now with the contacts set to Approved to send in HubSpot.

Asks Instantly for each Diablo campaign's sending status (its own diagnosis, with a short
plain-English summary) and counts the leads by status. Writes the answer to
diagnostics/instantly_status.md and to the run's summary page. No email addresses are written:
leads are shown as counts only.

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


def lead_label(lead):
    status = LEAD_STATUS.get(lead.get("status"), f"status {lead.get('status')}")
    contacted = "emailed" if lead.get("timestamp_last_contact") else "not yet emailed"
    replied = ", replied" if (lead.get("email_reply_count") or 0) > 0 else ""
    return f"{status}, {contacted}{replied}"


def run(instantly, prefix):
    lines = [f"# Instantly sending status", "", f"Checked {now_iso()} (UTC).", ""]
    for camp in instantly.list_campaigns():
        name = camp.get("name") or ""
        if not name.startswith(prefix):
            continue
        cid = camp["id"]
        try:
            camp = {**camp, **instantly.request("GET", f"/campaigns/{cid}")}
        except InstantlyError:
            pass
        lines += [f"## {name}", "", f"- Campaign status: {CAMPAIGN_STATUS.get(camp.get('status'), camp.get('status'))}"]
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
        leads = instantly.list_leads(cid)
        counts = Counter(lead_label(l) for l in leads)
        lines.append(f"- Leads: {len(leads)}" + ("".join(f"\n  - {n} {label}" for label, n in counts.most_common())))
        steps = ((camp.get("sequences") or [{}])[0] or {}).get("steps") or []
        bodies = [len(((s.get("variants") or [{}])[0] or {}).get("body") or "") for s in steps]
        lines.append(f"- Emails in the sequence: {len(steps)} (characters in each body: {bodies})")
        lines.append("")
    return "\n".join(lines) + "\n"


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
        text = run(Instantly(), settings["sync"]["campaign_prefix"])
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
