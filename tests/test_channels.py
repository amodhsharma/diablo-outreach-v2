"""20 Nov 2026 (Ariel, HARD RULE): before any company is selected, restarted or emailed, its channel is checked
first, no matter what. Only distributors, wholesalers, importers and supermarket chains go ahead."""

import json

import pytest

from outreach import channels, common, find_contacts, send

from .fakes import FakeInstantly
from .test_restart import LINE, LS, ORDER, apollo_with_three, crm, quiet, settings

pytestmark = pytest.mark.channels
PAUSED = "Unqualified: Channel no longer targeted"


def _company(hs, name, industry, status="GATE1: Approved for outreach", people=1):
    cid = hs.add("companies", name=name, domain=f"{name.lower()}.example", country="Australia",
                 industry_type=industry, **{LS: status})
    for rank in range(1, people + 1):
        pid = hs.add("contacts", email=f"p{rank}@{name.lower()}.example", firstname="P", lastname="L",
                     jobtitle="Buyer", diablo_company_note="imports sweets",
                     **{ORDER: str(rank), LS: "APPROVED_TO_SEND", LINE: "Line."})
        hs.links[pid] = [cid]
    return cid


def test_button_3_checks_the_channel_before_apollo():
    hs, apollo = crm(), apollo_with_three()
    shop = _company(hs, "Shop", "Specialist retail", people=0)
    unknown = _company(hs, "Mystery", "", people=0)
    shown = []
    find_contacts.run("test", settings(on=False), hs, apollo, log=shown.append)
    assert hs.records["companies"][shop][LS] == PAUSED
    assert hs.records["companies"][unknown][LS] == "GATE1: Approved for outreach"  # waits for its channel
    assert apollo.revealed == []
    assert any("Channel check: 1 companies wait" in line and "Mystery" in line for line in shown)


def test_button_4_emails_nobody_at_a_company_from_another_channel():
    hs, instantly = crm(), FakeInstantly()
    good = _company(hs, "Alpha", "Distributor Wholesaler", "Contact located. Queued for processing")
    bad = _company(hs, "Vendo", "Foodservice Catering", "Contact located. Queued for processing")
    send.run("test", settings(on=False), hs, instantly, log=quiet)
    emails = {l["email"] for k in instantly.campaigns for l in instantly.leads[k]}
    assert emails == {"p1@alpha.example"}
    assert hs.records["companies"][bad][LS] == PAUSED
    assert hs.records["companies"][good][LS] != PAUSED


def test_the_channel_set_by_hand_wins(tmp_path, monkeypatch):
    path = tmp_path / "company_channels.json"
    path.write_text(json.dumps({"companies": {"vendco.example": "Snack vending operators",
                                              "name:no website co": "Supermarket chains"}}))
    monkeypatch.setattr(common, "CHANNELS_FILE", path)
    monkeypatch.setattr(common, "_CHANNELS", {})
    notes = {"vendco.example": {"category": "Snack distributors"}}
    assert channels.verdict({"domain": "https://www.vendco.example/"}, notes) is False  # research named it wrongly
    assert channels.verdict({"name": "No Website Co"}, notes) is True
    assert channels.verdict({"domain": "lidl.example", "industry_type": "Grocery Retail"}, notes) is None
