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

    assert check_lines.check_file(lines_file([dict(GOOD, subject_line="Sugar free range for Alpha")])) == []  # older files
    assert problems(subject_line="Hello there")  # 2 words
    assert problems(subject_line="Sugar free for you?")
    assert problems(subject_line="Re: sugar free range")
    assert problems(subject_line="SUGAR FREE RANGE NOW")
    assert problems(personal_line="word " * 61)
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


def test_styles_and_tone_agreed_14_oct():
    def problems(line, style=None):
        item = dict(GOOD, personal_line=line)
        if style:
            item["style"] = style
        return check_lines.check_file(lines_file([item]))

    for letter, line in STYLE_LINES.items():
        line = line.replace(" —", ",")
        assert problems(line, letter) == [], (letter, problems(line, letter))
        assert problems(line, "D" if letter != "D" else "A")  # written in the wrong style
    assert problems(STYLE_LINES["B"].replace("the brands you already represent", "the products you already offer"), "B") == []
    assert problems(STYLE_LINES["C"], "E")  # no such style
    assert problems(STYLE_LINES["D"].replace("We hold", "We hold").replace("’", "'"), "D") == []
    # "we", never "I"
    assert problems("I hold your team in high regard. I would be grateful.")
    assert problems("We think my range suits you.")
    # casual words, over-the-top praise and guesses about what they lack
    for word in ("fun", "enjoyed", "lovely", "love", "chat", "incredibly", "wonderful", "world-class"):
        assert problems(f"Your stores are {word} places. We would value a call.")
    assert problems("Your range has a gap for sugar free. We would value a call.")
    assert problems("Your customers have started asking for sugar free. We would value a call.")
    # 60 words is the limit; "R.C." is not a sentence end
    assert not problems(" ".join(["word"] * 59) + ".")
    assert problems(" ".join(["word"] * 61) + ".")
    assert problems("We hold R.C. Andreae in high regard for its reach. We would be grateful for a call.") == []


def test_styles_are_random_but_spread_and_differ_within_a_company(tmp_path):
    import random
    import prepare_lines
    contacts = [{"contact_id": str(i), "company": {"name": f"Co {i // 3}"}} for i in range(12)]
    prepare_lines.assign_styles(contacts, lines_dir=tmp_path, rng=random.Random(1))
    letters = [c["style"]["letter"] for c in contacts]
    assert sorted(letters) == sorted("ABCD" * 3)  # every style used equally
    for start in range(0, 12, 3):
        assert len(set(letters[start:start + 3])) == 3  # colleagues get different styles
    # Earlier files count: a company that already had A, B and C gets D next.
    folder = tmp_path / "2026-10-14"
    folder.mkdir()
    (folder / "x.json").write_text(json.dumps({"lines": [
        {"contact_id": "a", "company_name": "Beta", "personal_line": "x", "style": s} for s in "ABC"]}))
    more = prepare_lines.assign_styles([{"contact_id": "z", "company": {"name": "beta"}}], lines_dir=tmp_path)
    assert more[0]["style"]["letter"] == "D"


# ---- the list of contacts needing lines ------------------------------------

LS = "hs_lead_status"


def crm_with_contacts():
    hs = FakeCRM()
    co = hs.add("companies", name="Alpha Foods", domain="alphafoods.in", city="Mumbai", country="India",
                industry_type="Distributor Wholesaler", **{LS: "GATE1: Approved for outreach"})
    stopped = hs.add("companies", name="Done Co", domain="done.in", **{LS: "In Progress"})
    a = hs.add("contacts", jobtitle="Purchasing Manager", diablo_outreach_order="2", **{LS: "NEW"})
    b = hs.add("contacts", jobtitle="Managing Director", diablo_outreach_order="1", **{LS: "NEW"})
    c = hs.add("contacts", jobtitle="Owner", diablo_outreach_order="1", **{LS: "NEW_PERSONAL_LINE_FILLED"})
    d = hs.add("contacts", jobtitle="Owner", diablo_outreach_order="1", **{LS: "NEW"})
    team = hs.add("contacts", tagged=False, jobtitle="Owner", **{LS: "NEW"})  # the team's own contact
    hs.associate_tagged("contacts", "companies", [(a, co), (b, co), (c, co), (d, stopped)])
    hs.links[team] = [co]
    return hs, (a, b, c, d)


def test_export_lists_only_contacts_needing_lines(tmp_path, monkeypatch):
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"alphafoods.in": {
        "name": "Alpha Foods", "based_out_of": "Mumbai", "what_they_do_well": ["Pharmacy reach"],
        "distributes": "Imported snacks", "fit_rationale": "Imports European snacks"}}))
    monkeypatch.setattr(common, "NOTES_FILE", notes)
    hs, (a, b, _c, _d) = crm_with_contacts()
    rows = export_for_lines.run("test", hs, tmp_path / "pending.json", log=quiet)
    assert [r["contact_id"] for r in rows] == [b, a]  # most senior first; copy ready, stopped and untagged left out
    assert rows[0]["company"]["what_they_do_well"] == ["Pharmacy reach"]
    assert rows[0]["company"]["location"] == "Mumbai, India"
    assert rows[0]["seniority"] == "Top leadership" and rows[1]["seniority"] == "Managers"
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


STYLE_LINES = {
    "A": "We have great respect for the way your team takes snacks across Mumbai — with such established "
         "reach across pharmacies, we would be honoured if you would consider whether a sugar free range "
         "could have a place in your portfolio.",
    "B": "Your team's work in building snack distribution across Mumbai speaks for itself. We would value the "
         "opportunity to present our sugar free range and to hear whether you feel it could sit alongside "
         "the brands you already represent.",
    "C": "Your range, from crisps to biscuits, reflects a careful choice of brands for Mumbai. We would welcome "
         "the chance to present our sugar free range for your consideration, should you see a place for it.",
    "D": "We hold your team in high regard for its snack distribution across Mumbai. We would be grateful for "
         "the opportunity to discuss whether our sugar free range could be a worthwhile addition to your business.",
}


def draft_line(cid, batch):
    style = next(c["style"]["letter"] for c in batch["contacts"] if c["contact_id"] == cid)
    return {"contact_id": cid, "personal_line": STYLE_LINES[style]}


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
    assert all(c["style"]["letter"] in check_lines.STYLES and "[" in c["style"]["shape"] for c in batch["contacts"])
    assert "The four styles" in prompt and '"letter"' in prompt
    (work / "draft.json").write_text(json.dumps({"lines": [draft_line("1000", batch),
                                                           dict(draft_line("1001", batch), personal_line="Amazing!")]}))
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
    assert data["lines"][0]["style"] == batch["contacts"][0]["style"]["letter"]
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
    assert ("1 contacts now on 'New, Personal line filled', 1 skipped (Lead Status no longer New), "
            "1 skipped (not an AUTO-OUTREACH contact in HubSpot)") in results[0]
    assert "REJECTED" in results[1]
    assert hs.records["contacts"][a][LS] == "NEW_PERSONAL_LINE_FILLED"
    assert hs.records["contacts"][a]["diablo_personal_line"] == GOOD["personal_line"]
    assert "diablo_subject_line" not in hs.records["contacts"][a]
    assert hs.records["contacts"][b][LS] == "NEW"  # rejected file
    assert [r["contact_id"] for r in json.loads(pending.read_text())["contacts"]] == [b]
    assert imported.read_text().count("\n") == 2
    assert import_lines.run("test", hs, log=quiet, imported_path=imported, pending_path=pending) == []


def test_search_lag_does_not_put_contacts_back_on_the_list(tmp_path, monkeypatch):
    """HubSpot's search lags behind updates; the list must use the real status."""
    monkeypatch.setattr(import_lines, "LINES_DIR", tmp_path / "lines")
    monkeypatch.setattr(common, "NOTES_FILE", tmp_path / "notes.json")
    hs, (a, b, _c, _d) = crm_with_contacts()
    stale = {rid: dict(p) for rid, p in hs.records["contacts"].items()}
    real_search = hs.search

    def lagging_search(object_type, filters, properties, **kw):
        if object_type != "contacts":
            return real_search(object_type, filters, properties, **kw)
        live = hs.records["contacts"]
        hs.records["contacts"] = stale
        try:
            return real_search(object_type, filters, properties, **kw)
        finally:
            hs.records["contacts"] = live

    hs.search = lagging_search
    folder = tmp_path / "lines" / "2026-10-07"
    folder.mkdir(parents=True)
    (folder / "2026-10-07_1400_1.json").write_text(json.dumps(lines_file([dict(GOOD, contact_id=a)])))
    pending = tmp_path / "pending.json"
    import_lines.run("test", hs, log=quiet, imported_path=tmp_path / "imported.txt", pending_path=pending)
    assert [r["contact_id"] for r in json.loads(pending.read_text())["contacts"]] == [b]
    hs.records["contacts"][b][LS] = "NEW_PERSONAL_LINE_FILLED"  # e.g. lines typed in HubSpot by hand
    rows = export_for_lines.run("test", hs, pending, log=quiet)
    assert rows == []
