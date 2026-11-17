"""The nightly flow charts email to Amodh (16 Nov 2026; outcome-first design 17 Nov 2026, Ariel): every
AUTO-OUTREACH company whose Lead Status changed in the period, counted once at where it ended, split into
Unqualified / Still being worked / Passed to sales team / Taken over by the team, then the step and the reason,
with each node's % compared with the day before or the same days last month."""

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

V = {"New": "New", "GATE1": "GATE1: Approved for outreach", "Located": "Contact located. Queued for processing",
     "Attempted": "Attempted to Contact", "In Progress": "In Progress", "Sales": "END: Forwarded to Sales Team",
     "No response": "Contacted, but no response, unqualified", "Exists": "Contact exists, not AUTO-OUTREACH",
     "Missing": "Missing Info", "Apollo": "Missing info on Apollo", "Rejected": "Unqualified",
     "Paused": "Unqualified: Channel no longer targeted", "Emailed": "Emailed", "Won": "Won",
     "Said no": "Unqualified: Employee response negative"}


def at(hour, day=DAY):
    return dt.datetime.combine(day, dt.time(hour), INDIA).astimezone(dt.timezone.utc).isoformat()


def hist(*moves):
    return [(V[s], t) for s, t in reversed(moves)]


def statuses():
    return LeadStatus(FakeCRM())


def history(**companies):
    """{id: ({"country": ...}, past)} from id=(country, moves)."""
    return {cid: ({"country": country}, hist(*moves)) for cid, (country, moves) in companies.items()}


def test_each_company_is_counted_once_at_where_it_ended_the_day():
    old = at(9, dt.date(2026, 11, 2))
    h = history(
        a=("Serbia", [("GATE1", old), ("Located", at(10)), ("Attempted", at(13))]),  # ended Emailed
        b=("Serbia", [("Attempted", old), ("No response", at(10)), ("Attempted", at(11)), ("No response", at(12))]),
        c=("Peru", [("New", at(8))]),  # created today by research: it counts
        d=("Peru", [("GATE1", old)]),  # did not move today
        e=("", [("In Progress", old), ("Won", at(15))]),  # set by the team
        f=("Chile", [("Attempted", old), ("Sales", at(9))]),
        g=("Chile", [("Located", old), ("Attempted", at(9, dt.date(2026, 11, 17)))]),  # tomorrow does not count
    )
    moved = fc.companies_in(statuses(), h, DAY, DAY)
    assert sorted(moved) == sorted([("Serbia", ("S", "s4")), ("Serbia", ("U", "u3", "r5")), ("Peru", ("S", "s1")),
                                    ("Other", ("T",)), ("Chile", ("Y",))])


@pytest.mark.parametrize("status, path", [
    ("Rejected", ("U", "u1", "r1")), ("Paused", ("U", "u1", "r2")), ("Missing", ("U", "u2", "r3")),
    ("Apollo", ("U", "u2", "r4")), ("No response", ("U", "u3", "r5")), ("Said no", ("U", "u3", "r10")),
    ("New", ("S", "s1")), ("GATE1", ("S", "s2")), ("Exists", ("S", "s2")), ("Located", ("S", "s3")),
    ("Attempted", ("S", "s4")), ("In Progress", ("S", "s5")), ("Sales", ("Y",)), ("Emailed", ("T",)),
])
def test_every_end_status_is_placed_as_agreed(status, path):
    h = history(x=("Serbia", [(status, at(10))]))
    assert fc.companies_in(statuses(), h, DAY, DAY) == [("Serbia", path)]


def test_shares_first_split_of_all_then_of_the_node_before():
    moved = [("X", ("U", "u3", "r5"))] * 3 + [("X", ("U", "u1", "r1"))] + [("X", ("S", "s4"))] * 4
    got = fc.shares(moved)
    assert got["U"] == 50 and got["S"] == 50 and got["u3"] == 75 and got["r5"] == 100 and got["s4"] == 100


def test_the_charts_and_their_arrows():
    old = at(9, dt.date(2026, 10, 30))
    h = history(
        a=("Serbia", [("Attempted", old), ("No response", at(10))]),
        b=("Serbia", [("New", at(10))]),
        c=("Australia", [("Attempted", old), ("No response", at(10, dt.date(2026, 11, 15)))]),
        d=("Australia", [("New", at(10, dt.date(2026, 10, 5)))]),  # last month: Still being worked 100%
    )
    a, b = fc.specs(DAY, h, statuses())
    assert a["title"] == "Monday 16 November 2026: where today's auto outreach companies ended the day"
    assert a["subtitle"] == ("AUTO-OUTREACH companies that moved today  |  2 companies  |  arrows compare with "
                             "Sunday 15 November")
    assert a["nodes"]["all"][0] == "Companies that\nmoved today" and a["total"] == 2
    assert ["all", "U", 1] in a["links"] and ["U", "u3", 1] in a["links"] and ["u3", "r5", 1] in a["links"]
    assert a["prev"]["U"] == 100 and a["prev"]["S"] == 0  # yesterday: one company, Unqualified
    assert "Y" not in a["nodes"]  # nothing with 0 is drawn
    assert b["title"] == "November so far (1 to 16 November): where our auto outreach companies stand"
    assert b["subtitle"].endswith("arrows compare with the same days last month (1 to 16 October)")
    countries = [v[0] for v in b["nodes"].values() if v[2] == 0]
    assert sorted(countries) == ["Australia", "Serbia"] and b["total"] == 3
    assert b["prev"]["S"] == 100 and b["prev"]["U"] == 0  # last month: one company, Still being worked
    assert all(v[1] == fc.PURPLE for v in b["nodes"].values() if v[2] == 0)


def test_the_same_days_last_month_stop_at_its_last_day():
    assert fc.previous_month_days(dt.date(2026, 3, 31)) == (dt.date(2026, 2, 1), dt.date(2026, 2, 28))
    assert fc.previous_month_days(dt.date(2026, 1, 16)) == (dt.date(2025, 12, 1), dt.date(2025, 12, 16))


def test_top_five_countries_and_the_rest_in_other():
    moved = [(c, ("S", "s1")) for c in ["A"] * 6 + ["B"] * 5 + ["C"] * 4 + ["D"] * 3 + ["E"] * 2 + ["F", "Other"]]
    spec = fc.build(moved, "countries", "t", "s", {})
    names = [v[0] for v in spec["nodes"].values() if v[2] == 0]
    assert names == ["A", "B", "C", "D", "E", "Other"]
    other = next(k for k, v in spec["nodes"].items() if v[0] == "Other")
    assert sum(n for a, _, n in spec["links"] if a == other) == 2


def test_the_run_day_is_the_day_the_run_was_started_for():
    just_after = dt.datetime.combine(dt.date(2026, 11, 17), dt.time(0, 4), INDIA)
    assert fc.run_day(just_after) == DAY


def test_the_email_goes_to_alert_to_only_with_both_charts_inline(monkeypatch, tmp_path):
    hs = FakeCRM()
    cid = hs.add("companies", name="Kadac", country="Australia",
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
    assert len([p for p in msg.walk() if p.get_content_type() == "image/png"]) == 2
    assert ["S", "s3", 1] in drawn[0]["links"] and drawn[1]["nodes"]["c0"][0] == "Australia"


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
    old = at(9, dt.date(2026, 10, 30))
    h = history(a=("Serbia", [("Attempted", old), ("No response", at(10))]), b=("Serbia", [("New", at(10))]),
                c=("Peru", [("Located", old), ("Sales", at(11))]), d=("", [("Attempted", old), ("Won", at(12))]))
    for spec in fc.specs(DAY, h, statuses()):
        png = fc.render(spec, tmp_path / "x.png")
        assert png.read_bytes()[:4] == b"\x89PNG"
