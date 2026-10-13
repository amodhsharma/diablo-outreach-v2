"""Offline tests for the automatic city list (button 2g)."""

from outreach import auto_markets as am
from outreach import research_queue as rq

CFG = {"enabled": True, "channels": "distributors, wholesalers, retailers", "companies_wanted": 30,
       "max_per_day": 1, "pause_when_awaiting_review": 100, "exclude_countries": ["Canada", "Germany"]}
POOL = [{"location": "Toronto, Canada"}, {"location": "Dublin, Ireland"}, {"location": "Berlin, Germany"},
        {"location": "Leeds, United Kingdom"}, {"location": "Lima, Peru"}]


def done_dublin():
    rows = []
    rq.add(rows, "Dublin, Ireland", "distributors", added_by="ariel", on="2026-10-07")
    rows[0]["status"] = rq.DONE
    return rows


def test_adds_the_first_city_not_left_out_or_already_researched():
    rows = done_dublin()
    job_id, message = am.top_up(rows, POOL, CFG, awaiting_review=5, today="2026-10-12")
    assert job_id == "J0002" and "Leeds, United Kingdom" in message
    new = [r for r in rows if r["job_id"] == job_id]
    assert [r["channel"] for r in new] == ["distributors", "wholesalers", "retailers"]
    assert all(r["added_by"] == am.AUTO_BY and r["companies_wanted"] == "30" for r in new)


def test_waits_while_there_is_work_or_a_backlog():
    rows = done_dublin()
    assert am.top_up(rows, POOL, CFG, 5, "2026-10-12")[0]
    for r in rows:
        r["status"] = rq.DONE if r["status"] == rq.WAITING else r["status"]
    job, message = am.top_up(rows, POOL, CFG, 5, "2026-10-12")
    assert job is None and "already been added" in message  # one a day
    assert am.top_up(rows, POOL, CFG, 5, "2026-10-13")[0] == "J0003"  # next day: Lima
    for r in rows:
        r["status"] = rq.DONE
    rq.add(rows, "Paris, France", "retailers", added_by="ariel", on="2026-10-14")
    assert am.top_up(rows, POOL, CFG, 5, "2026-10-14")[0] is None  # queue has work
    rows[-1]["status"] = rq.DONE
    job, message = am.top_up(rows, POOL, CFG, 150, "2026-10-14")
    assert job is None and "150 companies are waiting for review" in message
    assert am.top_up(rows, POOL, dict(CFG, enabled=False), 5, "2026-10-14")[0] is None
    job, message = am.top_up(rows, POOL, CFG, 5, "2026-10-14")
    assert job is None and "Every city" in message


def test_markets_added_by_hand_run_first():
    rows = []
    rq.add(rows, "Leeds, United Kingdom", "retailers", added_by=am.AUTO_BY, on="2026-10-12")
    rq.add(rows, "Paris, France", "retailers", added_by="ariel", on="2026-10-13")
    assert rq.waiting_job(rows)[0] == "J0002"


def test_the_real_list_is_valid():
    pool = am.load_pool()
    assert len(pool) > 200
    for line in pool:
        rq.check_country(rq.capitalise(line["location"]))
    assert {line["region"] for line in pool} == {"UK", "EU", "Canada", "South America"}


def test_excluded_countries_are_never_researched(tmp_path, monkeypatch):
    import pytest
    from outreach import countries
    real = rq.excluded_countries()
    for name in ("Belgium", "Canada", "United Arab Emirates", "Lithuania", "Uzbekistan", "South Korea", "Palestine"):
        assert name in real
    assert all(countries.find(n) for n in real)  # every line is a country we know
    with pytest.raises(rq.QueueError, match="do not look for leads"):
        rq.add([], "Ghent, Belgium", "distributors")
    with pytest.raises(rq.QueueError):
        rq.add([], "Dubai, UAE", "retailers")
    rows = []
    rq.add(rows, "Paris, France", "retailers")  # others still fine
    pool = [{"location": "Ghent, Belgium"}, {"location": "Riga, Latvia"}, {"location": "Porto, Portugal"}]
    assert am.next_city([], pool) == "Porto, Portugal"


def test_awaiting_review_counts_only_auto_outreach_companies():
    from .fakes import FakeCRM
    hs = FakeCRM()
    hs.add("companies", name="A", hs_lead_status="New")
    hs.add("companies", name="B", hs_lead_status="GATE1: Approved for outreach")
    hs.add("companies", tagged=False, name="Team", hs_lead_status="New")  # the team's own lead
    assert am.awaiting_review_count("test", hs) == 1
