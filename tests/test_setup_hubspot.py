"""Offline tests for the HubSpot field setup. Run: python -m pytest -q"""

import pytest

from outreach import setup_hubspot
from outreach.hubspot_client import HubSpotError
from outreach.schema import CONTACT_SOURCE, COMPANY_NOTE, GROUP_NAME, INDUSTRY_TYPES, NEW_PROPERTIES, ORDER, PERSONAL_LINE, STOP_REASON
from outreach.stages import STAGES


class FakeHubSpot:
    """Pretends to be the HubSpot API, keeping properties in memory."""

    def __init__(self, portal=12345):
        self.portal = portal
        self.groups = {"companies": [], "contacts": []}
        self.props = {"companies": {}, "contacts": {}}
        self.calls = []

    def portal_id(self):
        return self.portal

    def request(self, method, path, json=None, **_):
        self.calls.append((method, path))
        parts = path.strip("/").split("/")  # crm v3 properties <obj> [groups|name]
        obj = parts[3]
        if path.endswith("/groups"):
            if method == "GET":
                return {"results": self.groups[obj]}
            self.groups[obj].append(json)
            return json
        if method == "GET":
            return {"results": list(self.props[obj].values())}
        if method == "POST":
            assert json["name"] not in self.props[obj], "created twice"
            self.props[obj][json["name"]] = json
            return json
        if method == "PATCH":
            self.props[obj][parts[4]].update(json)
            return self.props[obj][parts[4]]
        raise AssertionError(path)


def quiet(_):
    pass


def options(pairs):
    return [{"label": label, "value": value, "displayOrder": i, "hidden": False}
            for i, (value, label) in enumerate(pairs)]


LIVE_COMPANY = [("New", "New"), ("Missing Info", "Missing Info"), ("Emailed", "Emailed"),
                ("In Progress", "In Progress"), ("Unqualified", "Unqualified"),
                ("Attempted to Contact", "Attempted to Contact"), ("Won", "Won")]
LIVE_CONTACT = [("NEW", "New"), ("MISSING INFO", "Missing Info"), ("Emailed", "Emailed"),
                ("IN_PROGRESS", "In Progress"), ("UNQUALIFIED", "Unqualified"),
                ("ATTEMPTED_TO_CONTACT", "Attempted to Contact"), ("WON", "WON")]
FRESH_CONTACT = [("NEW", "New"), ("OPEN", "Open"), ("IN_PROGRESS", "In Progress"), ("OPEN_DEAL", "Open Deal"),
                 ("UNQUALIFIED", "Unqualified"), ("ATTEMPTED_TO_CONTACT", "Attempted to Contact"),
                 ("CONNECTED", "Connected"), ("BAD_TIMING", "Bad Timing")]


def live_like(portal=setup_hubspot.PRODUCTION_PORTAL_ID):
    hs = FakeHubSpot(portal)
    hs.props["companies"] = {
        "hs_lead_status": {"name": "hs_lead_status", "type": "enumeration", "options": options(LIVE_COMPANY)},
        "lead_source": {"name": "lead_source", "type": "string"},
        "industry_type": {"name": "industry_type", "type": "enumeration",
                          "options": options(INDUSTRY_TYPES[:6])},  # one choice short, on purpose
    }
    hs.props["contacts"] = {
        "hs_lead_status": {"name": "hs_lead_status", "type": "enumeration", "options": options(LIVE_CONTACT)},
        "lead_source": {"name": "lead_source", "type": "string"},
    }
    return hs


def fresh_test():
    hs = FakeHubSpot()
    hs.props["companies"] = {"hs_lead_status": {"name": "hs_lead_status", "type": "enumeration",
                                                "options": options(FRESH_CONTACT)}}
    hs.props["contacts"] = {"hs_lead_status": {"name": "hs_lead_status", "type": "enumeration",
                                               "options": options(FRESH_CONTACT)}}
    return hs


def labels(hs, obj):
    return [o["label"] for o in hs.props[obj]["hs_lead_status"]["options"]]


def test_live_gets_exactly_four_fields_and_five_choices():
    hs = live_like()
    before = {obj: [dict(o) for o in hs.props[obj]["hs_lead_status"]["options"]] for obj in ("companies", "contacts")}
    summary = setup_hubspot.run(hs, allow_production=True, log=quiet)
    # the two groups, the five contact fields, (19 Oct 2026) the company's "Outreach stopped because"
    # and (21 Oct 2026) its "Job Number"
    assert summary["created"] == 9
    # GATE1: Approved for outreach; "New, Personal line filled", GATE2: Approved to send, and (14 Oct 2026)
    # "Forward sent" and "Reminder sent", and (19 Oct 2026) the three "Colleague replied" choices and
    # "Colleague opted out", and (21 Oct 2026) "Unqualified company" and, on both, "Contacted, but no
    # response, unqualified", and (23 Oct 2026) the company's "Missing info on Apollo" and (26 Oct 2026)
    # "Contact exists, not AUTO-OUTREACH", and (28 Oct 2026) the company's "Invalid inbox: Mail bounced, need
    # input" and the contact's "Unqualified Contact: Contact corrupt"
    assert summary["updated"] == 16
    assert set(hs.props["contacts"]) == {"hs_lead_status", "lead_source", PERSONAL_LINE, COMPANY_NOTE, ORDER,
                                         CONTACT_SOURCE, STOP_REASON}
    assert set(hs.props["companies"]) == {"hs_lead_status", "lead_source", "industry_type", STOP_REASON,
                                          "diablo_job_number"}
    assert sorted(labels(hs, "companies")[-5:]) == sorted(["GATE1: Approved for outreach",
                                                          "Contacted, but no response, unqualified",
                                                          "Missing info on Apollo",
                                                          "Contact exists, not AUTO-OUTREACH",
                                                          "Invalid inbox: Mail bounced, need input"])
    assert sorted(labels(hs, "contacts")[-11:]) == sorted(["New, Personal line filled", "GATE2: Approved to send",
                                                          "Forward sent", "Reminder sent", "Colleague replied: positive",
                                                          "Colleague replied: negative", "Colleague replied",
                                                          "Colleague opted out", "Unqualified company",
                                                          "Contacted, but no response, unqualified",
                                                          "Unqualified Contact: Contact corrupt"])
    for obj in ("companies", "contacts"):  # the team's choices are sent back exactly as they were
        assert hs.props[obj]["hs_lead_status"]["options"][:len(before[obj])] == before[obj]
    assert len(hs.props["companies"]["industry_type"]["options"]) == 6  # live's own field: untouched
    assert hs.groups["companies"][0]["name"] == hs.groups["contacts"][0]["name"] == GROUP_NAME

    again = setup_hubspot.run(hs, allow_production=True, log=quiet)
    assert set(again) == {"unchanged"}


def test_fresh_test_account_is_made_to_match_live():
    hs = fresh_test()
    setup_hubspot.run(hs, log=quiet)
    assert hs.props["companies"]["lead_source"]["type"] == "string"
    assert hs.props["contacts"]["lead_source"]["type"] == "string"
    assert [o["value"] for o in hs.props["companies"]["industry_type"]["options"]] == [v for v, _ in INDUSTRY_TYPES]
    for obj, stages in STAGES.items():
        have = {x.lower() for x in labels(hs, obj)}
        assert all(label.lower() in have for label in stages.values()), obj
    assert labels(hs, "contacts")[:8] == [label for _, label in FRESH_CONTACT]  # existing ones first, unchanged
    assert set(setup_hubspot.run(hs, log=quiet)) == {"unchanged"}


def test_refuses_live_account_without_flag_but_a_dry_run_only_reads():
    hs = live_like()
    with pytest.raises(HubSpotError):
        setup_hubspot.run(hs, log=quiet)
    assert hs.calls == []  # nothing was touched
    shown = []
    summary = setup_hubspot.run(hs, dry_run=True, log=shown.append)
    assert all(method == "GET" for method, _ in hs.calls)
    assert summary["updated"] == 16 and any("[would add]" in line for line in shown)
    assert "New, Personal line filled" not in labels(hs, "contacts")


def test_type_conflict_is_reported_not_overwritten():
    hs = live_like(portal=5)
    hs.props["contacts"][ORDER] = {"name": ORDER, "type": "string"}
    summary = setup_hubspot.run(hs, log=quiet)
    assert summary["conflict"] == 1
    assert hs.props["contacts"][ORDER]["type"] == "string"


def test_schema_rules():
    assert [s["name"] for s in NEW_PROPERTIES["contacts"]] == [PERSONAL_LINE, COMPANY_NOTE, ORDER, CONTACT_SOURCE,
                                                               STOP_REASON]
    assert [s["name"] for s in NEW_PROPERTIES["companies"]] == ["diablo_job_number", STOP_REASON]
    assert all(s["name"].startswith("diablo_") for s in NEW_PROPERTIES["contacts"])


def test_dry_run_needs_no_key():
    summary = setup_hubspot.run(None, dry_run=True, log=quiet)
    assert summary == {"planned": 1}


def test_live_never_gets_other_choices_or_fields():
    hs = live_like()
    hs.props["companies"]["hs_lead_status"]["options"] = options([v for v in LIVE_COMPANY if v[1] != "Missing Info"])
    del hs.props["contacts"]["lead_source"]
    summary = setup_hubspot.run(hs, allow_production=True, log=quiet)
    assert summary["conflict"] == 2  # reported, not added
    assert "Missing Info" not in labels(hs, "companies") and "lead_source" not in hs.props["contacts"]
    assert "GATE1: Approved for outreach" in labels(hs, "companies")[-4:]


def test_every_run_shows_the_key_steps_and_a_plain_reason(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    assert setup_hubspot.main([]) == 1  # a real run with no key fails
    text = summary.read_text()
    assert "Button 1 result: FAILED" in text and "`HUBSPOT_TOKEN_TEST` is empty" in text
    assert "Development > Testing > Test accounts" in text and "Development > Legacy apps" in text
    assert all(scope in text for scope in setup_hubspot.SCOPES) and len(setup_hubspot.SCOPES) == 9
    summary.write_text("")
    assert setup_hubspot.main(["--dry-run"]) == 0  # a dry run with no key says it checked nothing
    assert "NOT CHECKED (no key)" in summary.read_text()


def test_errors_are_explained_in_plain_words():
    assert "did not accept the key" in setup_hubspot.explain(HubSpotError("GET /x failed with 401: bad"))[0]
    assert "did not accept the key" in setup_hubspot.explain(
        HubSpotError("Could not work out which HubSpot account this key belongs to."))[0]
    assert "missing one of the 9 scopes" in setup_hubspot.explain(HubSpotError("PATCH /x failed with 403: no"))[0]
    assert "HUBSPOT_TOKEN_LIVE" in setup_hubspot.explain(
        HubSpotError("HUBSPOT_TOKEN is not set."), "HUBSPOT_TOKEN_LIVE")[0]
