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


def test_country_check_and_capitals():
    with pytest.raises(rq.QueueError) as err:
        rq.add([], "Mumbai, Infia", "distributors")
    assert "Did you mean India?" in str(err.value) and "Nothing was added" in str(err.value)
    with pytest.raises(rq.QueueError):
        rq.add([], "Paris", "distributors")  # a city with no country
    rows = []
    for typed, saved in (("dublin, ireland", "Dublin, Ireland"), ("new york, usa", "New York, USA"),
                         ("amsterdam, holland", "Amsterdam, Holland"), ("UK", "UK"), ("Côte d’Ivoire", "Cote d'Ivoire")):
        assert rq.add(rows, typed, "distributors")[1][0]["location"] == saved
    # UK and United Kingdom stay different Locations (matched as written).
    assert rq.add(rows, "United Kingdom", "distributors")[1][0]["status"] == rq.WAITING


def test_queue_file_round_trip(tmp_path):
    rows = []
    rq.add(rows, "Mumbai ,India", "health food stores", languages="Hindi,  Marathi", wanted="8", added_by="ariel")
    rq.save(rows, tmp_path / "q.csv")
    back = rq.load(tmp_path / "q.csv")
    assert back[0]["location"] == "Mumbai, India" and back[0]["companies_wanted"] == "8"


# ---- the strict check ------------------------------------------------------

def company(name="Alpha Foods", domain="alphafoods.in", tier=1, rank=1, **extra):
    c = {"name": name, "based_out_of": "Mumbai, India", "domain": domain, "tier": tier, "tier_rank": rank, "distributes": "Chocolate",
         "channels_supplied": "Pharmacies", "sf_brands_carried": None, "competing_brand_flag": False,
         "fit_rationale": "Imports European chocolate.", "what_they_do_well": ["Took two German brands into Musgrave."],
         "confidence": "high",
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
    (repo / "data" / "pipeline_target.txt").write_text("live\n")  # the live account: full exclusion list
    out = run_script(repo, "prepare_run.py")
    assert out.returncode == 0, out.stderr
    plan = json.loads((repo / "work" / "plan.json").read_text())
    assert [c["template"] for c in plan["channels"]] == ["distributor", "marketplace_seller", "retailer"]
    prompt = (repo / "work" / "channel_2_prompt.md").read_text()
    assert "{{" not in prompt and "Minimum 8 companies" in prompt and "at most 60 web searches" in prompt
    assert "Known Foods Pvt Ltd (knownfoods.in)" in prompt  # same country
    assert "Lead Elsewhere" in prompt  # in the pipeline anywhere
    assert "Other Kenya" not in prompt  # another country, not in the pipeline
    assert "- otherkenya.com" in (repo / "work" / "exclusions.txt").read_text()  # but the checks know it
    assert "storefront page is not a domain" in prompt
    assert (repo / "research" / "queue.csv").read_text().count("Waiting") == 3  # the skill never edits it

    work = repo / "work"
    (work / "channel_1.json").write_text(json.dumps(part(
        [company(), company(name="Beta", domain="beta.in", rank=2, fit_rationale="Strong — pharmacy reach."),
         company(name="Kenya Cousin", domain="otherkenya.com", rank=3)])))  # already in HubSpot: dropped
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
    import datetime as dt
    hs = FakeCRM()
    hs.add("companies", name="In Pipeline", domain="inpipe.in", country="India")  # AUTO-OUTREACH
    hs.add("companies", tagged=False, name="Customer", country="Kenya", lifecyclestage="customer")
    plain = hs.add("companies", tagged=False, name="Plain", website="https://www.plain.ae/", country="United Arab Emirates")
    paths = dict(path=tmp_path / "k.csv", state_path=tmp_path / "state.json", log=quiet)
    tuesday = dt.datetime(2026, 10, 13, 9, 0, tzinfo=dt.timezone.utc)
    for rec in hs.records["companies"].values():
        rec["hs_lastmodifieddate"] = str(int((tuesday - dt.timedelta(days=30)).timestamp() * 1000))
    rows = known_companies.run("test", hs, now=tuesday, **paths)  # first run: everything
    assert {(r["name"], r["why"]) for r in rows.values()} == {("In Pipeline", "auto-outreach"),
                                                              ("Customer", "customer"), ("Plain", "other")}
    assert rows[plain]["domain"] == "plain.ae"  # from the website when Domain is empty
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_full"] == "2026-10-13" and state["portal"] == "999"

    # Three hours later only the changes are read: a new company and a renamed one.
    later = tuesday + dt.timedelta(hours=3)
    new = hs.add("companies", tagged=False, name="Fresh Ltd", domain="fresh.co.uk", country="United Kingdom",
                 hs_lastmodifieddate=str(int((later - dt.timedelta(hours=1)).timestamp() * 1000)))
    hs.records["companies"][plain].update(name="Plain Trading",
                                          hs_lastmodifieddate=str(int(later.timestamp() * 1000)))
    del hs.records["companies"][next(iter(hs.records["companies"]))]  # deleted: stays until a full read
    called = []
    real = hs.list_all
    hs.list_all = lambda *a: called.append(1) or real(*a)
    rows = known_companies.run("test", hs, now=later, **paths)
    assert not called and len(rows) == 4 and rows[new]["name"] == "Fresh Ltd"
    assert rows[plain]["name"] == "Plain Trading"

    # Sunday (India time): a full read, which also drops the deleted company.
    sunday = dt.datetime(2026, 10, 18, 3, 0, tzinfo=dt.timezone.utc)
    rows = known_companies.run("test", hs, now=sunday, **paths)
    assert called and len(rows) == 3
    # A different account (e.g. moving from test to live): a full read straight away.
    called.clear()
    hs.portal = 1234
    known_companies.run("test", hs, now=sunday + dt.timedelta(hours=3), **paths)
    assert called


def test_known_company_matching():
    idx = known_companies.index([
        {"name": "WM MORRISON SUPERMARKETS P L C", "domain": "", "country": "United Kingdom"},
        {"name": "Kilargo Sp. z o.o.", "domain": "kilargo.pl", "country": "Poland"},
        {"name": "Metro", "domain": "", "country": "Germany"},
    ])
    assert known_companies.matches(idx, "", "Wm Morrison Supermarkets PLC", "United Kingdom")
    assert known_companies.matches(idx, "https://www.kilargo.pl/en", "Something else", "India")
    assert known_companies.matches(idx, "", "Kilargo", "Poland")
    assert not known_companies.matches(idx, "", "Metro", "United Kingdom")  # names only within a country
    assert not known_companies.matches(idx, "newco.com", "New Co", "Germany")


def final_file(job="J0001"):
    return {"format": check_output.FORMAT, "job_id": job, "location": "Mumbai, India",
            "run_date": "2026-10-09", "run_type": "scheduled", "replaces": [],
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
    monkeypatch.setattr(known_companies, "KNOWN_FILE", tmp_path / "known_companies.csv")
    from outreach.import_checks import Checker
    monkeypatch.setattr(import_research, "default_checker",
                        lambda log=print: Checker({"website": False, "apollo": False}))
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
    hs.add("companies", tagged=False, name="Old", domain="alphafoods.in")  # already in HubSpot
    import_research.run("test", hs, log=quiet)
    names = {p["name"]: p for p in hs.records["companies"].values()}
    assert set(names) == {"Old", "No Site Traders"}
    added = names["No Site Traders"]
    assert added["hs_lead_status"] == "Missing Info" and added["industry_type"] == "Distributor Wholesaler"
    assert added["country"] == "India" and added["city"] == "Mumbai" and added["hs_ideal_customer_profile"] == "tier_1"
    assert added["lead_source"] == "AUTO-OUTREACH" and not any(k.startswith("diablo_") for k in added)
    assert names["Old"] == {"name": "Old", "domain": "alphafoods.in"}  # the team's record: untouched
    assert hs.records["companies"] and common.load_company_notes() == {}  # no domain: no email notes
    rows = rq.load()
    # The failed Channel goes back to Waiting for one automatic retry.
    assert [(r["status"], r["ran_on"], r["attempts"]) for r in rows] == [
        (rq.DONE, "2026-10-09", ""), (rq.WAITING, "2026-10-09", "1")]
    assert "runs again by itself" in rows[1]["reason"]
    assert rq.waiting_job(rows)[0] == "J0001"
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
    assert {r["status"] for r in rq.load()} == {rq.WAITING}  # retried once by itself
    assert "Domain of the found company" in rq.load()[0]["reason"]
    # The retry fails the check too: now Failed, until someone presses Retry.
    rows = rq.load()
    for r in rows:
        r["output_file"] = ""
    rq.save(rows)
    import_research.run("test", hs, log=quiet)
    assert {r["status"] for r in rq.load()} == {rq.FAILED}
    assert rq.load()[0]["reason"].startswith("Failed again")


def test_import_marks_fewer_than_wanted(import_env, monkeypatch):
    root, folder = import_env
    data = final_file()
    data["companies"] = data["companies"][:1]
    data["channels"][0]["companies_found"] = 1
    (folder / "J0001_mumbai-india_y.json").write_text(json.dumps(data))
    import_research.run("test", FakeCRM(), log=quiet)
    assert rq.load()[0]["status"] == rq.DONE_FEWER


def test_retry_replaces_the_earlier_file(repo):
    # First run: distributors done, marketplace sellers and health food stores fail.
    assert run_script(repo, "prepare_run.py").returncode == 0
    work = repo / "work"
    (work / "channel_1.json").write_text(json.dumps(part([company()])))
    assert run_script(repo, "finalise.py", "merge").returncode == 0
    (work / "location.md").write_text("## Market structure\nA.\n\n## Barriers to entry\n- B.\n")
    (work / "closing.md").write_text("- Alpha Foods first.\n")
    assert run_script(repo, "finalise.py", "report").returncode == 0
    first = json.loads((work / "plan.json").read_text())["output_json"]
    assert "J0001_2026-" in first  # the run date is in the file name

    # The import marks the queue (done in the test by hand, as GitHub would).
    rows = rq.load(repo / "research" / "queue.csv")
    rows[0].update(status=rq.DONE, output_file=first, ran_on="2026-10-07")
    for r in rows[1:]:
        rq.record_failure(rows, "J0001", r["channel"], "usage limit", "2026-10-07", first)
    rq.save(rows, repo / "research" / "queue.csv")

    # Second run: only the failed Channels run, and the new file replaces the first.
    assert run_script(repo, "prepare_run.py").returncode == 0
    plan = json.loads((work / "plan.json").read_text())
    assert plan["replaces"] == [first] and [c["channel"] for c in plan["channels"]] == [
        "marketplace sellers", "health food stores"]
    (work / "channel_1.json").write_text(json.dumps(part([company(name="Seller One", domain="sellerone.in")],
                                                          "marketplace sellers")))
    (work / "channel_2.json").write_text(json.dumps(part([company(name="Shop One", domain="shopone.in")],
                                                          "health food stores")))
    out = run_script(repo, "finalise.py", "merge")
    assert out.returncode == 0 and "Removed the earlier file" in out.stdout, out.stdout
    assert not (repo / first).exists()
    (work / "location.md").write_text("## Market structure\nA.\n\n## Barriers to entry\n- B.\n")
    assert run_script(repo, "finalise.py", "report").returncode == 0
    final = json.loads((repo / plan["output_json"]).read_text())
    assert [c["status"] for c in final["channels"]] == ["done", "done", "done"]
    assert {c["name"] for c in final["companies"]} == {"Alpha Foods", "Seller One", "Shop One"}
    assert final["replaces"] == [first]


def test_what_they_do_well_rules():
    assert check_output.check_part(part([company(what_they_do_well=[])])) == []  # nothing verifiable: empty
    too_many = check_output.check_part(part([company(what_they_do_well=["a", "b", "c"])]))
    assert "one or two points" in too_many[0]
    too_long = check_output.check_part(part([company(what_they_do_well=["word " * 26])]))
    assert "25 words or fewer" in too_long[0]
    missing = company()
    del missing["what_they_do_well"]
    assert "missing field(s): what_they_do_well" in check_output.check_part(part([missing]))[0]


def test_import_skips_companies_on_the_full_list_and_by_website(import_env):
    root, folder = import_env
    (root / "known_companies_test.csv").write_text(  # the test account's own list (19 Oct 2026)
        "id,name,domain,country,why\n7,No Site Traders Pvt. Ltd.,,India,other\n", encoding="utf-8")
    (folder / "J0001_mumbai-india_z.json").write_text(json.dumps(final_file()))
    hs = FakeCRM()
    hs.add("companies", tagged=False, name="Alpha Foods India", website="https://www.alphafoods.in")
    lines = import_research.run("test", hs, log=quiet)
    assert "0 companies added to HubSpot" in lines[0] and "2 already in HubSpot" in lines[0]
    assert len(hs.records["companies"]) == 1


def test_country_short_forms_match():
    idx = known_companies.index([{"name": "Noble Foods Ltd", "domain": "", "country": "UK"}])
    assert known_companies.matches(idx, "", "Noble Foods", "United Kingdom")
    assert known_companies.matches(idx, "", "noble foods limited", "England")


def test_prompt_versions_side_by_side(repo):
    """Version 2 (default) uses the _2 prompts; version 1 still uses the untouched originals."""
    prompts = Path(__file__).resolve().parents[1] / "skills" / "outreachResearch" / "prompts"
    for name in ["channel_prompt", "channels/distributor", "channels/wholesaler", "channels/retailer",
                 "channels/general", "channels/marketplace_seller"]:
        assert (prompts / f"{name}.md").exists() and (prompts / f"{name}_2.md").exists()
    assert run_script(repo, "prepare_run.py").returncode == 0
    plan = json.loads((repo / "work" / "plan.json").read_text())
    new = (repo / "work" / "channel_1_prompt.md").read_text()
    assert plan["prompt_version"] == 2 and "reason \"agency\"" in new and "bestfoodimporters.com" in new
    settings = repo / "skills" / "outreachResearch" / "settings.yaml"
    settings.write_text(settings.read_text().replace("prompt_version: 2", "prompt_version: 1"))
    assert run_script(repo, "prepare_run.py").returncode == 0
    plan = json.loads((repo / "work" / "plan.json").read_text())
    old = (repo / "work" / "channel_1_prompt.md").read_text()
    assert plan["prompt_version"] == 1 and "agency" not in old and "Include import agents only if" in old


def test_version_2_numbers(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("prompt_version: 2\ndefault_companies: 60\nmin_floor: 30\ndefault_companies_2: 30\nmin_floor_2: 15\n")
    assert (rq.load_research_settings(f)["default_companies"], rq.load_research_settings(f)["min_floor"]) == (30, 15)
    f.write_text(f.read_text().replace("prompt_version: 2", "prompt_version: 1"))
    assert (rq.load_research_settings(f)["default_companies"], rq.load_research_settings(f)["min_floor"]) == (60, 30)


def test_test_account_research_has_no_exclusion_list(repo):
    """19 Oct 2026: on the test account research takes the first companies it finds; only the
    live account is checked against its 40,000+ companies."""
    (repo / "data" / "pipeline_target.txt").write_text("test\n")
    out = run_script(repo, "prepare_run.py")
    assert out.returncode == 0, out.stderr
    assert "no 'already in HubSpot' list" in out.stdout
    prompt = (repo / "work" / "channel_2_prompt.md").read_text()
    assert "Known Foods Pvt Ltd" not in prompt and (repo / "work" / "exclusions.txt").read_text() == ""
    assert json.loads((repo / "work" / "plan.json").read_text())["target"] == "test"


def test_each_account_keeps_its_own_list(tmp_path):
    from outreach import common
    hs = FakeCRM()
    hs.add("companies", name="Alpha", domain="alpha.example")
    known_companies.run("test", hs, log=quiet)
    assert common.KNOWN_FILE_TEST.exists() and not common.KNOWN_FILE.exists()  # live list untouched
    assert "alpha.example" in common.KNOWN_FILE_TEST.read_text()


def test_several_cities_in_one_box_become_one_job_each():
    """Ariel, 20 Oct 2026: "Hamburg, Munich, Cologne, Germany" in button 2."""
    from outreach import research_queue as rq
    assert rq.split_locations("Hamburg, Munich, Cologne, Germany") == [
        "Hamburg, Germany", "Munich, Germany", "Cologne, Germany"]
    assert rq.split_locations("Lyon, France") == ["Lyon, France"]
    assert rq.split_locations("Germany") == ["Germany"]
    assert rq.split_locations("hamburg; munich; Germany") == ["hamburg, Germany", "munich, Germany"]
    rows = []
    results = rq.add_many(rows, "hamburg, munich, cologne, germany", "distributors, retailers", wanted="15",
                          added_by="ariel", on="2026-10-20")
    assert [job for job, _, _ in results] == ["J0001", "J0002", "J0003"]
    assert [r["location"] for r in rows] == ["Hamburg, Germany"] * 2 + ["Munich, Germany"] * 2 + ["Cologne, Germany"] * 2
    assert all(r["companies_wanted"] == "15" for r in rows)
    # All or nothing: a misspelt country adds no job at all.
    before = list(rows)
    with pytest.raises(rq.QueueError):
        rq.add_many(rows, "Berlin, Bremen, Germny", "distributors")
    assert rows == before
