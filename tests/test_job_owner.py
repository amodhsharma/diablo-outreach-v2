"""Everything the research jobs bring in gets one HubSpot owner (Ariel, 23 Oct 2026); records that
already have an owner keep it."""

import pytest

from outreach import common, company_inbox, find_contacts, job_owner
from outreach.common import load_settings

from .fakes import FakeApollo, FakeCRM


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


def test_the_job_owner_is_set():
    assert job_owner.job_owner(load_settings()) == "38945050"
    assert job_owner.job_owner({"assignment": {"job_owner_id": ""}}) == ""


NOTES = {"free.example": {"research_file": "research/2026-10-20/J0001_x.json"},
         "taken.example": {"research_file": "research/2026-10-22/J0040_x.json"}}


def test_records_with_no_owner_get_it_and_others_keep_theirs():
    hs = FakeCRM()
    free = hs.add("companies", name="Free", domain="free.example")
    taken = hs.add("companies", name="Taken", domain="taken.example", hubspot_owner_id="111")
    by_job_number = hs.add("companies", name="No Domain", diablo_job_number="J0046")
    old = hs.add("companies", name="Lidl", domain="lidl.example")  # AUTO-OUTREACH from before the jobs
    c1 = hs.add("contacts", email="a@free.example")
    c2 = hs.add("contacts", email="b@taken.example")
    c3 = hs.add("contacts", email="c@taken.example", hubspot_owner_id="222")
    c4 = hs.add("contacts", email="d@lidl.example")
    hs.links[c1], hs.links[c2], hs.links[c3], hs.links[c4] = [free], [taken], [taken], [old]
    assert job_owner.fill_owners(hs, "999", quiet, notes=NOTES) == {"companies": 2, "contacts": 2}
    owner = lambda obj, rid: hs.records[obj][rid].get("hubspot_owner_id")
    assert owner("companies", free) == "999" and owner("companies", taken) == "111"
    assert owner("contacts", c1) == "999"  # its company now has the job owner (filled first)
    assert owner("contacts", c2) == "111"  # follows its company's owner
    assert owner("contacts", c3) == "222"  # already had one
    assert owner("companies", by_job_number) == "999"
    assert owner("companies", old) is None and owner("contacts", c4) is None  # not from a job: left alone
    assert job_owner.fill_owners(hs, "999", quiet, notes=NOTES) == {"companies": 0, "contacts": 0}
    assert job_owner.fill_owners(hs, "", quiet, notes=NOTES) == {"companies": 0, "contacts": 0}


def test_button_3_gives_new_contacts_the_job_owner(monkeypatch):
    monkeypatch.setattr(common, "NOTES_FILE", common.RUNS_DIR / "notes.json")
    common.save_company_notes(NOTES | {"alpha.example": {"research_file": "research/2026-10-23/J0046_x.json"}})
    hs = FakeCRM()
    cid = hs.add("companies", name="Alpha", domain="alpha.example", country="Switzerland",
                 hs_lead_status="GATE1: Approved for outreach")
    monkeypatch.setattr(company_inbox, "find_inbox", lambda domain, **k: "info@alpha.example")
    find_contacts.run("test", load_settings(), hs, FakeApollo({}, {}), log=quiet)
    assert hs.records["companies"][cid]["hubspot_owner_id"] == "38945050"
    assert [c["hubspot_owner_id"] for c in hs.records["contacts"].values()] == ["38945050"]
