"""The nightly flow charts email (agreed 16 Nov 2026, Ariel; the design of Ariel's samples from 20 Nov 2026).

Every night at 23:59 India time (the button "R Sankey Chart to Amodh", started by cron-job.org), a new email
to Amodh only (the GitHub secret ALERT_TO), from the same mailbox as the daily summary, with three Sankey
charts as PNG images: the day, the week so far (Monday to that day) and the month so far. The daily summary
email is not changed in any way. HubSpot is only read. The button's "Sample" box (20 Nov 2026) sends Amodh only the
whole daily summary (charts and Key numbers) for the Day given (a UK date; empty: today so far), marked SAMPLE.

Which companies: only AUTO-OUTREACH companies whose Lead Status changed at least once in the period (a company
created in the period counts: its Lead Status was set), read from HubSpot's history of each company's Lead
Status. Each company is counted once, at the Lead Status it had at the END of the period. A move between the two
labels of "no response" (19 Nov 2026) is not a change.

Every chart: "Companies assessed (all AUTO-OUTREACH)" -> country (top 5 and "Other"; no Country is "Other") ->
    Unqualified (red), split into: Rejected by you; Nobody usable found (also "One contact inputted, which is
        unavailable"); Nobody found on Apollo; No reply in time (also "No response: can restart" and a company
        that used all its rounds); Emails bounced (personal or company inbox); Channel no longer targeted; Asked
        not to be emailed; Blocked by their email system
    Emails sent, no reply yet (grey: Attempted to Contact; an automatic answer such as out of office is not a
        reply), split by who was emailed in its current round: Only the company inbox emailed; 1 person; 2
        people; 3 or more people (named people, from button 4's memory). A note says how many of each close for
        no reply within 3 days (nobody left to introduce, and the last reminder plus the close wait ends by then).
    Responded (forwarded to sales) (blue: In Progress, END: Forwarded to Sales Team, said no, or taken over by the
        team), split by the tag the reply was forwarded with: Positive, Negative or Neutral (said no is
        Negative; Positive wins over Negative, Negative over Neutral; no tag is Neutral)
    Initial stages, being prepared and/or might need human input (New, GATE1, Contact exists, Contact located;
        renamed 20 Nov 2026, Ariel), only when there are any.
The day chart splits only Responded (the depth of Ariel's sample). Restarts get no box of their own: a company
in its next round is wherever it stands; a note under "No reply in time" says how many will restart by
themselves (on "No response: can restart" with rounds left).

Each label: the count, its % (the outcome column: of all companies in the chart; every later node: of the node
before it) and an arrow against the same node's % in the comparison period (the day before; the same days last
week; the same days of the previous month, up to its last day). A node absent then compares with 0%. The
renderer (outreach/charts/render2.js: Node, d3-sankey and resvg) colours the arrow by good or bad.

Usage:
    python -m outreach.flow_charts --target live [--day 2026-11-16] [--preview] [--sample]
Without --day: the India day of the run (a run that starts just before midnight and reaches this step
just after it still charts the day it was started for). --sample: today so far, marked as a sample.
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

from . import chain, reply_forward, restart, send_memory
from .common import PipelineError, check_target, load_settings, step_summary
from .countries import uniform
from .daily_log import INDIA
from .daily_report import DEFAULTS, recipients
from .hubspot_client import HubSpot
from .next_in_line import contacts_by_company, parse_time
from .schema import LEAD_STATUS, ROUND
from .stages import TEAM, LeadStatus

RENDER = Path(__file__).resolve().parent / "charts" / "render2.js"
# A run started at 23:59 reaches this step a few minutes later: it still charts the day it was started for.
LATE_MINUTES = 45
TOP_COUNTRIES = 5

RED, GREY, LIGHT_GREY, BLUE = "#D85A30", "#5F5E5A", "#888780", "#378ADD"
GREEN, AMBER, PURPLE, STONE, GOLD = "#1D9E75", "#EF9F27", "#7F77DD", "#B4B2A9", "#BA7517"
DARK_GOLD, LIGHT_GOLD = "#8A5208", "#E0B36A"  # 20 Nov 2026: your input needed / no input needed

# Every node after the countries: id -> (label, colour, column), in the order they are drawn
NODES = {
    "U": ("Unqualified", RED, 2), "N": ("Emails sent, no reply yet", LIGHT_GREY, 2),  # 21 Nov 2026: one line, so its arrow is never hidden
    "R": ("Responded\n(forwarded to sales)", BLUE, 2), "I": ("Initial stages", GOLD, 2),
    "r1": ("Rejected by you", RED, 3), "r2": ("Nobody usable found", RED, 3), "r3": ("Nobody found on Apollo", RED, 3),
    "r4": ("No reply in time", RED, 3), "r5": ("Emails bounced", RED, 3), "r6": ("Channel no longer targeted", RED, 3),
    "r7": ("Asked not to be emailed", RED, 3), "r8": ("Blocked by their\nemail system", RED, 3),
    "n1": ("Only the company\ninbox emailed", STONE, 3), "n2": ("1 person emailed", STONE, 3),
    "n3": ("2 people emailed", STONE, 3), "n4": ("3 or more\npeople emailed", STONE, 3),
    "p": ("Positive", GREEN, 3), "g": ("Negative", RED, 3), "y": ("Neutral", AMBER, 3),
    "i1": ("Your input needed", DARK_GOLD, 3), "i2": ("No input needed", LIGHT_GOLD, 3),
}
# The company Lead Status stage -> (outcome, reason); None: worked out from the company (people emailed, reply tag)
PATHS = {
    "closed": ("U", "r1"), "missing_info": ("U", "r2"), "redirected_none": ("U", "r2"), "missing_apollo": ("U", "r3"),
    "no_response": ("U", "r4"), "personal_bounced": ("U", "r5"), "invalid_inbox": ("U", "r5"),
    "channel_paused": ("U", "r6"), "opted_out": ("U", "r7"), "bounced_other": ("U", "r8"),
    "in_outreach": ("N", None),
    "replied": ("R", None), "sales": ("R", None), "said_no": ("R", "g"), TEAM: ("R", None),
    # 20 Nov 2026 (Ariel): Initial stages split by whether Ariel's input is needed. New (GATE1 approval) and contacts
    # not yet AUTO-OUTREACH always need it; GATE1 and Contact located only when the channel is not known or an
    # introduction waits for GATE2 approval (worked out from the company's contacts now, context()).
    "found": ("I", "i1"), "approved": ("I", None), "contact_exists": ("I", "i1"), "located": ("I", None),
}
TAG_NODE = {"Positive": "p", "Negative": "g", "Neutral": "y", "Referral": "y"}
SOON_DAYS = 3  # "will close for no reply within 3 days"


def run_day(now=None):
    """The India day this run charts."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now.astimezone(INDIA) - dt.timedelta(minutes=LATE_MINUTES)).date()


def window(first, last, zone=None):
    """(start, end) in UTC of the dates first to last (inclusive), in India time unless another zone is given
    (20 Nov 2026: the daily summary email draws the charts for UK days)."""
    zone = zone or INDIA
    start = dt.datetime.combine(first, dt.time(), zone)
    end = dt.datetime.combine(last + dt.timedelta(days=1), dt.time(), zone)
    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def end_value(past, end):
    """The company's stored Lead Status value at the end of the period, from its history (newest first)."""
    before = [(parse_time(t), v) for v, t in past if parse_time(t) and parse_time(t) < end]
    if not before:
        return None
    return max(before, key=lambda x: x[0])[1]


def end_stage(statuses, past, end):
    """The company's Lead Status stage at the end of the period."""
    value = end_value(past, end)
    return statuses.stage("companies", value) if value not in (None, "") else None


def moved_in(past, start, end, statuses=None):
    """True when the Lead Status changed (or was first set) in [start, end). With statuses, a move between two labels
    of the same stage (19 Nov 2026: the two labels of "no response") does not count."""
    for i, (value, t) in enumerate(past):
        when = parse_time(t)
        if not when or not start <= when < end:
            continue
        if statuses is None or i + 1 >= len(past):
            return True
        before = past[i + 1][0]
        if statuses.stage("companies", value) != statuses.stage("companies", before):
            return True
    return False


def read_history(hs, since, log=print):
    """{company id: (properties, [(value, time)] newest first)} for every AUTO-OUTREACH company changed since."""
    ms = str(int(since.timestamp() * 1000))
    rows = hs.tagged_search("companies", [{"propertyName": "hs_lastmodifieddate", "operator": "GTE", "value": ms}],
                            ["name", "country", ROUND], max_results=10000)
    ids = [str(r["id"]) for r in rows]
    log(f"{len(ids)} AUTO-OUTREACH companies changed since {since.date().isoformat()}")
    return hs.history("companies", ids, LEAD_STATUS, ["country", ROUND]) if ids else {}


# ---- What each company counts as ----------------------------------------------------------------

def _rec_times(rec, current_only):
    """When this contact got their introduction (queued or sent): this round's, plus earlier rounds' unless the
    company is in a later round."""
    rounds = [rec] + ([] if current_only else list(rec.get("past") or []))
    return [t for r in rounds for t in (parse_time(r.get("queued")), parse_time(r.get("introduced"))) if t]


def emailed_node(memory, company_id, end, round_no=1):
    """n1..n4 from button 4's memory: who at the company had their introduction by `end` in its current round
    (a company in round 2 or 3 counts only that round's). Named people decide; the company inbox alone is n1.
    A company the memory does not know (emailed before 17 Nov 2026) counts as 1 person."""
    named = inbox = 0
    for rec in (memory.get("contacts") or {}).values():
        if str(rec.get("company")) != str(company_id):
            continue
        times = [t for t in _rec_times(rec, round_no > 1) if t < end]
        if not times:
            continue
        if rec.get("inbox"):
            inbox += 1
        else:
            named += 1
    if named >= 3:
        return "n4"
    if named == 2:
        return "n3"
    if named == 0 and inbox:
        return "n1"
    return "n2"


def closes_soon(memory, company_id, now, rules):
    """True when the company closes for no reply within SOON_DAYS of now: nobody at it is still waiting for their
    introduction, and the last reminder (sent, or due reminder-days after the introduction) plus the close wait
    ends by then (17 Nov 2026 chain rules)."""
    if not rules:
        return False
    recs = [r for r in (memory.get("contacts") or {}).values() if str(r.get("company")) == str(company_id)]
    last = []
    for r in recs:
        if r.get("closed"):
            continue
        intro = parse_time(r.get("introduced")) or parse_time(r.get("queued"))
        if intro is None:
            if r.get("approved"):
                return False  # someone still to introduce: the company goes on
            continue
        reminded = parse_time(r.get("reminded"))
        if reminded:
            last.append(reminded)
        elif r.get("inbox") and not rules.get("inbox_reminder", True):
            last.append(intro)
        else:
            last.append(intro + dt.timedelta(days=rules["reminder"]))
    if not last:
        return False
    return max(last) + dt.timedelta(days=rules["close"]) <= now + dt.timedelta(days=SOON_DAYS)


def company_tags(hs, company_ids, done=None):
    """{company id: "Positive" | "Negative" | "Neutral"}: the strongest tag its people's replies were forwarded with
    (reply_forward.py; data/forwarded_replies.json holds the tags per contact ID)."""
    done = reply_forward.load() if done is None else done
    if not company_ids or not done:
        return {}
    people = contacts_by_company(hs, list(company_ids))
    out = {}
    for cid, contacts in people.items():
        tags = {t for c in contacts for t in done.get(str(c["id"])) or []}
        for tag in ("Positive", "Negative", "Neutral", "Referral"):
            if tag in tags:
                out[str(cid)] = "Neutral" if tag == "Referral" else tag
                break
    return out


def companies_in(statuses, history, first, last, ctx=None):
    """[(country, path, company id, end value)] for every company whose Lead Status changed from the India date
    first to last, at the status it had at the end. path: outcome and, when known, the node after it."""
    ctx = ctx or {}
    start, end = window(first, last, ctx.get("zone"))
    out = []
    for cid, (props, past) in history.items():
        if not moved_in(past, start, end, statuses):
            continue
        value = end_value(past, end)
        stage = statuses.stage("companies", value) if value not in (None, "") else None
        base = PATHS.get(stage)
        if not base:
            continue
        outcome, then = base[0], (base[1] if len(base) > 1 else None)
        if outcome == "N":
            then = emailed_node(ctx.get("memory") or {}, cid, end, restart.round_of(props))
        elif outcome == "R" and then is None:
            then = TAG_NODE.get((ctx.get("tags") or {}).get(str(cid)), "y")
        elif outcome == "I" and then is None:
            then = (ctx.get("input") or {}).get(str(cid), "i2")
        path = (outcome,) + ((then,) if then else ())
        # 17 Nov 2026 (Ariel): "AU", "australia" and "Australia" are all "Australia"
        out.append((uniform(props.get("country")) or "Other", path, str(cid), value))
    return out


def shares(moved):
    """{node id: its % (rounded as the chart shows it)}: the outcome of all, the node after it of the outcome."""
    total = len(moved)
    counts = Counter(n for m in moved for n in m[1])
    out = {}
    for m in moved:
        path = m[1]
        for i, n in enumerate(path):
            base = total if i == 0 else counts[path[i - 1]]
            out[n] = round(100 * counts[n] / base) if base else 0
    return out


def depth(moved, day_chart):
    """The day chart splits only Responded and Initial stages (Ariel's sample of 20 Nov 2026; Initial stages from
    20 Nov 2026)."""
    if not day_chart:
        return moved
    return [(c, p if p[0] in ("R", "I") else p[:1]) + tuple(rest) for c, p, *rest in moved]


def notes(moved, ctx, statuses):
    """The brown notes: how many of each "no reply yet" node close within 3 days, and how many under "No reply in
    time" will restart by themselves."""
    out = {}
    soon = Counter()
    if ctx.get("now") is not None:
        for _, path, cid, _ in moved:
            if path[0] == "N" and len(path) > 1 and closes_soon(ctx.get("memory") or {}, cid, ctx["now"], ctx.get("rules")):
                soon[path[1]] += 1
    for n, k in soon.items():
        out[n] = f"{k} will close for no reply within {SOON_DAYS} days"
    cfg = ctx.get("restart")
    if cfg and cfg.get("automatic") and statuses.restart:
        alias = str(statuses.values("companies", "no_response")[0]).lower()
        rounds = ctx.get("rounds") or {}
        k = sum(1 for _, path, cid, value in moved if path[-1] == "r4" and str(value or "").lower() == alias
                and not restart.finished({ROUND: rounds.get(cid)}, cfg))
        if k:
            out["r4"] = f"{k} will restart automatically within {cfg['wait_days']} days"
    return out


def build(moved, title, subtitle, compare, pad=None, note=None, flag=None):
    """The renderer's input: all companies -> country (top 5 and Other) -> outcome -> the node after it."""
    nodes, links = {"all": ["Companies assessed\n(all AUTO-OUTREACH)", GREY, 0]}, Counter()
    ranked = [c for c, _ in Counter(m[0] for m in moved if m[0] != "Other").most_common(TOP_COUNTRIES)]
    order = ranked + (["Other"] if any(m[0] not in ranked for m in moved) else [])
    ids = {c: f"c{i}" for i, c in enumerate(order)}
    for c in order:
        nodes[ids[c]] = [c, PURPLE, 1]
    for m in moved:
        country, path = m[0], m[1]
        head = ids[country if country in ranked else "Other"]
        links[("all", head)] += 1
        prev = head
        for n in path:
            label, colour, col = NODES[n]
            nodes.setdefault(n, [label, colour, col])
            links[(prev, n)] += 1
            prev = n
    ordered = {k: nodes[k] for k in nodes if nodes[k][2] < 2}
    ordered.update({k: nodes[k] for k in NODES if k in nodes})  # the agreed order within each column
    spec = {"title": title, "subtitle": subtitle, "total": len(moved), "shareCol": 2, "nodes": ordered,
            "links": [[a, b, n] for (a, b), n in links.items()],
            "prev": {k: compare.get(k, 0) for k in ordered if ordered[k][2] >= 2}}
    if note:
        spec["notes"] = {k: v for k, v in note.items() if k in ordered}
    if pad:
        spec["pad"] = pad
    if flag:  # 20 Nov 2026 (Ariel): "No replies received ..." under the title
        spec["flag"] = flag
    return spec


def _long(day):
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')}"


def _span(first, last, year=True):
    """"Mon 16 to Wed 18 November 2026", "Mon 30 November to Tue 1 December 2026", or one day "Mon 16 November 2026"."""
    tail = f" {last.year}" if year else ""
    end = f"{last.strftime('%a')} {last.day} {last.strftime('%B')}{tail}"
    if first == last:
        return end
    if (first.year, first.month) == (last.year, last.month):
        start = f"{first.strftime('%a')} {first.day}"
    elif first.year == last.year:
        start = f"{first.strftime('%a')} {first.day} {first.strftime('%B')}"
    else:
        start = f"{first.strftime('%a')} {first.day} {first.strftime('%B')} {first.year}"
    return f"{start} to {end}"


def previous_month_days(day):
    """(first, last) of the same days of the previous month, stopping at its last day."""
    year, month = (day.year, day.month - 1) if day.month > 1 else (day.year - 1, 12)
    last = min(day.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, 1), dt.date(year, month, last)


def week_days(day):
    """(Monday, day) of the week so far."""
    return day - dt.timedelta(days=day.weekday()), day


def specs(day, history, statuses, ctx=None):
    """(the day, the week so far, the month so far) for the renderer."""
    ctx = dict(ctx or {})
    ctx.setdefault("rounds", {str(cid): props.get(ROUND) for cid, (props, _) in history.items()})
    sep = "  |  "
    head = "AUTO-OUTREACH companies only"

    def period(first, last, now_notes):
        moved = companies_in(statuses, history, first, last, ctx)
        here = dict(ctx, now=ctx.get("now") if now_notes else None)
        return moved, here

    def no_replies(first, last, text):
        """20 Nov 2026 (Ariel): the line under the title when nobody really replied in the period (positive,
        negative or neutral; automatic answers and opt-outs are not replies). None when the log was not read."""
        data = ctx.get("log_data")
        if data is None:
            return None
        from . import daily_log
        n, d = 0, first
        while d <= last:
            entry = daily_log.day(data, d.isoformat(), uk=bool(ctx.get("uk")))
            n += sum(len(entry.get(k) or []) for k in ("positive", "negative", "neutral"))
            d += dt.timedelta(days=1)
        return None if n else text

    today, here = period(day, day, False)
    before = day - dt.timedelta(days=1)
    yesterday, _ = period(before, before, False)
    a = build(depth(today, True), f"{_long(day)}: auto outreach companies assessed today",
              sep.join([head, f"{len(today)} companies",
                        f"arrows compare with {before.strftime('%A')} {before.day} {before.strftime('%B')}"]),
              shares(depth(yesterday, True)), pad=40,
              flag=no_replies(day, day, f"No replies received on {_long(day).rsplit(' ', 1)[0]}"))
    # 20 Nov 2026 (Ariel): the companies under "Your input needed" today, for the daily email's check against Key numbers
    a["input"] = {cid: (history.get(cid, ({}, []))[0].get("name") or "A company")
                  for _c, path, cid, _v in today if "i1" in path}

    w_first, w_last = week_days(day)
    week, here = period(w_first, w_last, True)
    lw_first, lw_last = w_first - dt.timedelta(days=7), w_last - dt.timedelta(days=7)
    last_week, _ = period(lw_first, lw_last, False)
    b = build(week, f"Week so far ({_span(w_first, w_last)}): auto outreach companies assessed",
              sep.join([head, f"{len(week)} companies",
                        f"arrows compare with the same days last week ({_span(lw_first, lw_last, year=False)})"]),
              shares(last_week), pad=48, note=notes(week, here, statuses),
              flag=no_replies(w_first, w_last, f"No replies received this week so far ({_span(w_first, w_last, year=False)})"))

    month, here = period(day.replace(day=1), day, True)
    p_first, p_last = previous_month_days(day)
    last_month, _ = period(p_first, p_last, False)
    name = day.strftime("%B")
    c = build(month, f"{name} so far (1 to {day.day} {name} {day.year}): auto outreach companies assessed",
              sep.join([head, f"{len(month)} companies",
                        f"arrows compare with the same days last month (1 to {p_last.day} {p_last.strftime('%B')})"]),
              shares(last_month), pad=48, note=notes(month, here, statuses),
              flag=no_replies(day.replace(day=1), day, f"No replies received in {name} so far"))
    return a, b, c


BAD_COLOURS = (RED, "#E8826A")  # as the renderer: for these nodes a rise is bad


def chart_lines(spec):
    """The chart written out (20 Nov 2026, Ariel: when a chart cannot be drawn, the daily email holds it as text with
    exactly the chart's words, numbers, % and arrows, notes and depth). [{"level", "label", "value", "pct", "arrow",
    "was", "good", "note"}]: level 0 the companies, 1 the countries (one line), 2 an outcome, 3 the node after it.
    arrow is "▲", "▼", "=" or None; good is True, False or None (no change)."""
    nodes = spec.get("nodes") or {}
    links = spec.get("links") or []
    total = spec.get("total") or 0
    into = Counter()
    sources = {}
    for a, b, n in links:
        into[b] += n
        sources.setdefault(b, set()).add(a)
    prev = spec.get("prev") or {}
    notes_ = spec.get("notes") or {}
    share_col = spec.get("shareCol") or 1

    def name(k):
        return " ".join(str(nodes[k][0]).split())

    def line(k, level, pct):
        out = {"level": level, "label": name(k), "value": into[k], "pct": pct, "arrow": None, "was": None,
               "good": None, "note": notes_.get(k)}
        p = prev.get(k)
        if pct is not None and p is not None:
            out["was"] = p
            if pct == p:
                out["arrow"] = "="
            else:
                up = pct > p
                out["arrow"] = "▲" if up else "▼"
                out["good"] = (not up) if nodes[k][1] in BAD_COLOURS else up
        return out

    rows = [{"level": 0, "label": name("all") if "all" in nodes else "Companies assessed", "value": total,
             "pct": None, "arrow": None, "was": None, "good": None, "note": None}]
    countries = [k for k in nodes if nodes[k][2] == 1]
    if countries:
        rows.append({"level": 1, "label": "By country: " + ", ".join(f"{name(k)} {into[k]}" for k in countries),
                     "value": None, "pct": None, "arrow": None, "was": None, "good": None, "note": None})
    for k in nodes:
        if nodes[k][2] != share_col:
            continue
        rows.append(line(k, 2, round(100 * into[k] / total) if total else 0))
        for c in nodes:
            if nodes[c][2] == share_col + 1 and sources.get(c) == {k}:
                rows.append(line(c, 3, round(100 * into[c] / into[k]) if into[k] else 0))
    return rows


def chart_text(spec):
    """The chart written out as plain text lines (see chart_lines)."""
    out = [spec.get("title", ""), spec.get("subtitle", "")] + ([spec["flag"]] if spec.get("flag") else [])
    for r in chart_lines(spec):
        pad = "  " * r["level"]
        if r["value"] is None:
            out.append(pad + r["label"])
            continue
        text = f"{pad}{r['label']}: {r['value']}" + (f" ({r['pct']}%)" if r["pct"] is not None else "")
        if r["arrow"] == "=":
            text += f" = {r['was']}%"
        elif r["arrow"]:
            text += f" {r['arrow']} was {r['was']}%"
        out.append(text)
        if r["note"]:
            out.append(pad + "  " + r["note"])
    return out


def render(spec, out_png):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(spec, f)
    done = subprocess.run(["node", str(RENDER), f.name, str(out_png)], capture_output=True, text=True)
    if done.returncode != 0:
        raise PipelineError(f"The chart could not be drawn: {(done.stderr or done.stdout)[-400:]}")
    return out_png


def build_email(day, charts, cfg, to, sample_at=None):
    """charts: [(title, png path or None)]. sample_at: the India time of a sample's data (the button's Sample box)."""
    msg = EmailMessage()
    subject = f"Outreach flow charts - {day.day} {day.strftime('%B %Y')}"
    msg["Subject"] = f"SAMPLE: {subject}" if sample_at else subject
    msg["From"] = f"{cfg['sender_name']} <{cfg['sender']}>"
    msg["To"] = ", ".join(to)
    text, parts, images = [], [], []
    if sample_at:
        line = (f"This is a sample with the data up to {sample_at.strftime('%H:%M')} India time on "
                f"{_long(sample_at.date())}. The day and the week end at that time.")
        text.append(line)
        parts.append(f"<p>{line}</p>")
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


def context(hs, settings, history, statuses, day, end, now=None):
    """What the charts need besides HubSpot's history: button 4's memory (who was emailed, and when), the reply
    tags, the rounds, the chain's timers and the restart settings."""
    now = now or dt.datetime.now(dt.timezone.utc)
    memory = send_memory.load()
    responded = []
    for cid, (_props, past) in history.items():
        if PATHS.get(end_stage(statuses, past, end), ("",))[0] == "R":
            responded.append(cid)
    try:
        tags = company_tags(hs, responded)
    except Exception:  # never stops the charts: no tag reads as Neutral
        tags = {}
    try:  # never stops the charts: without it, Initial stages reads as "No input needed"
        needs = input_needed(hs, statuses, history, end)
    except Exception:
        needs = {}
    try:
        from . import daily_log
        log_data = daily_log.load()
    except Exception:
        log_data = None
    return {"memory": memory, "tags": tags, "now": min(now, end), "rules": chain.config(settings),
            "restart": restart.config(settings), "input": needs, "log_data": log_data}


def input_needed(hs, statuses, history, end):
    """20 Nov 2026 (Ariel): {company id: "i1" or "i2"} for the companies on GATE1 or Contact located at the end of
    the period: "i1" (your input needed) when the company's channel is not known or someone there waits for GATE2
    approval ("New, Personal line filled") or is held because its record is broken (20 Nov 2026), else "i2" (no
    input needed). The contacts' Lead Status is the one they had
    at the end of the period (from their history; 20 Nov 2026, Ariel: the charts and Key numbers describe the same
    moment); the channel is read from the company now."""
    from . import channels
    from .common import load_company_notes
    ids = [cid for cid, (_p, past) in history.items() if end_stage(statuses, past, end) in ("approved", "located")]
    if not ids:
        return {}
    notes = load_company_notes()
    records = {str(r["id"]): r for r in hs.tagged_read("companies", ids, ["name", "domain", "industry_type"])}
    people = contacts_by_company(hs, ids)
    contact_ids = sorted({str(c["id"]) for cs in people.values() for c in cs or []})
    past = hs.history("contacts", contact_ids, LEAD_STATUS) if contact_ids else {}

    def stage_then(contact):
        h = (past.get(str(contact["id"])) or ({}, []))[1]
        value = end_value(h, end) if h else (contact.get("properties") or {}).get(LEAD_STATUS)
        return statuses.stage("contacts", value) if value not in (None, "") else None
    out = {}
    for cid in ids:
        props = (records.get(str(cid)) or {}).get("properties") or {}
        from . import address_checks  # 20 Nov 2026: a broken record waits for a person too
        waiting = any(stage_then(c) == "copy_ready" or (stage_then(c) == "approved" and address_checks.broken(c))
                      for c in people.get(cid) or people.get(str(cid)) or [])
        out[str(cid)] = "i1" if waiting or channels.verdict(props, notes) is None else "i2"
    return out


def draw_all(hs, settings, day, out_dir=None, log=print, draw=render, now=None, zone=None, log_data=None):
    """The three charts for `day` (in India time, or in `zone`): ([(title, png path or None)], (day, week, month)).
    Used by the button "R Sankey Chart to Amodh" and, for UK days, by the daily summary email (20 Nov 2026)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    statuses = LeadStatus(hs)
    first = min(previous_month_days(day)[0], week_days(day)[0] - dt.timedelta(days=7))
    earliest, _ = window(first, day, zone)  # one read covers the six periods
    _, end = window(day, day, zone)
    history = read_history(hs, earliest, log)
    ctx = context(hs, settings, history, statuses, day, end, now)
    ctx["zone"] = zone
    ctx["uk"] = zone is not None and zone != INDIA  # the daily summary's UK days
    if log_data is not None:
        ctx["log_data"] = log_data
    a, b, c = specs(day, history, statuses, ctx)
    out_dir = Path(out_dir or tempfile.mkdtemp())
    out_dir.mkdir(parents=True, exist_ok=True)
    charts = []
    for name, spec in (("today", a), ("week", b), ("month", c)):
        png = draw(spec, out_dir / f"flow_{name}_{day.isoformat()}.png") if spec["total"] else None
        charts.append((spec["title"], png))
    return charts, (a, b, c)


def run(target, settings, hs, day=None, preview=False, out_dir=None, log=print, smtp=None, draw=render,
        sample=False, now=None):
    check_target(hs, target)
    cfg = dict(DEFAULTS, **(settings.get("daily_report") or {}))
    now = now or dt.datetime.now(dt.timezone.utc)
    sample_at = now.astimezone(INDIA) if sample else None
    day = day or (sample_at.date() if sample_at else run_day(now))
    charts, (a, b, c) = draw_all(hs, settings, day, out_dir, log, draw, now)
    step_summary(f"## Flow charts for {day.isoformat()}" + (" (sample)" if sample else "")
                 + f"\n\n- {a['subtitle']}\n- {b['subtitle']}\n- {c['subtitle']}\n")
    if preview:
        log("Preview only: nothing was sent.")
        return {"sent": False, "charts": charts}
    to = recipients(os.environ.get("ALERT_TO", ""))
    password = os.environ.get("DAILY_REPORT_APP_PASSWORD", "")
    if not to or not password:
        raise PipelineError("The flow charts were not sent: add the GitHub secrets ALERT_TO (the address) and "
                            "DAILY_REPORT_APP_PASSWORD (the Google app password of the sending mailbox).")
    send(build_email(day, charts, cfg, to, sample_at), cfg, password, smtp)
    log(f"Sent to {len(to)} recipient{'s' if len(to) != 1 else ''} from {cfg['sender']}"
        + (" (a sample, to Amodh only)." if sample else "."))
    return {"sent": True, "charts": charts}


def sample_daily_email(target, day=None, preview=False, log=print):
    """The daily summary (00:05 UK) exactly as it would go (the three charts, Key numbers and the rest), for the UK
    date `day` (default: today so far), to ALERT_TO only (Amodh), marked SAMPLE in the subject."""
    from . import daily_report
    from .instantly_client import Instantly, InstantlyError
    from .hubspot_client import HubSpotError
    date = (day or dt.datetime.now(daily_report.DAY_ZONE).date()).isoformat()
    to = recipients(os.environ.get("ALERT_TO", ""))
    if not to and not preview:
        print("ERROR: the GitHub secret ALERT_TO (Amodh's address) is needed for a sample", file=sys.stderr)
        return 1
    try:
        accounts_key, emails_key = os.environ.get("INSTANTLY_ACCOUNTS_KEY"), os.environ.get("INSTANTLY_EMAILS_KEY")
        daily_report.run(target, load_settings(), HubSpot(), Instantly(),
                         accounts_api=Instantly(api_key=accounts_key) if accounts_key else None,
                         emails_api=Instantly(api_key=emails_key) if emails_key else None,
                         date=date, preview=preview, log=log, to=to, subject_prefix="SAMPLE: ")
    except (PipelineError, HubSpotError, InstantlyError, OSError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", required=True, choices=["test", "live"])
    ap.add_argument("--day", help="India date YYYY-MM-DD (default: the day this run was started for)")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--sample", action="store_true",
                    help="the whole daily summary email for --day (UK date; default today so far), to Amodh only")
    ap.add_argument("--out", default="flow_charts", help="folder for the PNG files")
    args = ap.parse_args(argv)
    day = dt.date.fromisoformat(args.day) if args.day else None
    if args.sample:  # 20 Nov 2026 (Ariel): the sample is the whole daily summary email (charts and Key numbers)
        return sample_daily_email(args.target, day, preview=args.preview)
    try:
        run(args.target, load_settings(), HubSpot(), day=day, preview=args.preview, out_dir=args.out,
            sample=args.sample)
    except PipelineError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
