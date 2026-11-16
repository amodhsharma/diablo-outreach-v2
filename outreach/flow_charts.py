"""The nightly flow charts email (agreed 16 Nov 2026, Ariel).

Every night at 23:59 India time, a new email to Amodh only (the GitHub secret ALERT_TO), from the same
mailbox as the 9 AM summary, with two Sankey charts of how AUTO-OUTREACH companies moved through their
company Lead Statuses:
  - Chart A: that day (00:00 to 23:59 India time);
  - Chart B: the month so far, from the 1st up to and including that day, with a first column for the
    country (the top 5 countries, the rest and companies with no Country as "Other").
The 9 AM summary email is not changed in any way. HubSpot is only read; nothing is changed anywhere.

Where the numbers come from: the history of each company's Lead Status in HubSpot (every change with its
time), for AUTO-OUTREACH companies only. Contacts are not charted. For each company, its path in the
period:
  - created in the period by research: it starts at "Research" (Research -> New);
  - tagged AUTO-OUTREACH by hand in the period: it starts at its status when it was tagged;
  - otherwise: it starts at its status at the start of the period (the 1st, or 00:00 for the day chart).
  A start on a status the pipeline does not use (a team status, or empty) starts at its next status instead.
Only companies with at least one move are charted. Loops are not allowed in a Sankey, so every backward
move ends the company's path there, in brown (16 Nov 2026, Ariel): back to GATE1 = "Back in the approved
queue", back to New = "Back for your review", In Progress back to Emailed = "Back to emailing", No reply
back to Emailed = "Reopened: more people to email", anything else = "Back to an earlier step". A move out
of "Nobody found on Apollo", "Nobody usable found" or "Only manual contacts" into the main line counts as
going back too (its approval or review starts again). A path that ends on a stage still in progress gets
a "Waiting" ending in the chart.

The charts are drawn by outreach/charts/render.js (Node, d3-sankey and resvg) as PNG images inside the
email body. Usage:
    python -m outreach.flow_charts --target live [--day 2026-11-16] [--preview]
Without --day: the India day of the run (a run that starts just before midnight and reaches this step
just after it still charts the day it was started for).
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from .common import PipelineError, check_target, load_settings, step_summary
from .daily_log import INDIA
from .daily_report import DEFAULTS, recipients
from .hubspot_client import HubSpot
from .next_in_line import parse_time
from .schema import LEAD_STATUS, TAG, TAG_PROPERTY
from .stages import TEAM, LeadStatus

RENDER = Path(__file__).resolve().parent / "charts" / "render.js"
# A run started at 23:59 reaches this step a few minutes later: it still charts the day it was started for.
LATE_MINUTES = 45
# A company tagged AUTO-OUTREACH within this many minutes of being created was added by research.
CREATED_TAGGED_MINUTES = 30

NODE = {"found": "New", "approved": "GATE1", "located": "Located", "in_outreach": "Attempted",
        "replied": "In Progress", "sales": "END Sales", "missing_apollo": "No Apollo",
        "contact_exists": "Contact exists", "missing_info": "Missing Info", "closed": "Rejected",
        "said_no": "Said no", "opted_out": "Opted out", "no_response": "No response",
        "invalid_inbox": "Inbox bounced", "personal_bounced": "Person bounced", "redirected_none": "No one left",
        "bounced_other": "Blocked/bounced", "channel_paused": "Channel paused", TEAM: "Team"}
MAIN = {"Research": 0, "New": 1, "GATE1": 2, "Located": 3, "Attempted": 4, "In Progress": 5, "END Sales": 6}
SIDE = {"No Apollo": 1, "Contact exists": 2, "Missing Info": 3}
# The dead ends, in a fixed order: a move from one to a later one is drawn, a move back is not (it would
# make a loop between two companies), so the company stays where it was.
DEAD = {name: i for i, name in enumerate(["No response", "Said no", "Opted out", "Person bounced", "Inbox bounced",
                                          "Blocked/bounced", "No one left", "Rejected", "Channel paused", "Team"])}
BACK = {"GATE1": "Back to GATE1", "New": "Back to New", "Attempted": "Back to Attempted"}
TOP_COUNTRIES = 5


def run_day(now=None):
    """The India day this run charts."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now.astimezone(INDIA) - dt.timedelta(minutes=LATE_MINUTES)).date()


def window(first, last):
    """(start, end) in UTC of the India dates first to last (inclusive)."""
    start = dt.datetime.combine(first, dt.time(), INDIA)
    end = dt.datetime.combine(last + dt.timedelta(days=1), dt.time(), INDIA)
    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def step(path, nxt):
    """Add one Lead Status move to a path. Returns False when the path ends here (a backward move, now
    added as its ending, or a move that cannot be drawn)."""
    cur = path[-1]
    if nxt == cur:
        return True
    if nxt in MAIN:
        if cur in MAIN and MAIN[nxt] > MAIN[cur]:
            path.append(nxt)
            return True
        if cur == "No response" and nxt == "Attempted":
            path.append("Reopened (backlog)")
        else:
            path.append(BACK.get(nxt, "Back"))
        return False
    if nxt in SIDE:
        if cur in MAIN or (cur in SIDE and SIDE[nxt] > SIDE[cur]):
            path.append(nxt)
            return True
        if cur in SIDE:  # e.g. Missing Info -> Only manual contacts: cannot be drawn without a loop
            return False
        path.append("Back")  # a dead end back to a waiting status
        return False
    if nxt in DEAD:
        if cur in DEAD and DEAD[nxt] <= DEAD[cur]:
            return False
        path.append(nxt)
        return True
    return True  # a value the chart does not know: ignored


def _tagged_at(source_past):
    """When the company was last tagged AUTO-OUTREACH (from the Lead Source history, newest first)."""
    when = None
    for value, t in source_past:
        if str(value or "").strip().upper() != TAG.upper():
            break
        when = parse_time(t) or when
    return when


def company_path(statuses, created, status_past, source_past, start, end):
    """The company's path in [start, end), or None when it did not move. status_past: [(value, time)],
    newest first."""
    changes = sorted(((parse_time(t), NODE.get(statuses.stage("companies", v)) if v not in (None, "") else None)
                      for v, t in status_past if parse_time(t)), key=lambda x: x[0])
    tagged_at = _tagged_at(source_past)
    by_research = created and tagged_at and abs((tagged_at - created).total_seconds()) <= CREATED_TAGGED_MINUTES * 60
    if created and start <= created < end and (by_research or not source_past):
        path, since = ["Research"], created - dt.timedelta(seconds=1)
    else:
        if tagged_at and tagged_at >= end:
            return None  # tagged AUTO-OUTREACH only after the period
        since = tagged_at if tagged_at and start <= tagged_at < end else start
        before = [n for when, n in changes if when <= since]
        path = [before[-1]] if before and before[-1] else []
    for when, node in changes:
        if when <= since or when >= end or not node:
            continue
        if not path:
            path = [node]  # it started on an empty status: its first status is its start
            continue
        if path[-1] == "Team" and node != "Team" and len(path) == 1:
            path = [node]  # a team status at the start: its next status is its start
            continue
        if not step(path, node):
            break
    if path and path[0] == "Team":
        return None
    return path if len(path) > 1 else None


def collect(hs, statuses, first, last, log=print):
    """[(country, path)] for every AUTO-OUTREACH company that moved from the India date first to last."""
    start, end = window(first, last)
    ms = str(int(start.timestamp() * 1000))
    rows = hs.tagged_search("companies", [{"propertyName": "hs_lastmodifieddate", "operator": "GTE", "value": ms}],
                            ["name", "country", "createdate"], max_results=10000)
    ids = [str(r["id"]) for r in rows]
    if not ids:
        return []
    status = hs.history("companies", ids, LEAD_STATUS, ["country", "createdate"])
    source = hs.history("companies", ids, TAG_PROPERTY)
    out = []
    for cid in ids:
        props, past = status.get(cid, ({}, []))
        path = company_path(statuses, parse_time(props.get("createdate")), past, (source.get(cid) or ({}, []))[1],
                            start, end)
        if path:
            out.append(((props.get("country") or "").strip() or "Other", path))
    log(f"{first} to {last}: {len(out)} AUTO-OUTREACH companies moved (of {len(ids)} changed in that time)")
    return out


def as_paths(moved, countries=False):
    """The renderer's paths: identical paths are counted together."""
    keep = set()
    if countries:
        ranked = Counter(c for c, _ in moved if c != "Other").most_common()
        keep = {c for c, _ in ranked[:TOP_COUNTRIES]}
    counts = Counter()
    for country, path in moved:
        key = ((country if country in keep else "Other") if countries else None, tuple(path))
        counts[key] += 1
    order = {c: i for i, (c, _) in enumerate(Counter(c for c, _ in moved).most_common())}
    out = []
    for (country, path), n in sorted(counts.items(), key=lambda kv: (order.get(kv[0][0], 99) if countries else 0,
                                                                       kv[0][0] == "Other", -kv[1])):
        row = {"path": list(path), "n": n}
        if countries:
            row["country"] = country
        out.append(row)
    return out


def _long(day):
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')}"


def specs(day, moved_day, moved_month):
    month = day.strftime("%B")
    sep = "  |  "
    a = {"title": f"Today, {_long(day)}: where our auto outreach companies moved",
         "subtitle": sep.join(["AUTO-OUTREACH companies only", f"{len(moved_day)} companies moved",
                               "% = share of the step before"]),
         "paths": as_paths(moved_day)}
    b = {"title": f"{month} so far (1 to {day.day} {month}): where our auto outreach companies moved",
         "subtitle": sep.join(["AUTO-OUTREACH companies only", f"{len(moved_month)} companies moved",
                               f"top {TOP_COUNTRIES} countries + Other", "% = share of the step before"]),
         "paths": as_paths(moved_month, countries=True)}
    return a, b


def render(spec, out_png):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(spec, f)
    done = subprocess.run(["node", str(RENDER), f.name, str(out_png)], capture_output=True, text=True)
    if done.returncode != 0:
        raise PipelineError(f"The chart could not be drawn: {(done.stderr or done.stdout)[-400:]}")
    return out_png


def build_email(day, charts, cfg, to):
    """charts: [(title, png path or None)]."""
    msg = EmailMessage()
    msg["Subject"] = f"Outreach flow charts - {day.day} {day.strftime('%B %Y')}"
    msg["From"] = f"{cfg['sender_name']} <{cfg['sender']}>"
    msg["To"] = ", ".join(to)
    text, parts, images = [], [], []
    for title, png in charts:
        if png:
            cid = make_msgid(domain="diablo-outreach")
            images.append((cid, png))
            parts.append(f'<p><img src="cid:{cid[1:-1]}" alt="{title}" style="max-width:100%;height:auto"></p>')
            text.append(f"{title} (chart in the HTML version of this email)")
        else:
            parts.append(f"<p>{title}: no AUTO-OUTREACH company changed status.</p>")
            text.append(f"{title}: no AUTO-OUTREACH company changed status.")
    msg.set_content("\n".join(text))
    msg.add_alternative("<html><body>" + "".join(parts) + "</body></html>", subtype="html")
    html_part = msg.get_payload()[1]
    for cid, png in images:
        html_part.add_related(Path(png).read_bytes(), maintype="image", subtype="png", cid=cid,
                              filename=Path(png).name)
    return msg


def send(msg, cfg, password, smtp=None):
    import smtplib
    import ssl
    if smtp is None:
        smtp = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=60)
        smtp.starttls(context=ssl.create_default_context())
    with smtp:
        smtp.login(cfg["sender"], password)
        smtp.send_message(msg)


def run(target, settings, hs, day=None, preview=False, out_dir=None, log=print, smtp=None, draw=render):
    check_target(hs, target)
    cfg = dict(DEFAULTS, **(settings.get("daily_report") or {}))
    day = day or run_day()
    statuses = LeadStatus(hs)
    moved_day = collect(hs, statuses, day, day, log)
    moved_month = collect(hs, statuses, day.replace(day=1), day, log)
    a, b = specs(day, moved_day, moved_month)
    out_dir = Path(out_dir or tempfile.mkdtemp())
    out_dir.mkdir(parents=True, exist_ok=True)
    charts = []
    for name, spec in (("today", a), ("month", b)):
        png = draw(spec, out_dir / f"flow_{name}_{day.isoformat()}.png") if spec["paths"] else None
        charts.append((spec["title"], png))
    step_summary(f"## Flow charts for {day.isoformat()}\n\n- {a['subtitle']}\n- {b['subtitle']}\n")
    if preview:
        log("Preview only: nothing was sent.")
        return {"sent": False, "charts": charts}
    to = recipients(os.environ.get("ALERT_TO", ""))
    password = os.environ.get("DAILY_REPORT_APP_PASSWORD", "")
    if not to or not password:
        raise PipelineError("The flow charts were not sent: add the GitHub secrets ALERT_TO (the address) and "
                            "DAILY_REPORT_APP_PASSWORD (the Google app password of the sending mailbox).")
    send(build_email(day, charts, cfg, to), cfg, password, smtp)
    log(f"Sent to {len(to)} recipient{'s' if len(to) != 1 else ''} from {cfg['sender']}.")
    return {"sent": True, "charts": charts}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", required=True, choices=["test", "live"])
    ap.add_argument("--day", help="India date YYYY-MM-DD (default: the day this run was started for)")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--out", default="flow_charts", help="folder for the PNG files")
    args = ap.parse_args(argv)
    day = dt.date.fromisoformat(args.day) if args.day else None
    try:
        run(args.target, load_settings(), HubSpot(), day=day, preview=args.preview, out_dir=args.out)
    except PipelineError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
