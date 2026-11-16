"""16 Nov 2026 (Ariel): "Contact exists, not AUTO-OUTREACH" only means there is a person you can tag. When none
of the contacts already in HubSpot can be used, button 3 sets the company to "Missing Info" with the real reason,
for new cases and for the companies already on "Contact exists"."""

import pytest

from outreach import apollo_status, common, company_inbox, find_contacts, takeover
from outreach.common import load_settings
from outreach.schema import TAG, TAG_PROPERTY
from outreach.stages import LeadStatus
from outreach.sync import BlockList

from .fakes import FakeApollo, FakeCRM

EXISTS = "Contact exists, not AUTO-OUTREACH"
GATE1 = "GATE1: Approved for outreach"


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(takeover, "read_blocked", lambda log=print: BlockList(["blocked@shop.example"]))


def _company(hs, name, status=EXISTS, tagged=True):
    return hs.add("companies", tagged=tagged, name=name, domain=name.lower() + ".example", country="Australia",
                  hs_lead_status=status)


def _contact(hs, companies, tagged=False, **props):
    pid = hs.add("contacts", tagged=tagged, **props)
    hs.links[pid] = list(companies)
    return pid


def _run(hs):
    find_contacts.run("test", load_settings(), hs, FakeApollo({}, {}), log=quiet)


def test_the_four_cases_seen_on_16_nov_become_missing_info_with_the_reason():
    hs = FakeCRM()
    no_email = _company(hs, "Direct")
    _contact(hs, [no_email], firstname="Camilla")
    bounced = _company(hs, "Stern")
    _contact(hs, [bounced], email="info@stern.example", hs_email_hard_bounce_reason_enum="MAILBOX_FULL")
    real = _company(hs, "Westco", status="Attempted to Contact")
    duplicate = _company(hs, "Westco2")
    for email in ("harvey@westco.example", "libby@westco.example"):
        _contact(hs, [real, duplicate], tagged=True, email=email, hs_lead_status="ATTEMPTED_TO_CONTACT")
    _run(hs)
    co = hs.records["companies"]
    for cid in (no_email, bounced, duplicate):
        assert co[cid]["hs_lead_status"] == "Missing Info"
        assert co[cid]["diablo_stop_reason"].startswith("No usable contact (")
    assert "the only contact has no email address" in co[no_email]["diablo_stop_reason"]
    assert "the only contact's address bounced" in co[bounced]["diablo_stop_reason"]
    assert ("none of its 2 contacts can be used: 2 are already AUTO-OUTREACH under another company record "
            "(this may be a duplicate)") in co[duplicate]["diablo_stop_reason"]
    assert co[real]["hs_lead_status"] == "Attempted to Contact"  # the real record is never touched


def test_a_contact_you_can_tag_keeps_contact_exists_and_one_in_the_loop_here_counts_too(monkeypatch):
    monkeypatch.setattr(takeover, "read_blocked", lambda log=print: BlockList([], ok=False))
    hs = FakeCRM()
    cid = _company(hs, "Shop")
    _contact(hs, [cid], email="buyer@shop.example")  # blocklist unread: not taken over, but still taggable
    _run(hs)
    assert hs.records["companies"][cid]["hs_lead_status"] == EXISTS
    statuses = LeadStatus(hs)
    here = _company(hs, "Here")
    mine = hs.add("contacts", email="a@here.example")
    hs.links[mine] = [here]
    assert apollo_status.unusable_reasons(hs, statuses, here, hs.batch_read("contacts", [mine], ["email"])) is None


def test_a_blocked_contact_counts_as_opted_out_and_mixed_reasons_are_listed():
    hs = FakeCRM()
    cid = _company(hs, "Shop")
    _contact(hs, [cid], email="blocked@shop.example")
    _contact(hs, [cid], firstname="No address")
    _contact(hs, [cid], email="gone@shop.example", hs_email_optout="true")
    _run(hs)
    reason = hs.records["companies"][cid]["diablo_stop_reason"]
    assert hs.records["companies"][cid]["hs_lead_status"] == "Missing Info"
    assert "none of its 3 contacts can be used: 2 opted out, 1 have no email address" in reason


def test_a_new_case_found_by_button_3_goes_straight_to_missing_info(monkeypatch):
    hs = FakeCRM()
    cid = _company(hs, "Bounce", status=GATE1)
    dead = _contact(hs, [cid], email="info@bounce.example", hs_email_hard_bounce_reason_enum="MAILBOX_NOT_FOUND")
    monkeypatch.setattr(company_inbox, "find_inbox", lambda domain, **k: "info@bounce.example")
    _run(hs)
    company = hs.records["companies"][cid]
    assert company["hs_lead_status"] == "Missing Info"
    assert "the only contact's address bounced" in company["diablo_stop_reason"]
    assert TAG_PROPERTY not in hs.records["contacts"][dead]  # never changed


def test_tagging_a_fixed_contact_by_hand_still_sends_it_back_to_gate1():
    hs = FakeCRM()
    cid = _company(hs, "Direct")
    pid = _contact(hs, [cid], firstname="Camilla")
    _run(hs)
    assert hs.records["companies"][cid]["hs_lead_status"] == "Missing Info"
    hs.records["contacts"][pid].update({"email": "camilla@direct.example", TAG_PROPERTY: TAG})
    _run(hs)
    assert hs.records["companies"][cid]["hs_lead_status"] in (GATE1, "Contact located. Queued for processing")
