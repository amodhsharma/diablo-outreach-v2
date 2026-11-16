"""Paused campaigns in Instantly: tell Amodh, and resume when it is safe (agreed 16 Nov 2026, Ariel, after an
Outlook outage made Instantly pause the campaigns for days without anyone noticing).

At every run of button 4 (step 1b), each Diablo campaign's status in Instantly is read:

    Instantly's status                      What happens
    Active, Completed, Draft                nothing
    Accounts Unhealthy (-1): a sending      Amodh is emailed once. It is resumed automatically when ALL of
      mailbox has a problem (e.g. Outlook     these hold: paused for at least 6 hours (send.campaign_guard
      down, a mailbox disconnected)           .resume_after_hours); every mailbox the campaign uses is
                                              connected, with no errors and a warm-up score of 95 or more;
                                              no more than 5 real bounces since the pause began (temporary
                                              ones do not count). Amodh is emailed when it is resumed, or
                                              once with the reason it cannot be yet (e.g. which mailbox)
    Paused (2): a person paused it          Amodh is emailed once; never resumed automatically
    Bounce Protect (-2)                     Amodh is emailed once; never resumed automatically
    Account Suspended (-99)                 Amodh is emailed once; never resumed automatically

At most one automatic resume a day per campaign. If a campaign is paused again within 24 hours of an
automatic resume, it is left paused and Amodh is told it needs a person.

Emails go only to the GitHub secret ALERT_TO (Amodh), from admin@diablosnosugar.com (outreach/alert.py).
data/campaign_guard.json remembers each pause (campaign ID, status, times); no names or addresses.
"""

import datetime as dt
import json
import sys

from .common import ROOT

FILE = ROOT / "data" / "campaign_guard.json"
REASON = {
    -1: "Accounts Unhealthy: Instantly paused it because a sending mailbox has a problem",
    2: "Paused: someone paused it in Instantly (or Instantly gave no specific reason)",
    -2: "Bounce Protect: Instantly paused it because too many emails bounced",
    -99: "Account Suspended: Instantly suspended the account",
}
NEVER = {2: "a person's pause is never undone automatically",
         -2: "a pause for too many bounces protects our domains, so a person must look at the bounces first",
         -99: "a suspended account needs Instantly's support"}
DEFAULTS = {"resume_after_hours": 6, "bounce_limit": 5, "repause_hours": 24}


def load(path=None):
    try:
        return json.loads((path or FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data, path=None):
    path = path or FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _ist(t):
    t = t.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30)))
    return f"{t.day} {t.strftime('%b %Y, %H:%M')} India time"


def real_bounces_since(since, log_path=None):
    """Bounces logged since the pause began (India days), without the temporary ones."""
    from . import corrupt, daily_log
    try:
        days = json.loads((log_path or daily_log.LOG_FILE).read_text(encoding="utf-8")).get("days") or {}
    except (OSError, ValueError):
        return 0
    first = daily_log.india_day(since)
    ids = {str(i) for d, kinds in days.items() if d >= first for i in (kinds.get("bounced") or [])}
    return len(ids - set(corrupt.temporary_ids()))


def mailbox_problems(campaign, accounts_api):
    """[plain-words problem per mailbox] for the mailboxes the campaign sends from; None when they cannot be read."""
    from .check_instantly import mailbox_verdict
    try:
        accounts = {(a.get("email") or "").lower(): a for a in accounts_api.list_accounts()}
    except Exception:
        return None
    problems = []
    for email in campaign.get("email_list") or []:
        acc = accounts.get(email.lower())
        if acc is None:
            problems.append(f"{email}: no longer connected to Instantly")
            continue
        verdict, reasons = mailbox_verdict(acc)
        if verdict != "Ready":
            problems.append(f"{email}: {verdict}" + (f" ({'; '.join(reasons)})" if reasons else ""))
    return problems


def run(instantly, settings, accounts_api=None, log=print, now=None, path=None, alert=None, log_path=None):
    """Check every Diablo campaign (see the top). Returns {"paused": n, "resumed": n}."""
    from . import alert as alert_module
    alert = alert or (lambda subject, text: alert_module.send(subject, text, log))
    cfg = {**DEFAULTS, **((settings.get("send") or {}).get("campaign_guard") or {})}
    prefix = settings["sync"]["campaign_prefix"]
    now = now or dt.datetime.now(dt.timezone.utc)
    state = load(path)
    out = {"paused": 0, "resumed": 0}
    for camp in instantly.list_campaigns():
        name = str(camp.get("name") or "")
        if not name.startswith(prefix):
            continue
        cid, status = str(camp["id"]), camp.get("status")
        entry = state.setdefault(cid, {"name": name, "resumed": []})
        entry["name"] = name
        if status not in REASON:
            if entry.get("since"):
                log(f"{name}: running again")
                for k in ("since", "status", "alerted", "held"):
                    entry.pop(k, None)
            continue
        out["paused"] += 1
        if entry.get("status") != status or not entry.get("since"):
            entry.update(since=_iso(now), status=status)
            for k in ("alerted", "held"):
                entry.pop(k, None)
        since = _parse(entry["since"])
        if not entry.get("alerted"):
            if status == -1:
                then = (f"It is resumed automatically once it has been paused for {cfg['resume_after_hours']} "
                        "hours, every mailbox it uses is healthy and bounces are normal. You will get an email "
                        "when that happens.")
            else:
                then = f"It is NOT resumed automatically: {NEVER[status]}. Please look at it in Instantly."
            alert(f"Partner outreach: campaign paused in Instantly ({name})",
                  f"Instantly shows the campaign \"{name}\" as paused.\n\nReason: {REASON[status]}.\n"
                  f"First seen paused: {_ist(since)}.\n\n{then}\n\nKind regards,\nDiablo Partner Outreach")
            entry["alerted"] = _iso(now)
        if status != -1:
            log(f"{name}: {REASON[status]}; left paused ({NEVER[status]})")
            continue
        resumed = [t for t in (_parse(x) for x in entry.get("resumed") or []) if t]
        last = max(resumed) if resumed else None
        if last and since - last < dt.timedelta(hours=cfg["repause_hours"]):
            if entry.get("held") != "repaused":
                alert(f"Partner outreach: campaign paused again ({name})",
                      f"The campaign \"{name}\" was resumed automatically on {_ist(last)} and Instantly paused it "
                      f"again within {cfg['repause_hours']} hours ({REASON[status]}).\n\nIt is left paused so a "
                      "person can look at the mailboxes in Instantly (Email Accounts) before it is resumed by "
                      "hand.\n\nKind regards,\nDiablo Partner Outreach")
                entry["held"] = "repaused"
            log(f"{name}: paused again soon after an automatic resume; left for a person")
            continue
        if now - since < dt.timedelta(hours=cfg["resume_after_hours"]):
            log(f"{name}: paused since {_ist(since)}; resumed automatically after {cfg['resume_after_hours']} hours "
                "if all is well")
            continue
        problems = mailbox_problems(camp, accounts_api or instantly)
        bounces = real_bounces_since(since, log_path)
        why = ""
        if problems is None:
            why = "the mailboxes could not be read from Instantly (the key needs the scope accounts:read)"
        elif problems:
            why = "these mailboxes are not healthy yet:\n- " + "\n- ".join(problems)
        elif bounces > cfg["bounce_limit"]:
            why = (f"{bounces} emails bounced since the pause began (more than {cfg['bounce_limit']}); "
                   "a person should look at the bounces first")
        if why:
            if entry.get("held") != why:
                alert(f"Partner outreach: campaign still paused ({name})",
                      f"The campaign \"{name}\" has been paused since {_ist(since)} ({REASON[status]}).\n\n"
                      f"It is not resumed yet because {why}\n\nIt is checked again at every run of button 4 and "
                      "resumed as soon as all is well.\n\nKind regards,\nDiablo Partner Outreach")
                entry["held"] = why
            log(f"{name}: not resumed yet: {why.splitlines()[0]}")
            continue
        try:
            instantly.activate_campaign(cid)
        except Exception as err:
            log(f"{name}: Instantly refused to resume it ({str(err)[:200]}); tried again next run")
            continue
        entry["resumed"] = [x for x in entry.get("resumed") or [] if _parse(x) and now - _parse(x) <
                            dt.timedelta(days=7)] + [_iso(now)]
        for k in ("since", "status", "alerted", "held"):
            entry.pop(k, None)
        out["resumed"] += 1
        alert(f"Partner outreach: campaign resumed automatically ({name})",
              f"The campaign \"{name}\" was paused by Instantly from {_ist(since)} ({REASON[-1]}).\n\n"
              f"It has been resumed automatically: every mailbox it uses is healthy again and {bounces} real "
              f"bounces were logged since the pause.\n\nKind regards,\nDiablo Partner Outreach")
        log(f"{name}: resumed automatically (paused since {_ist(since)})")
    save(state, path)
    return out


def main(argv=None):
    import argparse
    import os
    from .common import PipelineError, load_settings
    from .instantly_client import Instantly, InstantlyError
    p = argparse.ArgumentParser(description="Alert on paused Instantly campaigns and resume them when safe")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--skip-if-not-configured", action="store_true")
    args = p.parse_args(argv)
    if args.skip_if_not_configured and not os.environ.get("INSTANTLY_API_KEY"):
        print("Campaign check skipped: the Instantly key is not added yet.")
        return 0
    try:
        key = os.environ.get("INSTANTLY_ACCOUNTS_KEY")
        out = run(Instantly(), load_settings(), Instantly(api_key=key) if key else None)
    except (PipelineError, InstantlyError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print(f"Campaigns paused: {out['paused']}, resumed automatically: {out['resumed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
