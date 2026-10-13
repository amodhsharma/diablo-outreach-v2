"""Tests for markets below country level, exclusion of existing HubSpot companies,
stopping for the whole company and salesperson assignment."""

import pytest

from outreach import common, find_contacts, send
from outreach.assign import Assigner
from outreach.common import PipelineError, country_of, load_settings, market_matches

from .fakes import FakeApollo, FakeCRM, FakeInstantly


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)
    from outreach import find_contacts as _fc
    monkeypatch.setattr(_fc, "SKIPPED_FILE", tmp_path / "apollo_skipped.json")
    monkeypatch.setattr(_fc, "KEPT_FILE", tmp_path / "apollo_kept.json")
    monkeypatch.setattr(common, "NOTES_FILE", tmp_path / "company_notes.json")


@pytest.fixture
def settings():
    s = load_settings()
    s["send"]["sending_accounts"] = ["team@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"  # the real link is not set yet ("xxx")
    return s


def test_market_helpers():
    assert country_of("Mumbai, India") == "India"
    assert country_of("India") == "India"
    assert market_matches("India", "Mumbai, India")
    assert market_matches("mumbai", "Mumbai, Maharashtra, India")
    assert not market_matches("India", "Indiana, United States")
    assert not market_matches("Delhi", "Mumbai, India")


def test_schedule_and_stop_for_company(settings):
    assert settings["send"]["schedule"]["default"]["from"] == "00:00"  # agreed: any time, every day
    body = send.campaign_body("Diablo | Dublin, Ireland | X | OCT2026", "Dublin, Ireland", settings)
    assert all(body["campaign_schedule"]["schedules"][0]["days"].values())
    settings["send"]["schedule"]["India"] = {"timezone": "Asia/Kolkata", "from": "10:00", "to": "17:00",
                                             "days": ["mon", "tue", "wed", "thu", "fri"]}
    settings["send"]["schedule"]["Mumbai"] = {"timezone": "Asia/Kolkata", "from": "11:00", "to": "16:00"}
    assert send.schedule_for("Pune, India", settings["send"]["schedule"])["from"] == "10:00"
    assert send.schedule_for("Mumbai, India", settings["send"]["schedule"])["from"] == "11:00"
    assert send.schedule_for("Kenya", settings["send"]["schedule"])["timezone"] == "Europe/London"
    body = send.campaign_body("Diablo | Pune, India | X | 2026-10", "Pune, India", settings)
    assert body["stop_for_company"] is True and body["stop_on_reply"] is True
    assert body["campaign_schedule"]["schedules"][0]["days"] == {
        "0": False, "1": True, "2": True, "3": True, "4": True, "5": True, "6": False}


def assignment_settings(settings):
    settings["assignment"] = {
        "rules": [
            {"market": "India", "owners": ["sam@diablosugarfree.com", "ria@diablosugarfree.com"]},
            {"market": "Mumbai, India", "category": "Pharmacy distributor", "owners": ["kai@diablosugarfree.com"]},
        ],
        "default_owners": [],
    }
    return settings


def test_assigner_rules_and_even_sharing(settings):
    hs = FakeCRM()
    a = Assigner(hs, assignment_settings(settings), log=quiet)
    assert a.owners_for("Mumbai, India", "Pharmacy distributor") == ["kai@diablosugarfree.com"]
    assert a.owners_for("Mumbai, India", "Grocery wholesaler") == ["sam@diablosugarfree.com", "ria@diablosugarfree.com"]
    assert a.owners_for("Kenya", "Grocery wholesaler") == []
    picks = [a.pick("Delhi, India", "Grocery wholesaler") for _ in range(4)]
    assert sorted(picks) == ["11", "11", "22", "22"]
    assert a.pick("Kenya", "Grocery wholesaler") is None


def test_assigner_counts_existing_load(settings):
    hs = FakeCRM()
    for _ in range(3):
        hs.add("companies", hubspot_owner_id="11", country="India")
    for _ in range(5):  # the team's own companies never count
        hs.add("companies", tagged=False, hubspot_owner_id="22", country="India")
    a = Assigner(hs, assignment_settings(settings), log=quiet)
    assert a.pick("India", "Grocery wholesaler") == "22"


def test_assigner_rejects_unknown_salesperson(settings):
    settings["assignment"] = {"rules": [{"market": "India", "owners": ["nobody@diablosugarfree.com"]}]}
    with pytest.raises(PipelineError):
        Assigner(FakeCRM(), settings, log=quiet)


def test_assigner_off_when_empty(settings):
    a = Assigner(FakeCRM(), settings, log=quiet)
    assert not a.enabled and a.pick("India", "Grocery wholesaler") is None


def test_find_contacts_assigns_company_and_contacts(settings):
    hs = FakeCRM()
    common.save_company_notes({"medco.in": {"category": "Pharmacy distributor"}})
    cid = hs.add("companies", name="Med Co", domain="medco.in", city="Mumbai", country="India",
                 industry_type="Distributor Wholesaler", hs_lead_status="GATE1: Approved for outreach")
    kept = hs.add("companies", name="Owned Co", domain="owned.in", country="India",
                  hs_lead_status="GATE1: Approved for outreach", hubspot_owner_id="99")
    apollo = FakeApollo({"medco.in": [{"id": "m1"}], "owned.in": [{"id": "o1"}]},
                        {"m1": ("buyer@medco.in", "verified"), "o1": ("buyer@owned.in", "verified")})
    find_contacts.run("test", assignment_settings(settings), hs, apollo, log=quiet)

    assert hs.records["companies"][cid]["hubspot_owner_id"] == "33"
    assert hs.records["companies"][kept]["hubspot_owner_id"] == "99"  # existing owner kept
    owners = {c["email"]: c.get("hubspot_owner_id") for c in hs.records["contacts"].values()}
    assert owners == {"buyer@medco.in": "33", "buyer@owned.in": "99"}


def test_follow_up_after_three_days(settings):
    # With rounds of emails (agreed 13 Oct 2026) Instantly sends only the first email.
    assert len(send.campaign_body("Diablo | X", "India", settings)["sequences"][0]["steps"]) == 1
    settings["send"]["rotation"]["rounds"] = 1  # the earlier way: Instantly sends the reminder itself
    body = send.campaign_body("Diablo | India | X | 2026-10", "India", settings)
    steps = body["sequences"][0]["steps"]
    assert len(steps) == 2
    assert steps[0]["delay"] == 3 and steps[0]["delay_unit"] == "days"
    reminder = steps[1]["variants"][0]
    assert reminder["subject"] == ""  # sent in the same thread
    assert "Joshua<br/>Initial Outreach Team" in reminder["body"] and "border-left" in reminder["body"] and "{{privacy_url}}" not in reminder["body"]
    assert "samples" in reminder["body"]
    assert "\u2014" not in reminder["body"]

    settings["send"]["follow_up"]["enabled"] = False
    body = send.campaign_body("Diablo | India | X | 2026-10", "India", settings)
    assert len(body["sequences"][0]["steps"]) == 1


def test_typed_channel_end_to_end(settings):
    assert common.clean_category("  sugar   free distributor ") == "Sugar free distributor"
    assert common.clean_category("OTC pharmacy distributors") == "OTC pharmacy distributors"
    # Research Channels map onto the live account's Industry Type.
    assert common.industry_type("Sugar free distributor") == "Distributor Wholesaler"
    assert common.industry_type("Health food distributor") == "Distributor Wholesaler"
    assert common.industry_type("Marketplace sellers") == "Online Retailer"
    assert common.industry_type("Online retailers") == "Online Retailer"
    assert common.industry_type("Pharmacy chains") == "Specialist retail"
    assert common.industry_type("Supermarkets") == "Grocery Retail"
    assert common.industry_type("retailers") == "Grocery Retail"
    assert common.industry_type("Hotels and cafés") == "Foodservice Catering"
    assert common.industry_type("Petrol station shops") == "Convenience Impulse"
    assert common.industry_type("Gift shops") == "Other"
    from outreach.next_in_line import partner_type
    assert partner_type("Distributor Wholesaler") == "distributor" and partner_type("Online Retailer") == "online seller"

    # A company as the research import adds it (the import tests cover the import itself).
    hs = FakeCRM()
    common.save_company_notes({"noblefoods.in": {"category": "Sugar free distributor"}})
    cid = hs.add("companies", name="Noble Foods", domain="noblefoods.in", country="India",
                 industry_type="Distributor Wholesaler", hs_lead_status="GATE1: Approved for outreach")

    # Unknown categories use the default job titles; known ones keep their own.
    titles = settings["contacts"]["titles"]
    assert find_contacts.titles_for("Sugar free distributor", titles) == titles["default"]
    assert find_contacts.titles_for("pharmacy DISTRIBUTOR", titles) == titles["Pharmacy distributor"]

    contact = hs.add("contacts", email="buyer@noblefoods.in", firstname="Asha",
                     hs_lead_status="APPROVED_TO_SEND", diablo_personal_line="Line.")
    hs.links[contact] = [cid]
    inst = FakeInstantly()
    send.run("test", settings, hs, inst, log=quiet)
    assert [c["name"] for c in inst.campaigns.values()][0] == "Diablo | " + send.month_label()
    lead = next(iter(inst.leads.values()))[0]
    assert lead["custom_variables"]["partner_type"] == "sugar free distributor"


def test_one_campaign_per_month():
    import datetime as dt
    assert send.month_label(dt.date(2026, 9, 6)) == "SEP2026"
    assert send.campaign_name("Diablo |", month="OCT2026") == "Diablo | OCT2026"


