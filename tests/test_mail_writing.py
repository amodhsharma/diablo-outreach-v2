"""Offline tests for the outreach-mail-writing parts: the list of contacts needing lines,
the skill's scripts, the strict check and the import into HubSpot."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from outreach import common, export_for_lines, import_lines

from .fakes import FakeCRM

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "outreachMailWriting" / "scripts"))
import check_lines  # noqa: E402


def quiet(_):
    pass


GOOD = {"contact_id": "1001", "company_name": "Alpha Foods",
        "subject_line": "Sugar free range for Alpha Foods",
        "personal_line": "Your work taking European snack brands into pharmacies across Mumbai stood out to us. "
                         "A partner with that reach is what we are looking for in India."}


def lines_file(lines, generated_from="2026-10-07T10:00:00+00:00"):
    return {"format": check_lines.FORMAT, "run_date": "2026-10-07", "run_type": "scheduled",
            "generated_from": generated_from, "lines": lines}


# ---- the strict check ------------------------------------------------------

def test_check_accepts_a_good_line_and_rejects_what_was_agreed():
    assert check_lines.check_file(lines_file([GOOD])) == []

    def problems(**change):
        return check_lines.check_file(lines_file([dict(GOOD, **change)]))

    assert problems(subject_line="Hello there")  # 2 words
    assert problems(subject_line="Sugar free for you?")
    assert problems(subject_line="Re: sugar free range")
    assert problems(subject_line="SUGAR FREE RANGE NOW")
    assert problems(personal_line="word " * 51)
    assert problems(personal_line="One. Two. Three.")
    assert problems(personal_line="A great range for diabetic shoppers.")
    assert problems(personal_line="I was impressed by your stores.")
    assert problems(personal_line="Your stores are great — truly.")
    assert problems(personal_line="Alpha Foods leads. Alpha Foods grows.")
    assert problems(personal_line="See www.alpha.in for more.")
    assert problems(personal_line="Hi {{firstName}}, your stores lead.")
    assert problems(personal_line="Great stores!")
    assert check_lines.check_file(lines_file([GOOD, GOOD]))  # the same contact twice
    assert check_lines.check_file(lines_file([GOOD]), pending_ids={"999"})  # not on the list
    bad = lines_file([GOOD])
    bad["extra"] = 1
    assert check_lines.check_file(bad)


# ---- the list of contacts needing lines ------------------------------------

def crm_with_contacts():
    hs = FakeCRM()
    co = hs.add("companies", name="Alpha Foods", domain="alphafoods.in", diablo_market="Mumbai, India",
                diablo_channel_category="distributors", diablo_outreach_status="approved")
    stopped = hs.add("companies", name="Done Co", domain="done.in", diablo_outreach_status="replied")
    a = hs.add("contacts", jobtitle="Purchasing Manager", diablo_hierarchy_rank="2",
               diablo_hierarchy_level="Manager", diablo_contact_status="contact_found")
    b = hs.add("contacts", jobtitle="Managing Director", diablo_hierarchy_rank="1",
               diablo_hierarchy_level="Director", diablo_contact_status="contact_found")
    c = hs.add("contacts", jobtitle="Owner", diablo_hierarchy_rank="1", diablo_contact_status="copy_ready")
    d = hs.add("contacts", jobtitle="Owner", diablo_hierarchy_rank="1", diablo_contact_status="contact_found")
    hs.associate_default("contacts", "companies", [(a, co), (b, co), (c, co), (d, stopped)])
    return hs, (a, b, c, d)


def test_export_lists_only_contacts_needing_lines(tmp_path, monkeypatch):
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"alphafoods.in": {
        "name": "Alpha Foods", "based_out_of": "Mumbai", "what_they_do_well": ["Pharmacy reach"],
        "distributes": "Imported snacks", "fit_rationale": "Imports European snacks"}}))
    monkeypatch.setattr(common, "NOTES_FILE", notes)
    hs, (a, b, _c, _d) = crm_with_contacts()
    rows = export_for_lines.run("test", hs, tmp_path / "pending.json", log=quiet)
    assert [r["contact_id"] for r in rows] == [b, a]  # most senior first; copy ready and stopped left out
    assert rows[0]["company"]["what_they_do_well"] == ["Pharmacy reach"]
    assert rows[0]["company"]["location"] == "Mumbai, India"
    saved = json.loads((tmp_path / "pending.json").read_text())
    assert "email" not in json.dumps(saved) and len(saved["contacts"]) == 2


# ---- the skill's scripts, end to end on a copy of the repository -----------

@pytest.fixture
def repo(tmp_path):
    copy_root = tmp_path / "repo"
    shutil.copytree(ROOT / "skills", copy_root / "skills", ignore=shutil.ignore_patterns("__pycache__"))
    (copy_root / "mail").mkdir()
    contacts = [{"contact_id": str(1000 + i), "job_title": "Director", "seniority": "Director", "rank": 1,
                 "company": {"name": f"Company {i}", "domain": f"c{i}.in", "location": "Mumbai, India",
                             "channel": "Distributors", "based_out_of": "Mumbai", "distributes": "Snacks",
                             "channels_supplied": "", "sf_brands_carried": "", "what_they_do_well": [],
                             "fit_rationale": ""}} for i in range(3)]
    (copy_root / "mail" / "pending.json").write_text(json.dumps(
        {"generated_at": "2026-10-07T10:00:00+00:00", "target": "test", "contacts": contacts}))
    return copy_root


def run_script(repo, name, *args):
    return subprocess.run([sys.executable, str(repo / "skills" / "outreachMailWriting" / "scripts" / name), *args],
                          cwd=repo, capture_output=True, text=True)


def draft_line(cid, n):
    return {"contact_id": cid, "subject_line": f"Sugar free range for Company {n}",
            "personal_line": "Your snack distribution across Mumbai stood out to us — it is the reach we "
                             "are looking for in India."}


def test_skill_scripts_end_to_end(repo):
    settings = repo / "skills" / "outreachMailWriting" / "settings.yaml"
    settings.write_text("max_contacts_per_run: 2\n")
    out = run_script(repo, "prepare_lines.py")
    assert out.returncode == 0, out.stderr
    assert "1 more wait" in out.stdout
    batch = json.loads((repo / "work_mail" / "batch.json").read_text())
    assert [c["contact_id"] for c in batch["contacts"]] == ["1000", "1001"]
    prompt = (repo / "work_mail" / "prompt.md").read_text()
    assert "{{contacts_json}}" not in prompt and "Company 1" in prompt and "all 2 contacts" in prompt

    work = repo / "work_mail"
    (work / "draft.json").write_text(json.dumps({"lines": [draft_line("1000", 0),
                                                           dict(draft_line("1001", 1), personal_line="Amazing!")]}))
    out = run_script(repo, "finalise_lines.py")
    assert out.returncode == 1 and "Contact 1001" in out.stdout
    assert not (repo / "mail" / "lines").exists()  # nothing saved on a failure

    out = run_script(repo, "finalise_lines.py", "--drop-failing")
    assert out.returncode == 0, out.stdout
    saved = list((repo / "mail" / "lines").glob("*/*.json"))
    assert len(saved) == 1 and saved[0].name.endswith("_1.json")
    data = json.loads(saved[0].read_text())
    assert data["lines"][0]["company_name"] == "Company 0"
    assert "—" not in data["lines"][0]["personal_line"]  # the dash became a comma
    assert check_lines.check_file(data) == []

    # The next run leaves out 1000 (lines waiting for import) and picks up the rest.
    out = run_script(repo, "prepare_lines.py", "--manual")
    batch = json.loads((repo / "work_mail" / "batch.json").read_text())
    assert [c["contact_id"] for c in batch["contacts"]] == ["1001", "1002"] and batch["run_type"] == "manual"


def test_nothing_to_do(repo):
    pending = json.loads((repo / "mail" / "pending.json").read_text())
    pending["contacts"] = []
    (repo / "mail" / "pending.json").write_text(json.dumps(pending))
    out = run_script(repo, "prepare_lines.py")
    assert out.returncode == 3 and "NOTHING TO DO" in out.stdout
    (repo / "mail" / "pending.json").unlink()
    assert run_script(repo, "prepare_lines.py").returncode == 3


# ---- the import into HubSpot -----------------------------------------------

def test_import_moves_contacts_to_copy_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(import_lines, "LINES_DIR", tmp_path / "lines")
    monkeypatch.setattr(common, "NOTES_FILE", tmp_path / "notes.json")
    hs, (a, b, c, _d) = crm_with_contacts()
    folder = tmp_path / "lines" / "2026-10-07"
    folder.mkdir(parents=True)
    good = folder / "2026-10-07_1400_3.json"
    good.write_text(json.dumps(lines_file([dict(GOOD, contact_id=a), dict(GOOD, contact_id=c),
                                           dict(GOOD, contact_id="424242")])))
    bad = folder / "2026-10-07_1600_1.json"
    bad.write_text(json.dumps(lines_file([dict(GOOD, contact_id=b, personal_line="Amazing stores.")])))
    imported, pending = tmp_path / "imported.txt", tmp_path / "pending.json"

    results = import_lines.run("test", hs, log=quiet, imported_path=imported, pending_path=pending)
    assert "1 contacts now Copy ready, 1 skipped (no longer Contact found), 1 skipped (not in HubSpot)" in results[0]
    assert "REJECTED" in results[1]
    assert hs.records["contacts"][a]["diablo_contact_status"] == "copy_ready"
    assert hs.records["contacts"][a]["diablo_subject_line"] == GOOD["subject_line"]
    assert hs.records["contacts"][b]["diablo_contact_status"] == "contact_found"  # rejected file
    assert [r["contact_id"] for r in json.loads(pending.read_text())["contacts"]] == [b]
    assert imported.read_text().count("\n") == 2
    assert import_lines.run("test", hs, log=quiet, imported_path=imported, pending_path=pending) == []
