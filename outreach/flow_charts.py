"""The nightly flow charts email (agreed 16 Nov 2026, Ariel; the outcome-first design from 17 Nov 2026).

Every night at 23:59 India time (the button "R Sankey Chart to Amodh", started by cron-job.org), a new email
to Amodh only (the GitHub secret ALERT_TO), from the same mailbox as the 9 AM summary, with two Sankey
charts as PNG images. The 9 AM summary email is not changed in any way. HubSpot is only read.

Which companies: only AUTO-OUTREACH companies whose Lead Status changed at least once in the period (a company
created in the period counts: its Lead Status was set), read from HubSpot's history of each company's Lead
Status. Each company is counted once, at the Lead Status it had at the END of the period.
  - Chart A: that day (00:00 to 23:59 India time): "Companies that moved today" | first split | step | reason
  - Chart B: the month so far (the 1st up to and including that day): country (top 5 and "Other", companies
    with no Country in "Other") | first split | step | reason

Where each end status goes (first split -> step -> reason):
  Unqualified (red):  Dropped at your review (Rejected by you, Channel no longer targeted); Dropped while
                      finding people (Nobody usable found, Nobody found on Apollo); Dropped after being
                      emailed (No reply, Said no, Asked not to be emailed, Emails bounced, Company inbox
                      bounced, Blocked by their email system, Nobody left to email)
  Still being worked: Awaiting your review (New); Approved, looking for people (GATE1, Contact exists);
                      Queued to be emailed (Contact located); Emailed, awaiting a reply (Attempted to
                      Contact); In conversation (In Progress, blue)
  Passed to sales team (green) and Taken over by the team (dark teal: any status set by hand, e.g. Won)

Each label: the count, its % (the first split: of all companies in the chart; every later node: of the node
before it) and an arrow against the same node's % in the comparison period (chart A: the day before; chart
B: the same days of the previous month, up to its last day). A node absent then compares with 0%. The
renderer (outreach/charts/render2.js: Node, d3-sankey and resvg) colours the arrow by good or bad.

Usage:
    python -m outreach.flow_charts --target live [--day 2026-11-16] [--preview]
Without --day: the India day of the run (a run that starts just before midnight and reaches this step
just after it still charts the day it was started for).
"""

import argparse
import calendar
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
from .countries import uniform
from .daily_log import INDIA
from .daily_report import DEFAULTS, recipients
from .hubspot_client import HubSpot
from .next_in_line import parse_time
from .schema import LEAD_STATUS
from .stages import TEAM, LeadStatus

RENDER = Path(__file__).resolve().parent / "charts" / "render2.js"
# A run started at 23:59 reaches this step a few minutes later: it still charts the day it was started for.
LATE_MINUTES = 45
TOP_COUNTRIES = 5

RED, LIGHT_RED, GREY, LIGHT_GREY, BLUE = "#D85A30", "#E8826A", "#5F5E5A", "#888780", "#378ADD"
GREEN, TEAL, PURPLE = "#1D9E75", "#0F6E56", "#7F77DD"

# Each first split, step and reason: id -> (label, colour, column)
NODES = {
    "U": ("Unqualified", RED, 1), "S": ("Still being worked", GREY, 1), "Y": ("Passed to\nsales team", GREEN, 1),
    "T": ("Taken over\nby the team", TEAL, 1),
    "u1": ("Dropped at\nyour review", LIGHT_RED, 2), "u2": ("Dropped while\nfinding people", LIGHT_RED, 2),
    "u3": ("Dropped after\nbeing emailed", LIGHT_RED, 2),
    "s1": ("Awaiting your review", LIGHT_GREY, 2), "s2": ("Approved, looking\nfor people", LIGHT_GREY, 2),
    "s3": ("Queued to be emailed", LIGHT_GREY, 2), "s4": ("Emailed, awaiting\na reply", LIGHT_GREY, 2),
    "s5": ("In conversation", BLUE, 2),
    "r1": ("Rejected by you", RED, 3), "r2": ("Channel no longer targeted", RED, 3),
    "r3": ("Nobody usable found", RED, 3), "r4": ("Nobody found on Apollo", RED, 3), "r5": ("No reply", RED, 3),
    "r6": ("Emails bounced", RED, 3), "r7": ("Company inbox bounced", RED, 3),
    "r8": ("Asked not to be emailed", RED, 3), "r9": ("Blocked by their\nemail system", RED, 3),
    "r10": ("Said no", RED, 3), "r11": ("Nobody left to email", RED, 3),
}
# The company Lead Status stage -> its path (first split, step, reason)
PATHS = {
    "closed": ("U", "u1", "r1"), "channel_paused": ("U", "u1", "r2"),
    "missing_info": ("U", "u2", "r3"), "missing_apollo": ("U", "u2", "r4"),
    "no_response": ("U", "u3", "r5"), "said_no": ("U", "u3", "r10"), "opted_out": ("U", "u3", "r8"),
    "personal_bounced": ("U", "u3", "r6"), "invalid_inbox": ("U", "u3", "r7"),
    "bounced_other": ("U", "u3", "r9"), "redirected_none": ("U", "u3", "r11"),
    "found": ("S", "s1"), "approved": ("S", "s2"), "contact_exists": ("S", "s2"), "located": ("S", "s3"),
    "in_outreach": ("S", "s4"), "replied": ("S", "s5"),
    "sales": ("Y",), TEAM: ("T",),
}


def run_day(now=None):
    """The India day this run charts."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now.astimezone(INDIA) - dt.timedelta(minutes=LATE_MINUTES)).date()


def window(first, last):
    """(start, end) in UTC of the India dates first to last (inclusive)."""
    start = dt.datetime.combine(first, dt.time(), INDIA)
    end = dt.datetime.combine(last + dt.timedelta(days=1), dt.time(), INDIA)
    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def end_stage(statuses, past, end):
    """The company's Lead Status stage at the end of the period, from its history (newest first)."""
    before = [(parse_time(t), v) for v, t in past if parse_time(t) and parse_time(t) < end]
    if not before:
        return None
    value = max(before, key=lambda x: x[0])[1]
    return statuses.stage("companies", value) if value not in (None, "") else None


def moved_in(past, start, end):
    """True when the Lead Status changed (or was first set) in [start, end)."""
    return any(start <= t < end for t in (parse_time(t) for _, t in past) if t)


def read_history(hs, since, log=print):
    """{company id: (properties, [(value, time)] newest first)} for every AUTO-OUTREACH company changed since."""
    ms = str(int(since.timestamp() * 1000))
    rows = hs.tagged_search("companies", [{"propertyName": "hs_lastmodifieddate", "operator": "GTE", "value": ms}],
                            ["name", "country"], max_results=10000)
    ids = [str(r["id"]) for r in rows]
    log(f"{len(ids)} AUTO-OUTREACH companies changed since {since.date().isoformat()}")
    return hs.history("companies", ids, LEAD_STATUS, ["country"]) if ids else {}


def companies_in(statuses, history, first, last):
    """[(country, path)] for every company whose Lead Status changed from the India date first to last, at the
    status it had at the end."""
    start, end = window(first, last)
    out = []
    for cid, (props, past) in history.items():
        if not moved_in(past, start, end):
            continue
        path = PATHS.get(end_stage(statuses, past, end))
        if path:  # 17 Nov 2026 (Ariel): "AU", "australia" and "Australia" are all "Australia"
            out.append((uniform(props.get("country")) or "Other", path))
    return out


def shares(moved):
    """{node id: its % (rounded as the chart shows it)}: the first split of all, every later node of its parent."""
    total = len(moved)
    counts = Counter(n for _, path in moved for n in path)
    out = {}
    for _, path in moved:
        for i, n in enumerate(path):
            base = total if i == 0 else counts[path[i - 1]]
            out[n] = round(100 * counts[n] / base) if base else 0
    return out


def build(moved, first_column, title, subtitle, compare, pad=None):
    """The renderer's input. first_column: "all" (chart A) or "countries" (chart B)."""
    nodes, links = {}, Counter()
    if first_column == "all":
        nodes["all"] = ["Companies that\nmoved today", GREY, 0]
        heads = {c: "all" for c, _ in moved}
    else:
        ranked = [c for c, _ in Counter(c for c, _ in moved if c != "Other").most_common(TOP_COUNTRIES)]
        heads = {}
        for c, _ in moved:
            heads[c] = c if c in ranked else "Other"
        order = ranked + (["Other"] if any(h == "Other" for h in heads.values()) else [])
        for i, c in enumerate(order):
            nodes[f"c{i}"] = [c, PURPLE, 0]
        ids = {c: f"c{i}" for i, c in enumerate(order)}
        heads = {c: ids[h] for c, h in heads.items()}
    for country, path in moved:
        prev = heads[country]
        for n in path:
            label, colour, col = NODES[n]
            nodes.setdefault(n, [label, colour, col])
            links[(prev, n)] += 1
            prev = n
    ordered = {k: nodes[k] for k in nodes if nodes[k][2] == 0}
    ordered.update({k: nodes[k] for k in NODES if k in nodes})  # the agreed order within each column
    spec = {"title": title, "subtitle": subtitle, "total": len(moved), "nodes": ordered,
            "links": [[a, b, n] for (a, b), n in links.items()],
            "prev": {k: compare.get(k, 0) for k in ordered if ordered[k][2] > 0}}
    if pad:
        spec["pad"] = pad
    return spec


def _long(day):
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')}"


def previous_month_days(day):
    """(first, last) of the same days of the previous month, stopping at its last day."""
    year, month = (day.year, day.month - 1) if day.month > 1 else (day.year - 1, 12)
    last = min(day.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, 1), dt.date(year, month, last)


def specs(day, history, statuses):
    sep = "  |  "
    today = companies_in(statuses, history, day, day)
    before = day - dt.timedelta(days=1)
    yesterday = companies_in(statuses, history, before, before)
    a = build(today, "all", f"{_long(day)}: where today's auto outreach companies ended the day",
              sep.join(["AUTO-OUTREACH companies that moved today", f"{len(today)} companies",
                        f"arrows compare with {before.strftime('%A')} {before.day} {before.strftime('%B')}"]),
              shares(yesterday), pad=62)
    month = companies_in(statuses, history, day.replace(day=1), day)
    p_first, p_last = previous_month_days(day)
    last_month = companies_in(statuses, history, p_first, p_last)
    name = day.strftime("%B")
    b = build(month, "countries", f"{name} so far (1 to {day.day} {name}): where our auto outreach companies stand",
              sep.join(["AUTO-OUTREACH companies only", f"{len(month)} companies",
                        f"arrows compare with the same days last month (1 to {p_last.day} {p_last.strftime('%B')})"]),
              shares(last_month))
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
    earliest, _ = window(previous_month_days(day)[0], day)  # one read covers the four periods
    a, b = specs(day, read_history(hs, earliest, log), statuses)
    out_dir = Path(out_dir or tempfile.mkdtemp())
    out_dir.mkdir(parents=True, exist_ok=True)
    charts = []
    for name, spec in (("today", a), ("month", b)):
        png = draw(spec, out_dir / f"flow_{name}_{day.isoformat()}.png") if spec["total"] else None
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
