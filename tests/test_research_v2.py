"""Offline tests for version 2's research parts: the queue, the skill's scripts,
the strict check, the nightly HubSpot list and the import into HubSpot."""

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from outreach import common, import_research, known_companies
from outreach import research_queue as rq

from .fakes import FakeCRM

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "outreachResearch" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_output  # noqa: E402


def quiet(_):
    pass


# ---- the queue -------------------------------------------------------------

def test_repeat_rules_match_what_ariel_agreed():
    rows = []
    rq.add(rows, "UK", "wholesalers, retailers", on="2026-10-07")
    _, new, warnings = rq.add(rows, "uk", "Wholesaler, sugar free healthy food wholesalers, distributors",
                              on="2026-10-08")
    status = {r["channel"]: r["status"] for r in new}
    assert status == {"Wholesaler": rq.ON_HOLD,  # capitals and plural ignored
                      "sugar free healthy food wholesalers": rq.WAITING,  # different wording is new
                      "distributors": rq.WAITING}  # mixed job: only the repeat is held
    assert len(warnings) == 1 and "Approve a repeat" in warnings[0]
    _, new, _ = rq.add(rows, "United Kingdom", "wholesalers", on="2026-10-08")
    assert new[0]["status"] == rq.WAITING  # Locations match as written


def test_queue_buttons_and_oldest_job_first():
    rows = []
    rq.add(rows, "India", "distributors", on="2026-10-08")
    rq.add(rows, "Kenya", "retailers, wholesalers", on="2026-10-07")
    rq.add(rows, "India", "Distributor", on="2026-10-09")
    assert [r["status"] for r in rows][-1] == rq.ON_HOLD
    job, lines = rq.waiting_job(rows)
    assert job == "J0002" and [r["channel"] for r in lines] == ["retailers", "wholesalers"]
    assert rq.waiting_job(rows, location="india")[0] == "J0001"
    rq.cancel(rows, "j0002", "retailers")
    assert rq.waiting_job(rows)[1][0]["channel"] == "wholesalers"
    rq.approve_repeat(rows, "J0003", by="ariel")
    assert rows[-1]["status"] == rq.WAITING and rows[-1]["approved_by"] == "ariel"
    with pytest.raises(rq.QueueError):
        rq.retry(rows, "J0001")  # nothing has failed
    with pytest.raises(rq.QueueError):
        rq.add(rows, "India", " , ")


def test_queue_file_round_trip(tmp_path):
    rows = []
    rq.add(rows, "Mumbai ,India", "health food stores", languages="Hindi,  Marathi", wanted="8", added_by="ariel")
    rq.save(rows, tmp_path / "q.csv")
    back = rq.load(tmp_path / "q.csv")
    assert back[0]["location"] == "Mumbai, India" and back[0]["companies_wanted"] == "8"


# ---- the strict check ------------------------------------------------------

def company(name="Alpha Foods", domain="alphafoods.in", tier=1, rank=1, **extra):
    c = {"name": name, "domain": domain, "tier": tier, "tier_rank": rank, "distributes": "Chocolate",
         "channels_supplied": "Pharmacies", "sf_brands_carried": None, "competing_brand_flag": False,
         "fit_rationale": "Imports European chocolate.", "confidence": "high",
         "source_urls": ["https://example.org/a"]}
    c.update(extra)
    return c


def part(companies, channel="distributors"):
    return {"channel": channel, "searches_used": 10, "tier_logic": "Tier 1 imports.",
            "checked_and_excluded": [], "shortfall_note": None, "companies": companies}


def test_check_rejects_what_was_agreed():
    assert check_output.check_part(part([company()])) == []
    bad = [company(domain="https://www.alpha.in/about", confidence="High", source_urls=[]),
           company(name="Beta", domain="indiamart.com", tier=4, fit_rationale="Call +91 98200 12345 — now"),
           company(name="Alpha Foods Pvt Ltd", domain="alphafoods2.in", rank=1)]
    text = "\n".join(check_output.check_part(part(bad)))
    for expected in ("Domain of the found company must be written like abc.com",
                     "Found the company from must list at least one web link",
                     "Confidence must be high, medium or low", "Tier must be 1, 2 or 3",
                     "not the company's own site", "phone number", "em or en dash",
                     "appears twice (same name"):
        assert expected in text
    excluded = check_output.check_part(part([company()]), ({"alpha foods"}, set()))
    assert "exclusion list" in excluded[0]
    assert check_output.clean_domain("https://WWW.Alpha.in/about?x=1") == "alpha.in"
    assert check_output.clean_domain("amazon.in/shops/alpha") == "no domain"


# ---- the skill scripts, end to end on a copy of the repository --------------

@pytest.fixture
def repo(tmp_path):
    copy_root = tmp_path / "repo"
    for name in ("outreach", "skills", "config"):
        shutil.copytree(ROOT / name, copy_root / name, ignore=shutil.ignore_patterns("__pycache__"))
    (copy_root / "data").mkdir()
    (copy_root / "data" / "known_companies.csv").write_text(
        "name,domain,country,why\nKnown Foods Pvt Ltd,knownfoods.in,India,other\n"
        "Lead Elsewhere,leadelsewhere.com,Kenya,pipeline\nOther Kenya,otherkenya.com,Kenya,other\n",
        encoding="utf-8")
    rows = []
    rq.add(rows, "Mumbai, India", "distributors, marketplace sellers, health food stores", wanted="8",
           added_by="ariel", on="2026-10-07")
    rq.save(rows, copy_root / "research" / "queue.csv")
    return copy_root


def run_script(repo, name, *args):
    return subprocess.run([sys.executable, str(repo / "skills" / "outreachResearch" / "scripts" / name), *args],
                          cwd=repo, capture_output=True, text=True)


def test_skill_scripts_end_to_end(repo):
    out = run_script(repo, "prepare_run.py")
    assert out.returncode == 0, out.stderr
    plan = json.loads((repo / "work" / "plan.json").read_text())
    assert [c["template"] for c in plan["channels"]] == ["distributor", "marketplace_seller", "retailer"]
    prompt = (repo / "work" / "channel_2_prompt.md").read_text()
    assert "{{" not in prompt and "Minimum 8 companies" in prompt and "at most 60 web searches" in prompt
    assert "Known Foods Pvt Ltd (knownfoods.in)" in prompt  # same country
    assert "Lead Elsewhere" in prompt  # in the pipeline anywhere
    assert "Other Kenya" not in prompt  # another country, not in the pipeline
    assert "storefront page is not a domain" in prompt
    assert (repo / "research" / "queue.csv").read_text().count("Waiting") == 3  # the skill never edits it

    work = repo / "work"
    (work / "channel_1.json").write_text(json.dumps(part(
        [company(), company(name="Beta", domain="beta.in", rank=2, fit_rationale="Strong — pharmacy reach.")])))
    (work / "channel_2.json").write_text(json.dumps(part(
        [company(name="Alpha Foods", domain="https://www.alphafoods.in/shop"),
         company(name="Known Foods", domain="knownfoods.in", rank=2),
         company(name="Gamma Sellers", domain="amazon.in", tier=2)], "marketplace sellers")))
    # health food stores: no file, as if the helper hit a usage limit.
    out = run_script(repo, "finalise.py", "merge")
    assert out.returncode == 0, out.stdout + out.stderr
    final = json.loads((repo / plan["output_json"]).read_text())
    by_name = {c["name"]: c for c in final["companies"]}
    assert set(by_name) == {"Alpha Foods", "Beta", "Gamma Sellers"}
    assert by_name["Alpha Foods"]["channel_category"] == ["distributors", "marketplace sellers"]
    assert by_name["Gamma Sellers"]["domain"] == "no domain"
    assert "—" not in by_name["Beta"]["fit_rationale"]
    status = {c["channel"]: (c["status"], c["companies_found"]) for c in final["channels"]}
    assert status == {"distributors": ("done", 2), "marketplace sellers": ("done", 2),
                      "health food stores": ("failed", 0)}

    (work / "location.md").write_text("## Market structure\nImporters sell to super stockists.\n\n"
                                      "## Barriers to entry\n- Listing fees.\n")
    (work / "closing.md").write_text("- Alpha Foods first.\n")
    out = run_script(repo, "finalise.py", "report")
    assert out.returncode == 0, out.stdout
    report = (repo / plan["output_report"]).read_text()
    assert "Alpha Foods (also: marketplace sellers)" in report and "Known Foods" in report
    assert "health food stores" in report and "Retry a failed job" in report
    assert check_output.check_final(final, report) == []

    (work / "location.md").write_text("## Market structure\n" + "word " * 205 + "\n\n## Barriers to entry\n- x\n")
    out = run_script(repo, "finalise.py", "report")
    assert out.returncode == 1 and "205 words" in out.stdout


def test_nothing_to_do_and_on_hold(repo):
    rows = rq.load(repo / "research" / "queue.csv")
    for r in rows:
        r["status"] = rq.DONE
    rq.add(rows, "Mumbai, India", "Distributor", on="2026-10-08")
    rows[-1]["status"] = rq.WAITING  # e.g. typed into the file by hand: the run still holds it
    rq.save(rows, repo / "research" / "queue.csv")
    assert run_script(repo, "prepare_run.py", "--manual").returncode == 0
    plan = json.loads((repo / "work" / "plan.json").read_text())
    assert plan["run_type"] == "manual" and plan["channels"][0]["status"] == "on_hold"
    rows[-1]["status"] = rq.DONE
    rq.save(rows, repo / "research" / "queue.csv")
    out = run_script(repo, "prepare_run.py")
    assert out.returncode == 3 and "NOTHING TO DO" in out.stdout


# ---- the nightly list and the import ---------------------------------------

def test_known_companies(tmp_path):
    hs = FakeCRM()
    hs.add("companies", name="In Pipeline", domain="inpipe.in", country="India", diablo_outreach_status="approved")
    hs.add("companies", name="Customer", country="Kenya", lifecyclestage="customer")
    hs.add("companies", name="Plain", domain="plain.ae", country="United Arab Emirates")
    rows = known_companies.run("test", hs, tmp_path / "k.csv", log=quiet)
    assert {(r["name"], r["why"]) for r in rows} == {("In Pipeline", "pipeline"), ("Customer", "customer"),
                                                     ("Plain", "other")}


def final_file(job="J0001"):
    return {"format": check_output.FORMAT, "job_id": job, "location": "Mumbai, India",
            "run_date": "2026-10-09", "run_type": "scheduled",
            "channels": [
                {"channel": "distributors", "template": "distributor", "status": "done", "reason": "",
                 "companies_wanted": 2, "companies_found": 2, "searches_used": 40},
                {"channel": "retailers", "template": "retailer", "status": "failed",
                 "reason": "The helper did not save its file", "companies_wanted": 2, "companies_found": 0,
                 "searches_used": 0}],
            "companies": [
                dict(company(), channel_category=["distributors"]),
                dict(company(name="No Site Traders", domain="no domain", rank=2), channel_category=["distributors"]),
            ]}


@pytest.fixture
def import_env(tmp_path, monkeypatch):
    monkeypatch.setattr(import_research, "ROOT", tmp_path)
    monkeypatch.setattr(rq, "QUEUE_FILE", tmp_path / "research" / "queue.csv")
    monkeypatch.setattr(common, "NOTES_FILE", tmp_path / "company_notes.json")
    rows = []
    rq.add(rows, "Mumbai, India", "distributors, retailers", wanted="2", on="2026-10-08")
    rq.save(rows)
    folder = tmp_path / "research" / "2026-10-09"
    folder.mkdir(parents=True)
    return tmp_path, folder


def test_import_adds_companies_and_marks_the_queue(import_env):
    root, folder = import_env
    path = folder / "J0001_mumbai-india_distributors-retailers.json"
    path.write_text(json.dumps(final_file()))
    hs = FakeCRM()
    hs.add("companies", name="Old", domain="alphafoods.in")  # already in HubSpot
    import_research.run("test", hs, log=quiet)
    names = {p["name"]: p for p in hs.records["companies"].values()}
    assert set(names) == {"Old", "No Site Traders"}
    added = names["No Site Traders"]
    assert added["diablo_outreach_status"] == "no_domain" and added["diablo_channel_category"] == "distributors"
    assert added["country"] == "India" and added["diablo_tier"] == "tier_1" and "city" not in added
    rows = rq.load()
    assert [(r["status"], r["ran_on"]) for r in rows] == [(rq.DONE, "2026-10-09"), (rq.FAILED, "2026-10-09")]
    assert rows[0]["output_file"] == "research/2026-10-09/J0001_mumbai-india_distributors-retailers.json"
    # Running again imports nothing new.
    before = len(hs.records["companies"])
    import_research.run("test", hs, log=quiet)
    assert len(hs.records["companies"]) == before


def test_import_rejects_a_bad_file_whole(import_env):
    root, folder = import_env
    bad = final_file()
    bad["companies"][1]["domain"] = "https://www.nosite.in"
    (folder / "J0001_mumbai-india_x.json").write_text(json.dumps(bad))
    hs = FakeCRM()
    lines = import_research.run("test", hs, log=quiet)
    assert "REJECTED" in lines[0] and not hs.records["companies"]
    assert {r["status"] for r in rq.load()} == {rq.FAILED}
    assert "Domain of the found company" in rq.load()[0]["reason"]


def test_import_marks_fewer_than_wanted(import_env, monkeypatch):
    root, folder = import_env
    data = final_file()
    data["companies"] = data["companies"][:1]
    data["channels"][0]["companies_found"] = 1
    (folder / "J0001_mumbai-india_y.json").write_text(json.dumps(data))
    import_research.run("test", FakeCRM(), log=quiet)
    assert rq.load()[0]["status"] == rq.DONE_FEWER
