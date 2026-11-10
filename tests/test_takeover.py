"""10 Nov 2026 (Ariel): the contacts already in HubSpot at approved companies are taken over by button 3
(AUTO-OUTREACH, New) instead of being tagged by hand, and a company with a contact moves on from GATE1 to
"Contact located. Queued for processing" until its first email goes out."""

import pytest

from outreach import common, find_contacts, send, takeover
from outreach.common import load_settings
from outreach.hubspot_client import TagGuardError
from outreach.stages import LeadStatus, forward
from outreach.sync import BlockList

from .fakes import LIVE_COMPANY_STATUS, FakeApollo, FakeCRM

GATE1 = "GATE1: Approved for outreach"
LOCATED = "Contact located. Queued for processing"
EXISTS = "Contact exists, not AUTO-OUTREACH"


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


def _blocklist(monkeypatch, *entries):
    monkeypatch.setattr(takeover, "read_blocked", lambda log=print: BlockList(entries))


def _company(hs, name, domain, status=GATE1, tagged=True):
    return hs.add("companies", tagged=tagged, name=name, domain=domain, country="Australia",
                  industry_type="Distributors", hs_lead_status=status)


def _old(hs, cid, email, status="IN_PROGRESS", **props):
    """One of the team's own contacts (not AUTO-OUTREACH)."""
    pid = hs.add("contacts", tagged=False, email=email, hs_lead_status=status, **props)
    hs.links.setdefault(pid, []).append(cid)
    return pid


def test_old_contacts_at_an_approved_company_become_new_auto_outreach_contacts(monkeypatch):
    _blocklist(monkeypatch, "blocked@kadac.example", "spam.example")
    hs = FakeCRM()
    cid = _company(hs, "Kadac", "kadac.example")
    buyer = _old(hs, cid, "buyer@kadac.example", firstname="Bea", jobtitle="Buyer")
    ceo = _old(hs, cid, "ceo@kadac.example", status="NEW", firstname="Kim", jobtitle="CEO")
    inbox = _old(hs, cid, "info@kadac.example", status="")
    won = _old(hs, cid, "won@kadac.example", status="WON")
    unsubscribed = _old(hs, cid, "gone@kadac.example", hs_email_optout="true")
    blocked = _old(hs, cid, "blocked@kadac.example")
    blocked_domain = _old(hs, cid, "x@spam.example")
    dead = _old(hs, cid, "dead@kadac.example", status="UNQUALIFIED_CONTACT_CORRUPT")
    bounced = _old(hs, cid, "hard@kadac.example", hs_email_hard_bounce_reason_enum="MAILBOX_NOT_FOUND")
    no_email = _old(hs, cid, "")
    customer = _company(hs, "Customer Co", "customer.example", status="Won", tagged=False)
    shared = _old(hs, cid, "shared@kadac.example")
    hs.links[shared].append(customer)
    elsewhere = _company(hs, "Other Co", "other.example", status="In Progress", tagged=False)
    theirs = _old(hs, elsewhere, "someone@other.example")  # not at an approved company: never touched

    apollo = FakeApollo({"kadac.example": [{"id": "a1", "title": "Director", "has_email": True}]},
                        {"a1": ("director@kadac.example", "verified")})
    summary = find_contacts.run("test", load_settings(), hs, apollo, log=quiet)

    c = hs.records["contacts"]
    for pid in (buyer, ceo, inbox):
        assert c[pid]["lead_source"] == "AUTO-OUTREACH" and c[pid]["hs_lead_status"] == "NEW"
        assert c[pid]["hs_legal_basis"] == "Legitimate interest – prospect/lead"
    for pid in (won, unsubscribed, blocked, blocked_domain, dead, bounced, no_email, shared, theirs):
        assert "lead_source" not in c[pid]  # left exactly as they were
    assert c[won]["hs_lead_status"] == "WON" and c[dead]["hs_lead_status"] == "UNQUALIFIED_CONTACT_CORRUPT"
    # Ordered like hand-tagged contacts: the people first (most senior), then the company inbox.
    assert (c[ceo]["diablo_outreach_order"], c[buyer]["diablo_outreach_order"],
            c[inbox]["diablo_outreach_order"]) == ("1", "2", "3")
    assert c[inbox]["jobtitle"] == "Company inbox (from website)"
    # It already has its 2 people: Apollo is not even asked, and the company moves on.
    assert apollo.revealed == [] and apollo.searches == []
    assert hs.records["companies"][cid]["hs_lead_status"] == LOCATED
    assert summary["taken_over"]["taken"] == 3
    assert summary["taken_over"]["skipped"] == {"Won": 2, "dead address": 2, "no email": 1, "opted out": 3}
    assert "Existing contacts taken over (made AUTO-OUTREACH and set to New): 3" in summary["gate1"]
    assert "Kadac: 3" in summary["gate1"]


def test_a_contact_exists_company_comes_back_and_a_located_one_is_looked_at_too(monkeypatch):
    _blocklist(monkeypatch)
    hs = FakeCRM()
    exists = _company(hs, "Timstock", "timstock.example", status=EXISTS)
    old = _old(hs, exists, "orders@timstock.example")
    located = _company(hs, "Garbi", "garbi.example", status=LOCATED)
    ours = hs.add("contacts", email="first@garbi.example", hs_lead_status="NEW", diablo_outreach_order="1")
    hs.links[ours] = [located]
    late = _old(hs, located, "late@garbi.example", firstname="Lee")  # added later by the team
    find_contacts.run("test", load_settings(), hs, FakeApollo({}, {}), log=quiet)
    c = hs.records["contacts"]
    assert c[old]["lead_source"] == "AUTO-OUTREACH" and c[old]["diablo_outreach_order"] == "1"
    assert hs.records["companies"][exists]["hs_lead_status"] == LOCATED  # back in the loop by itself
    assert c[late]["lead_source"] == "AUTO-OUTREACH" and c[late]["diablo_outreach_order"] == "2"  # after ours
    assert hs.records["companies"][located]["hs_lead_status"] == LOCATED


def test_nobody_is_taken_over_when_the_blocklist_cannot_be_read():
    hs = FakeCRM()  # the tests' default: the blocklist is not read
    cid = _company(hs, "Kadac", "kadac.example")
    old = _old(hs, cid, "buyer@kadac.example")
    result = takeover.run(hs, LeadStatus(hs), quiet)
    assert result["taken"] == 0 and result["skipped"] == {"blocklist not read": 1}
    assert "lead_source" not in hs.records["contacts"][old]


def test_a_take_over_may_only_set_the_lead_status_and_the_legal_basis():
    hs = FakeCRM()
    pid = hs.add("contacts", tagged=False, email="a@b.example")
    with pytest.raises(TagGuardError):
        hs.take_over_contacts([(pid, {"hs_lead_status": "NEW", "email": "other@b.example"})])
    assert hs.records["contacts"][pid] == {"email": "a@b.example"}
    with pytest.raises(TagGuardError):  # the usual way still refuses records without the tag
        hs.update_tagged("contacts", [(pid, {"hs_lead_status": "NEW"})])


def test_a_located_company_whose_contacts_all_dropped_out_goes_back_to_gate1_and_apollo_tries_again(monkeypatch):
    hs = FakeCRM()
    cid = _company(hs, "Ferndale", "ferndale.example", status=LOCATED)
    for email, status in (("dead@ferndale.example", "UNQUALIFIED_CONTACT_CORRUPT"),
                          ("no@ferndale.example", "UNQUALIFIED")):  # rejected at GATE2
        pid = hs.add("contacts", email=email, hs_lead_status=status, diablo_outreach_order="1")
        hs.links[pid] = [cid]
    monkeypatch.setattr(find_contacts, "_month", lambda: "JAN2030")
    apollo = FakeApollo({"ferndale.example": []}, {})
    find_contacts.run("test", load_settings(), hs, apollo, log=quiet)
    assert apollo.searches  # searched again: nobody there can still be emailed
    assert hs.records["companies"][cid]["hs_lead_status"] == GATE1
    # With someone new found later, it moves on again.
    monkeypatch.setattr(find_contacts, "_month", lambda: "FEB2030")
    apollo = FakeApollo({"ferndale.example": [{"id": "f1", "title": "Owner", "has_email": True}]},
                        {"f1": ("owner@ferndale.example", "verified")})
    find_contacts.run("test", load_settings(), hs, apollo, log=quiet)
    assert hs.records["companies"][cid]["hs_lead_status"] == LOCATED


def test_before_button_1_adds_the_choice_everything_stays_on_gate1():
    hs = FakeCRM()
    del hs.options[("companies", "hs_lead_status")][LOCATED]
    cid = _company(hs, "Kiss", "kiss.example")
    pid = hs.add("contacts", email="a@kiss.example", hs_lead_status="NEW", diablo_outreach_order="1")
    hs.links[pid] = [cid]
    statuses = LeadStatus(hs)
    assert find_contacts.settle(hs, statuses, quiet) == {"located": [], "back": []}
    assert [c["id"] for c in find_contacts.approved_companies(hs, statuses, ["name"])] == [cid]
    assert hs.records["companies"][cid]["hs_lead_status"] == GATE1


def test_a_located_company_is_sent_to_like_a_gate1_company():
    statuses = LeadStatus(FakeCRM())
    contact = {"properties": {"email": "a@kiss.example", "diablo_personal_line": "A line"}}
    assert send.skip_reason(contact, {"id": "1"}, "located") is None
    assert send.skip_reason(contact, {"id": "1"}, "approved") is None
    assert forward("located", "in_outreach") and forward("approved", "located")
    assert not forward("located", "approved")  # only settle() moves it back, on purpose
    assert statuses.props("companies", "located") == {"hs_lead_status": LOCATED}
    assert LOCATED in LIVE_COMPANY_STATUS
