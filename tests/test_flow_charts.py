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


def paths(moved):
    return sorted((c, p) for c, p, *_ in moved)


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
    assert paths(moved) == sorted([("Serbia", ("N", "n2")), ("Serbia", ("U", "r4")), ("Peru", ("I",)),
                                   ("Other", ("R", "y")), ("Chile", ("R", "y"))])


@pytest.mark.parametrize("status, path", [
    ("Rejected", ("U", "r1")), ("Paused", ("U", "r6")), ("Missing", ("U", "r2")), ("Apollo", ("U", "r3")),
    ("No response", ("U", "r4")), ("Said no", ("R", "g")), ("New", ("I",)), ("GATE1", ("I",)), ("Exists", ("I",)),
    ("Located", ("I",)), ("Attempted", ("N", "n2")), ("In Progress", ("R", "y")), ("Sales", ("R", "y")),
    ("Emailed", ("R", "y")),
])
def test_every_end_status_is_placed_as_agreed(status, path):
    h = history(x=("Serbia", [(status, at(10))]))
    assert paths(fc.companies_in(statuses(), h, DAY, DAY)) == [("Serbia", path)]


def test_the_other_unqualified_reasons_fold_into_ariel_s_boxes():
    more = {"Inbox": "Invalid inbox: Mail bounced, need input", "Personal": "Unqualified: Personal inbox bounced",
            "Nobody": "Unqualified: One contact inputted, which is unavailable",
            "Blocked": "Unqualified: Bounced, other reason", "Opted": "Unqualified: Employee Opted-out/Blocklist"}
    V.update(more)
    want = {"Inbox": "r5", "Personal": "r5", "Nobody": "r2", "Blocked": "r8", "Opted": "r7"}
    for status, node in want.items():
        h = history(x=("Serbia", [(status, at(10))]))
        assert paths(fc.companies_in(statuses(), h, DAY, DAY)) == [("Serbia", ("U", node))]


def test_shares_the_outcome_of_all_then_of_the_node_before():
    moved = [("X", ("U", "r4"))] * 3 + [("X", ("U", "r1"))] + [("X", ("N", "n2"))] * 4
    got = fc.shares(moved)
    assert got["U"] == 50 and got["N"] == 50 and got["r4"] == 75 and got["n2"] == 100


def test_people_emailed_counts_named_people_in_the_current_round():
    end = fc.parse_time(at(23))
    t = at(9)
    memory = {"contacts": {
        "1": {"company": "a", "inbox": True, "introduced": t},
        "2": {"company": "b", "inbox": False, "introduced": t}, "3": {"company": "b", "inbox": True, "queued": t},
        "4": {"company": "c", "inbox": False, "introduced": t}, "5": {"company": "c", "inbox": False, "queued": t},
        "6": {"company": "d", "inbox": False, "introduced": t}, "7": {"company": "d", "inbox": False, "introduced": t},
        "8": {"company": "d", "inbox": False, "introduced": t},
        "9": {"company": "e", "inbox": False, "introduced": at(9, dt.date(2026, 11, 20))},  # after the period
        "10": {"company": "f", "inbox": False, "past": [{"introduced": at(9, dt.date(2026, 10, 1))}],
               "introduced": t},
        "11": {"company": "f", "inbox": False, "past": [{"introduced": at(9, dt.date(2026, 10, 1))}]},
    }}
    got = {c: fc.emailed_node(memory, c, end) for c in "abcde"}
    assert got == {"a": "n1", "b": "n2", "c": "n3", "d": "n4", "e": "n2"}  # e: unknown before the end, 1 person
    assert fc.emailed_node(memory, "f", end, round_no=2) == "n2"  # only this round's introductions
    assert fc.emailed_node(memory, "f", end, round_no=1) == "n3"


def test_closing_within_3_days_needs_nobody_left_and_the_last_reminder_old_enough():
    rules = {"reminder": 4, "close": 3, "inbox_reminder": True}
    now = fc.parse_time(at(12))
    ago = lambda d: (now - dt.timedelta(days=d)).isoformat()  # noqa: E731
    memory = {"contacts": {
        "1": {"company": "soon", "introduced": ago(6), "reminded": ago(1)},
        "2": {"company": "late", "introduced": ago(1)},  # reminder in 3 days, then 3 more
        "3": {"company": "waiting", "introduced": ago(6), "reminded": ago(1)},
        "4": {"company": "waiting", "approved": ago(6)},  # still to introduce
        "5": {"company": "due", "introduced": ago(2)},  # reminder due in 2 days: closes in 5
        "6": {"company": "edge", "introduced": ago(4)},  # reminder due now: closes in 3 days
    }}
    got = {c: fc.closes_soon(memory, c, now, rules) for c in ("soon", "late", "waiting", "due", "edge")}
    assert got == {"soon": True, "late": False, "waiting": False, "due": False, "edge": True}
    assert not fc.closes_soon(memory, "soon", now, None)  # no chain rules: no estimate


def test_the_strongest_reply_tag_names_the_company():
    hs = FakeCRM()
    want, tagged, ids = {}, {}, []
    for name, people, tag in (("pos", [["Neutral", "Positive"], ["Negative"], []], "Positive"),
                              ("neg", [["Negative"], ["Neutral"]], "Negative"),
                              ("ref", [["Referral"]], "Neutral"), ("none", [[]], None)):
        cid = hs.add("companies", name=name)
        ids.append(cid)
        for i, tags in enumerate(people):
            pid = hs.add("contacts", email=f"{name}{i}@x.example")
            hs.links[pid] = [cid]
            tagged[str(pid)] = tags
        if tag:
            want[str(cid)] = tag
    assert fc.company_tags(hs, ids, done={}) == {}  # nothing forwarded yet
    assert fc.company_tags(hs, ids, done=tagged) == want


def test_the_three_charts_and_their_arrows():
    old = at(9, dt.date(2026, 10, 30))
    h = history(
        a=("Serbia", [("Attempted", old), ("No response", at(10))]),
        b=("Serbia", [("New", at(10))]),
        c=("Australia", [("Attempted", old), ("No response", at(10, dt.date(2026, 11, 15)))]),
        d=("Australia", [("New", at(10, dt.date(2026, 10, 5)))]),  # last month: Initial stages 100%
        e=("Peru", [("Attempted", old), ("Sales", at(10, dt.date(2026, 11, 9)))]),  # last week: Responded
    )
    a, b, c = fc.specs(DAY, h, statuses(), {"tags": {"e": "Positive"}})
    assert a["title"] == "Monday 16 November 2026: auto outreach companies assessed today"
    assert a["subtitle"] == ("AUTO-OUTREACH companies only  |  2 companies  |  arrows compare with "
                             "Sunday 15 November")
    assert a["nodes"]["all"][0] == "Companies assessed\n(all AUTO-OUTREACH)" and a["total"] == 2
    assert a["shareCol"] == 2 and a["pad"] == 40
    assert ["U", "r4", 1] not in a["links"]  # the day chart splits only Responded
    assert a["prev"]["U"] == 100 and a["prev"]["I"] == 0  # yesterday: one company, Unqualified
    assert "R" not in a["nodes"]  # nothing with 0 is drawn
    assert b["title"] == "Week so far (Mon 16 November 2026): auto outreach companies assessed"
    assert b["subtitle"].endswith("arrows compare with the same days last week (Mon 9 November)")
    assert b["prev"]["U"] == 0 and b["prev"]["I"] == 0  # last Monday: one company, and it Responded
    _, week, _ = fc.specs(dt.date(2026, 11, 9), h, statuses(), {"tags": {"e": "Positive"}})
    assert ["R", "p", 1] in week["links"]  # that Monday's own week: Responded, Positive
    assert c["title"] == "November so far (1 to 16 November 2026): auto outreach companies assessed"
    assert c["subtitle"].endswith("arrows compare with the same days last month (1 to 16 October)")
    countries = [v[0] for v in c["nodes"].values() if v[2] == 1]
    assert sorted(countries) == ["Australia", "Peru", "Serbia"] and c["total"] == 4
    assert c["prev"]["I"] == 100 and c["prev"]["U"] == 0  # last month: one company, in the initial stages
    assert ["U", "r4", 2] in c["links"] and ["R", "p", 1] in c["links"]
    assert all(v[1] == fc.PURPLE for v in c["nodes"].values() if v[2] == 1)


def test_the_week_titles_across_months_and_years():
    assert fc._span(dt.date(2026, 11, 16), dt.date(2026, 11, 18)) == "Mon 16 to Wed 18 November 2026"
    assert fc._span(dt.date(2026, 11, 30), dt.date(2026, 12, 1)) == "Mon 30 November to Tue 1 December 2026"
    assert fc._span(dt.date(2026, 12, 28), dt.date(2027, 1, 1)) == "Mon 28 December 2026 to Fri 1 January 2027"
    assert fc._span(dt.date(2026, 11, 9), dt.date(2026, 11, 11), year=False) == "Mon 9 to Wed 11 November"
    assert fc.week_days(dt.date(2026, 11, 22)) == (dt.date(2026, 11, 16), dt.date(2026, 11, 22))


def test_the_notes_close_soon_and_restart_automatically():
    from outreach.stages import RESTART_LABEL
    hs = FakeCRM()
    hs.options[("companies", "hs_lead_status")][RESTART_LABEL] = RESTART_LABEL
    st = LeadStatus(hs, restart=True)
    V["Can restart"] = RESTART_LABEL
    old = at(9, dt.date(2026, 11, 2))
    h = history(a=("Serbia", [("Attempted", old), ("Can restart", at(10))]),
                b=("Serbia", [("Attempted", old), ("Can restart", at(11))]),
                f=("Serbia", [("Attempted", old), ("No response", at(12))]),  # every round used
                n=("Serbia", [("Located", old), ("Attempted", at(9))]))
    h["b"][0]["diablo_outreach_round"] = "3"
    s = load_settings()
    s["restart"].update(enabled=True, automatic=True)
    from outreach import chain, restart
    now = fc.parse_time(at(20))
    memory = {"contacts": {"x": {"company": "n", "introduced": (now - dt.timedelta(days=6)).isoformat(),
                                 "reminded": (now - dt.timedelta(days=1)).isoformat()}}}
    ctx = {"memory": memory, "now": now, "rules": chain.config(s), "restart": restart.config(s)}
    _, week, month = fc.specs(DAY, h, st, ctx)
    assert month["notes"] == {"n2": "1 will close for no reply within 3 days",
                              "r4": "1 will restart automatically within 9 days"}  # b used all 3 rounds
    s["restart"]["automatic"] = False
    _, _, month = fc.specs(DAY, h, st, dict(ctx, restart=restart.config(s)))
    assert "r4" not in month.get("notes", {})


def test_an_initial_stages_section_only_when_there_is_one():
    h = history(x=("Serbia", [("Attempted", at(10))]))
    _, _, month = fc.specs(DAY, h, statuses())
    assert "I" not in month["nodes"]
    h = history(x=("Serbia", [("Attempted", at(10))]), y=("Serbia", [("GATE1", at(11))]))
    _, _, month = fc.specs(DAY, h, statuses())
    assert month["nodes"]["I"][0] == "Initial stages, being prepared\nand/or might need human input" and ["c0", "I", 1] in month["links"]


def test_the_same_days_last_month_stop_at_its_last_day():
    assert fc.previous_month_days(dt.date(2026, 3, 31)) == (dt.date(2026, 2, 1), dt.date(2026, 2, 28))
    assert fc.previous_month_days(dt.date(2026, 1, 16)) == (dt.date(2025, 12, 1), dt.date(2025, 12, 16))


def test_top_five_countries_and_the_rest_in_other():
    moved = [(c, ("I",)) for c in ["A"] * 6 + ["B"] * 5 + ["C"] * 4 + ["D"] * 3 + ["E"] * 2 + ["F", "Other"]]
    spec = fc.build(moved, "t", "s", {})
    names = [v[0] for v in spec["nodes"].values() if v[2] == 1]
    assert names == ["A", "B", "C", "D", "E", "Other"]
    other = next(k for k, v in spec["nodes"].items() if v[0] == "Other")
    assert sum(n for a, _, n in spec["links"] if a == other) == 2


def test_the_run_day_is_the_day_the_run_was_started_for():
    just_after = dt.datetime.combine(dt.date(2026, 11, 17), dt.time(0, 4), INDIA)
    assert fc.run_day(just_after) == DAY


def test_the_email_goes_to_alert_to_only_with_the_three_charts_inline(monkeypatch, tmp_path):
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
    assert len([p for p in msg.walk() if p.get_content_type() == "image/png"]) == 3
    assert ["c0", "I", 1] in drawn[0]["links"] and drawn[2]["nodes"]["c0"][0] == "Australia"
    assert [d["title"].split(":")[0] for d in drawn] == ["Monday 16 November 2026", "Week so far (Mon 16 November 2026)",
                                                         "November so far (1 to 16 November 2026)"]


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


def test_countries_are_written_one_way_in_the_charts():
    # 17 Nov 2026 (Ariel): "AU", "australia" and "Australia" were three countries in the chart.
    h = history(a=("AU", [("New", at(10))]), b=("australia", [("New", at(11))]), c=("Australia", [("New", at(12))]),
                d=("Hongkong", [("New", at(12))]), e=("serbia", [("New", at(12))]))
    countries = sorted({m[0] for m in fc.companies_in(statuses(), h, DAY, DAY)})
    assert countries == ["Australia", "Hong Kong", "Serbia"]
    from outreach.countries import uniform
    assert uniform("AU") == uniform(" AUSTRALIA ") == "Australia" and uniform("narnia land") == "Narnia Land"


def test_a_sample_goes_now_to_alert_to_only_marked_as_a_sample(monkeypatch, tmp_path):
    hs = FakeCRM()
    cid = hs.add("companies", name="Kadac", country="Australia",
                 hs_lastmodifieddate=str(int(fc.parse_time(at(12)).timestamp() * 1000)), hs_lead_status=V["Located"])
    hs.past = {("companies", cid): hist(("GATE1", at(9, dt.date(2026, 11, 2))), ("Located", at(12)))}
    monkeypatch.setenv("ALERT_TO", "amodh@example.com")
    monkeypatch.setenv("DAILY_REPORT_TO", "everyone@example.com")
    monkeypatch.setenv("DAILY_REPORT_APP_PASSWORD", "app-password")
    smtp = FakeSMTP()
    now = fc.parse_time(at(15))  # 3 PM India time on Monday 16 November: the day so far
    fc.run("test", load_settings(), hs, out_dir=tmp_path, log=quiet, smtp=smtp, sample=True, now=now,
           draw=lambda spec, png: Path(png).write_bytes(b"\x89PNG fake") and png)
    msg = smtp.sent[0]
    assert msg["To"] == "amodh@example.com"
    assert msg["Subject"] == "SAMPLE: Outreach flow charts - 16 November 2026"
    assert "data up to 15:00 India time on Monday 16 November 2026" in msg.get_body(("plain",)).get_content()
