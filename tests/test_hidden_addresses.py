"""1 Nov 2026 (Ariel): addresses hidden by Cloudflare's email protection are read (Cycle Fitness Nutrition
showed info@ to people and "[email protected]" to button 3), and "Missing Info" companies whose website
shows an address after all go back on GATE1, each website read again once."""

import json

import pytest

from outreach import apollo_status, common, company_inbox, find_contacts
from outreach.common import load_settings
from outreach.schema import INBOX_TITLE

from .fakes import FakeApollo, FakeCRM


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


def scrambled(email, key=0x42):
    return f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in email)


def test_cloudflare_hidden_addresses_are_read():
    code = scrambled("info@cyclefitnessnutrition.com")
    page = (f'<li><a href="/cdn-cgi/l/email-protection#{code}"><span class="__cf_email__" data-cfemail="{code}">'
            "[email&#160;protected]</span></a></li>")
    assert company_inbox.emails_in(page) == ["info@cyclefitnessnutrition.com"]
    assert company_inbox.emails_in("<p>[email protected]</p>") == []


def nowhere(hs, name, domain):
    return hs.add("companies", name=name, domain=domain, country="Australia", industry_type="Retailers",
                  hs_lead_status="Missing Info",
                  diablo_stop_reason="No contact found anywhere (2026-11-01): nobody in Apollo and no usable address "
                                     "on its website")


def test_missing_info_websites_are_read_once_and_found_ones_go_back_to_gate_1(monkeypatch):
    hs = FakeCRM()
    found = nowhere(hs, "Cycle Fitness Nutrition", "cyclefitnessnutrition.com")
    empty = nowhere(hs, "Quiet Shop", "quiet.example")
    other = hs.add("companies", name="No Site", hs_lead_status="Missing Info")  # no note: left alone
    sites = {"cyclefitnessnutrition.com": "info@cyclefitnessnutrition.com"}
    read = []

    def find(domain, name=None, **_):
        read.append(domain)
        return sites.get(domain)

    monkeypatch.setattr(company_inbox, "find_inbox", find)
    monkeypatch.setattr(company_inbox, "can_receive_mail", lambda d: True)
    apollo = FakeApollo({"cyclefitnessnutrition.com": [], "quiet.example": []}, {})
    summary = find_contacts.run("test", load_settings(), hs, apollo, log=quiet)
    assert hs.records["companies"][empty]["hs_lead_status"] == "Missing Info"
    assert hs.records["companies"][other]["hs_lead_status"] == "Missing Info"
    # Back on GATE1 and, in the same run, given the address as its company inbox.
    inbox = [r for r in hs.records["contacts"].values() if r["email"] == "info@cyclefitnessnutrition.com"]
    assert len(inbox) == 1 and inbox[0]["jobtitle"] == INBOX_TITLE
    # 10 Nov 2026: with its company inbox it moves on to "Contact located. Queued for processing"
    assert hs.records["companies"][found]["hs_lead_status"] == "Contact located. Queued for processing"
    assert "back on GATE 1: Cycle Fitness Nutrition" in summary["gate1"]
    assert sorted(json.loads(apollo_status._rechecked_file().read_text())) == sorted([found, empty])
    before = len(read)
    find_contacts.run("test", load_settings(), hs, apollo, log=quiet)  # each website is read again only once
    assert [d for d in read[before:] if d == "quiet.example"] == []


def test_at_most_a_limited_number_of_websites_a_run():
    hs = FakeCRM()
    for i in range(5):
        nowhere(hs, f"Shop {i}", f"shop{i}.example")
    from outreach.stages import LeadStatus
    got = apollo_status.recheck_websites(hs, LeadStatus(hs), quiet, limit=2, find=lambda d, name=None: None)
    assert got["read"] == 2 and got["left"] == 3 and got["back_to_gate1"] == []
