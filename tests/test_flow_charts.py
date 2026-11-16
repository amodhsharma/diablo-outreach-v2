"""16 Nov 2026 (Ariel): the nightly flow charts email to Amodh: each AUTO-OUTREACH company's path through its
Lead Statuses in the day and in the month so far, read from HubSpot's history."""

import datetime as dt
import shutil
from pathlib import Path

import pytest

from outreach import flow_charts as fc
from outreach.common import load_settings
from outreach.daily_log import INDIA
from outreach.stages import LeadStatus

from .fakes import FakeCRM
from .test_daily_report import FakeSMTP, quiet

DAY = dt.date(2026, 11, 16)
START, END = fc.window(DAY, DAY)
MONTH_START, _ = fc.window(DAY.replace(day=1), DAY)

V = {"New": "New", "GATE1": "GATE1: Approved for outreach", "Located": "Contact located. Queued for processing",
     "Attempted": "Attempted to Contact", "In Progress": "In Progress", "Sales": "END: Forwarded to Sales Team",
     "No response": "Contacted, but no response, unqualified", "Exists": "Contact exists, not AUTO-OUTREACH",
     "Missing": "Missing Info", "Apollo": "Missing info on Apollo", "Rejected": "Unqualified",
     "Paused": "Unqualified: Channel no longer targeted", "Emailed": "Emailed",
     "Said no": "Unqualified: Employee response negative"}


def at(hour, day=DAY):
    """An India time on that day, as HubSpot gives it (ISO, UTC)."""
    return dt.datetime.combine(day, dt.time(hour), INDIA).astimezone(dt.timezone.utc).isoformat()


def hist(*moves):
    """[(status, time)] oldest first -> HubSpot's order (newest first)."""
    return [(V[s], t) for s, t in reversed(moves)]


def path(*moves, created=None, tagged=None, start=START, end=END):
    statuses = LeadStatus(FakeCRM())
    source = [("AUTO-OUTREACH", tagged)] if tagged else []
    made = fc.parse_time(created) if created else fc.parse_time(at(9, dt.date(2026, 1, 29)))
    if created and not tagged:
        source = [("AUTO-OUTREACH", created)]  # tagged by research when it was created
    return fc.company_path(statuses, made, hist(*moves), source, start, end)


def test_a_company_research_found_today_starts_at_research():
    t = at(10)
    assert path(("New", t), ("GATE1", at(11)), ("Located", at(12)), created=t) == \
        ["Research", "New", "GATE1", "Located"]


def test_a_company_from_before_starts_where_it_was_and_only_todays_moves_count():
    old = at(9, dt.date(2026, 11, 2))
    assert path(("GATE1", old), ("Located", at(10)), ("Attempted", at(13))) == ["GATE1", "Located", "Attempted"]
    assert path(("GATE1", old)) is None  # it did not move today
    assert path(("GATE1", old), ("Located", at(9, dt.date(2026, 11, 17)))) is None  # tomorrow does not count
    # The month chart starts on the 1st.
    assert path(("New", at(9, dt.date(2026, 10, 30))), ("GATE1", old), ("Located", at(10)),
                start=MONTH_START) == ["New", "GATE1", "Located"]


@pytest.mark.parametrize("moves, expected", [
    ((("Exists", at(1)), ("GATE1", at(10))), ["Contact exists", "Back to GATE1"]),
    ((("Missing", at(1)), ("GATE1", at(10))), ["Missing Info", "Back to GATE1"]),
    ((("Apollo", at(1)), ("New", at(10))), ["No Apollo", "Back to New"]),
    ((("Located", at(1)), ("GATE1", at(10))), ["Located", "Back to GATE1"]),
    ((("In Progress", at(1)), ("Attempted", at(10))), ["In Progress", "Back to Attempted"]),
    ((("No response", at(1)), ("Attempted", at(10))), ["No response", "Reopened (backlog)"]),
    ((("Paused", at(1)), ("New", at(10))), ["Channel paused", "Back to New"]),
    ((("Located", at(1)), ("Attempted", at(9)), ("Located", at(10)), ("Attempted", at(11))),
     ["Located", "Attempted", "Back"]),
])
def test_every_backward_move_ends_the_path_there(moves, expected):
    yesterday = [(s, at(9, dt.date(2026, 11, 15))) for s, _ in moves[:1]]
    assert path(*yesterday, *moves[1:]) == expected


def test_dead_ends_side_steps_and_team_statuses():
    old = at(9, dt.date(2026, 11, 1))
    assert path(("Exists", old), ("Missing", at(10))) == ["Contact exists", "Missing Info"]
    assert path(("Attempted", old), ("No response", at(10)), ("Paused", at(11))) == \
        ["Attempted", "No response", "Channel paused"]
    assert path(("Attempted", old), ("Paused", at(10)), ("No response", at(11))) == ["Attempted", "Channel paused"]
    assert path(("In Progress", old), ("Sales", at(10))) == ["In Progress", "END Sales"]
    assert path(("Attempted", old), ("Said no", at(10))) == ["Attempted", "Said no"]
    assert path(("In Progress", old), ("Emailed", at(10))) == ["In Progress", "Team"]


def test_a_company_tagged_by_hand_today_starts_at_its_status_when_tagged():
    long_ago = at(9, dt.date(2026, 3, 1))
    # It was the team's ("Emailed") when tagged at 10, then approved: it starts at GATE1.
    assert path(("Emailed", long_ago), ("GATE1", at(10)), ("Located", at(12)), tagged=at(10)) == ["GATE1", "Located"]
    # Moves before it was tagged do not count.
    assert path(("New", long_ago), ("GATE1", at(8)), ("Located", at(12)), tagged=at(10)) == ["GATE1", "Located"]
    # Tagged only after the day: not in that day's chart.
    assert path(("New", long_ago), ("GATE1", at(8)), tagged=at(10, dt.date(2026, 11, 17))) is None


def test_countries_top_five_and_the_rest_and_no_country_go_to_other():
    moved = [(c, ["New", "GATE1"]) for c in ["Serbia"] * 6 + ["Colombia"] * 5 + ["Georgia"] * 4 + ["Peru"] * 3
             + ["Chile"] * 2 + ["Mexico", "Other", "Other"]]
    rows = fc.as_paths(moved, countries=True)
    assert {r["country"] for r in rows} == {"Serbia", "Colombia", "Georgia", "Peru", "Chile", "Other"}
    assert sum(r["n"] for r in rows if r["country"] == "Other") == 3
    assert all("country" not in r for r in fc.as_paths(moved))


def test_titles_and_subtitles():
    a, b = fc.specs(DAY, [("Serbia", ["New", "GATE1"])] * 3, [("Serbia", ["New", "GATE1"])] * 7)
    assert a["title"] == "Today, Monday 16 November 2026: where our auto outreach companies moved"
    assert a["subtitle"] == "AUTO-OUTREACH companies only  |  3 companies moved  |  % = share of the step before"
    assert b["title"] == "November so far (1 to 16 November): where our auto outreach companies moved"
    assert "7 companies moved  |  top 5 countries + Other" in b["subtitle"]
    assert "Sample" not in a["subtitle"] + b["subtitle"]


def test_the_run_day_is_the_day_the_run_was_started_for():
    just_after = dt.datetime.combine(dt.date(2026, 11, 17), dt.time(0, 4), INDIA)
    assert fc.run_day(just_after) == DAY
    assert fc.run_day(dt.datetime.combine(DAY, dt.time(23, 59), INDIA)) == DAY


def test_the_email_goes_to_alert_to_only_with_both_charts_inline(monkeypatch, tmp_path):
    hs = FakeCRM()
    cid = hs.add("companies", name="Kadac", country="Australia", createdate=at(1, dt.date(2026, 10, 29)),
                 hs_lastmodifieddate=str(int(fc.parse_time(at(12)).timestamp() * 1000)), hs_lead_status=V["Located"])
    hs.past = {("companies", cid): hist(("GATE1", at(9, dt.date(2026, 11, 2))), ("Located", at(12)))}
    monkeypatch.setenv("ALERT_TO", "amodh@example.com")
    monkeypatch.setenv("DAILY_REPORT_TO", "everyone@example.com")
    monkeypatch.setenv("DAILY_REPORT_APP_PASSWORD", "app-password")
    drawn = []

    def draw(spec, png):
        drawn.append(spec)
        Path(png).write_bytes(b"\x89PNG fake")
        return png
    smtp = FakeSMTP()
    result = fc.run("test", load_settings(), hs, day=DAY, out_dir=tmp_path, log=quiet, smtp=smtp, draw=draw)
    assert result["sent"] and len(smtp.sent) == 1
    msg = smtp.sent[0]
    assert msg["To"] == "amodh@example.com" and msg["Subject"] == "Outreach flow charts - 16 November 2026"
    assert "admin@diablosnosugar.com" in msg["From"]
    images = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(images) == 2
    assert drawn[0]["paths"] == [{"path": ["GATE1", "Located"], "n": 1}]
    assert drawn[1]["paths"] == [{"path": ["GATE1", "Located"], "n": 1, "country": "Australia"}]


def test_a_day_with_no_moves_says_so_without_a_chart(monkeypatch, tmp_path):
    monkeypatch.setenv("ALERT_TO", "amodh@example.com")
    monkeypatch.setenv("DAILY_REPORT_APP_PASSWORD", "app-password")
    smtp = FakeSMTP()
    fc.run("test", load_settings(), FakeCRM(), day=DAY, out_dir=tmp_path, log=quiet, smtp=smtp,
           draw=lambda spec, png: pytest.fail("nothing to draw"))
    assert "no AUTO-OUTREACH company changed status" in smtp.sent[0].get_body(("plain",)).get_content()


@pytest.mark.skipif(not (shutil.which("node") and (fc.RENDER.parent / "node_modules").exists()),
                    reason="the chart packages are installed only where charts are drawn")
def test_the_renderer_draws_a_png(tmp_path):
    a, b = fc.specs(DAY, [(None, ["Research", "New"]), (None, ["GATE1", "Located", "Attempted", "Back"]),
                          (None, ["Attempted", "Team"]), (None, ["Contact exists", "Missing Info"])],
                    [("Serbia", ["New", "GATE1", "Contact exists", "Missing Info"]),
                     ("Peru", ["Research", "New", "GATE1"]), ("Other", ["No response", "Reopened (backlog)"])])
    for spec in (a, b):
        png = fc.render(spec, tmp_path / "x.png")
        assert png.read_bytes()[:4] == b"\x89PNG"
