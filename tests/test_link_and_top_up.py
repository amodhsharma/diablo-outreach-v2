"""Button 3, 26 Oct 2026 (Ariel): every contact linked to its company as its Primary company with its
Company name filled; a company with fewer people than wanted gets the rest searched for (once a month);
and the summary line "Out of x companies on GATE 1 ...".
"""

import json

import pytest

from outreach import common, find_contacts, linking
from outreach.common import load_settings
from outreach.schema import INBOX_TITLE

from .fakes import FakeApollo, FakeCRM


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


def _gate1(hs, name, domain):
    return hs.add("companies", name=name, domain=domain, country="Switzerland", industry_type="Distributors",
                  hs_lead_status="GATE1: Approved for outreach")


def _contact(hs, cid, email, order, title="Owner", **props):
    pid = hs.add("contacts", email=email, firstname="Pia", lastname="Muster", jobtitle=title,
                 diablo_outreach_order=str(order), hs_lead_status="NEW", **props)
    hs.links[pid] = [cid]
    return pid


def _people(*ids):
    return [{"id": i, "title": "Purchasing Manager", "has_email": True} for i in ids]


def test_new_contacts_get_their_primary_company_and_company_name():
    hs = FakeCRM()
    cid = _gate1(hs, "Alpha Foods", "alpha.example")
    apollo = FakeApollo({"alpha.example": _people("a1", "a2")},
                        {"a1": ("one@alpha.example", "verified"), "a2": ("two@alpha.example", "verified")})
    find_contacts.run("test", load_settings(), hs, apollo, log=quiet)
    added = [rid for rid, r in hs.records["contacts"].items() if r["email"].endswith("@alpha.example")]
    assert len(added) == 2
    assert all(hs.primary[rid] == cid for rid in added)
    assert all(hs.records["contacts"][rid]["company"] == "Alpha Foods" for rid in added)


def test_the_tidy_up_fills_primary_company_and_company_name_and_lists_the_rest():
    hs = FakeCRM()
    dal = hs.add("companies", name="Dalchini World food Market", domain="dalchini.example")
    old = hs.add("contacts", email="info@dalchini.example", firstname="Dalchini", jobtitle=INBOX_TITLE)
    hs.links[old] = [dal]                       # linked, no Primary company, no Company name
    kept = hs.add("contacts", email="x@dalchini.example", company="Kept as typed")
    hs.links[kept] = [dal]
    hs.primary = {kept: dal}                    # already right: untouched
    loose = hs.add("contacts", email="chris@dalchini.example")  # linked to nothing; its website matches
    lost = hs.add("contacts", email="someone@nowhere.example")  # nothing matches: listed for a person
    team = hs.add("companies", tagged=False, name="Team Co", domain="team.example")
    theirs = hs.add("contacts", email="a@team.example")
    hs.links[theirs] = [team]                   # only linked to a team company: left alone
    done = linking.fill_primary(hs, quiet)
    assert done == {"primary_set": 1, "names_filled": 2, "linked": 1, "unlinked": [lost]}
    assert hs.primary[old] == dal and hs.primary[loose] == dal and hs.links[loose] == [dal]
    assert hs.records["contacts"][old]["company"] == "Dalchini World food Market"
    assert hs.records["contacts"][loose]["company"] == "Dalchini World food Market"
    assert hs.records["contacts"][kept]["company"] == "Kept as typed"
    assert theirs not in hs.primary
    assert linking.fill_primary(hs, quiet) == {"primary_set": 0, "names_filled": 0, "linked": 0, "unlinked": [lost]}


def test_a_company_with_one_person_gets_the_rest_and_its_inbox_moves_after_them(tmp_path):
    hs = FakeCRM()
    cid = _gate1(hs, "Beta Foods", "beta.example")
    first = _contact(hs, cid, "first@beta.example", 1)
    inbox = _contact(hs, cid, "info@beta.example", 2, title=INBOX_TITLE)
    apollo = FakeApollo({"beta.example": _people("b1", "b2")},
                        {"b1": ("first@beta.example", "verified"), "b2": ("second@beta.example", "verified")})
    s = load_settings()
    assert s["contacts"]["per_company"] == 2
    find_contacts.run("test", s, hs, apollo, log=quiet)
    new = [rid for rid, r in hs.records["contacts"].items() if r["email"] == "second@beta.example"]
    assert len(new) == 1 and hs.records["contacts"][new[0]]["diablo_outreach_order"] == "2"
    assert hs.records["contacts"][first]["diablo_outreach_order"] == "1"
    assert hs.records["contacts"][inbox]["diablo_outreach_order"] == "3"  # the people go first
    assert hs.records["companies"][cid]["hs_lead_status"] == "GATE1: Approved for outreach"
    assert hs.primary[new[0]] == cid
    assert json.loads(find_contacts.TOPPED_FILE.read_text()) == {cid: find_contacts._month()}
    # Now full: never searched again.
    searches = len(apollo.searches)
    find_contacts.run("test", s, hs, apollo, log=quiet)
    assert len(apollo.searches) == searches


def test_nobody_more_in_apollo_changes_nothing_and_waits_for_next_month(monkeypatch):
    hs = FakeCRM()
    cid = _gate1(hs, "Gamma Foods", "gamma.example")
    _contact(hs, cid, "only@gamma.example", 1)
    apollo = FakeApollo({"gamma.example": []}, {})
    s = load_settings()
    find_contacts.run("test", s, hs, apollo, log=quiet)
    assert hs.records["companies"][cid]["hs_lead_status"] == "GATE1: Approved for outreach"  # not Missing Info
    assert len(apollo.searches) >= 1
    searches = len(apollo.searches)
    find_contacts.run("test", s, hs, apollo, log=quiet)  # the same month: not asked again
    assert len(apollo.searches) == searches
    monkeypatch.setattr(find_contacts, "_month", lambda: "NOV2026")  # the next month: asked again
    find_contacts.run("test", s, hs, apollo, log=quiet)
    assert len(apollo.searches) > searches


def test_new_companies_go_before_top_ups():
    hs = FakeCRM()
    old = _gate1(hs, "Old Co", "old.example")
    _contact(hs, old, "one@old.example", 1)
    new = _gate1(hs, "New Co", "new.example")
    apollo = FakeApollo({"old.example": _people("o1"), "new.example": _people("n1")},
                        {"o1": ("two@old.example", "verified"), "n1": ("one@new.example", "verified")})
    s = load_settings()
    s["contacts"]["companies_per_run"] = 1
    summary = find_contacts.run("test", s, hs, apollo, log=quiet)
    assert [d for d, _, _ in apollo.searches][0] == "new.example"
    assert "Waiting to run 1 company" in summary["gate1"]


def test_the_summary_line_counts_every_company_on_gate_1():
    rows = [{"company": "A", "contacts": 2, "kind": "new", "result": "contacts found"},
            {"company": "B", "contacts": 2, "kind": "new", "result": "contacts found"},
            {"company": "C", "contacts": 1, "kind": "topup", "result": "topped up"},
            {"company": "D", "contacts": 1, "kind": "new", "result": "company inbox added"},
            {"company": "Kanela", "contacts": 0, "kind": "new", "exists": True, "result": "no contacts found"},
            {"company": "Sport Benzin", "contacts": 0, "kind": "new", "nowhere": True, "result": "no contacts found"},
            {"company": "Go Fitness", "contacts": 0, "kind": "new", "nowhere": True, "result": "no contacts found"},
            {"company": "E", "contacts": 0, "kind": "topup", "result": "no more found"}]
    cfg = {"per_company": 2, "companies_per_run": 25}
    full = [{"id": "f1", "properties": {"name": "Full One"}}, {"id": "f2", "properties": {"name": "Full Two"}}]
    held = {"f1": 4, "f2": 2, "t1": 1, "l1": 0}
    text = find_contacts.gate1_summary(13, rows, full=full, tried=[{"id": "t1"}], left=[{"id": "l1"}], cfg=cfg,
                                       held=held)
    assert text == """Out of 13 companies on GATE 1: ran 8 (Total 6 contacts)
- Found 2 contacts each for 2 companies (4 contacts)
- Found 1 contact for 2 companies (1 of them topped up, 1 of them a company inbox) (2 contacts)
- 1 company already has contacts in the CRM: Kanela (0 contacts)
- 2 companies had no contacts at any source, might need manual intervention: Sport Benzin, Go Fitness (0 contacts)
- 1 company had fewer than 2 contacts and Apollo had nobody else; it goes ahead with the contacts it has, and Apollo is checked again next month: E (0 contacts)

Not run this time:
- Waiting to run 1 company"""
