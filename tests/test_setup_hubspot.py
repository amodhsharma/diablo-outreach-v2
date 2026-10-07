"""Offline tests for the HubSpot field setup. Run: python -m pytest -q"""

import pytest

from outreach import setup_hubspot
from outreach.hubspot_client import HubSpotError
from outreach.schema import GROUP_NAME, PROPERTIES


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


def test_creates_everything_once_then_is_idempotent():
    hs = FakeHubSpot()
    first = setup_hubspot.run(hs, log=quiet)
    total = sum(len(v) for v in PROPERTIES.values())
    assert first == {"created": total}
    assert all(g[0]["name"] == GROUP_NAME for g in hs.groups.values())

    second = setup_hubspot.run(hs, log=quiet)
    assert second == {"unchanged": total}
    assert all(len(g) == 1 for g in hs.groups.values())


def test_adds_missing_dropdown_options_without_removing_existing():
    hs = FakeHubSpot()
    setup_hubspot.run(hs, log=quiet)
    status = hs.props["companies"]["diablo_outreach_status"]
    status["options"] = status["options"][:2] + [{"label": "Custom", "value": "custom", "displayOrder": 99}]
    summary = setup_hubspot.run(hs, log=quiet)
    assert summary["updated"] == 1
    values = {o["value"] for o in hs.props["companies"]["diablo_outreach_status"]["options"]}
    assert "custom" in values and "interested" in values


def test_refuses_live_account_without_flag():
    hs = FakeHubSpot(portal=setup_hubspot.PRODUCTION_PORTAL_ID)
    with pytest.raises(HubSpotError):
        setup_hubspot.run(hs, log=quiet)
    assert hs.calls == []  # nothing was touched
    setup_hubspot.run(hs, allow_production=True, log=quiet)


def test_type_conflict_is_reported_not_overwritten():
    hs = FakeHubSpot()
    hs.props["contacts"]["diablo_market"] = {"name": "diablo_market", "type": "number"}
    summary = setup_hubspot.run(hs, log=quiet)
    assert summary["conflict"] == 1
    assert hs.props["contacts"]["diablo_market"]["type"] == "number"


def test_schema_rules():
    for obj, specs in PROPERTIES.items():
        names = [s["name"] for s in specs]
        assert len(names) == len(set(names)), obj
        for s in specs:
            assert s["name"].startswith("diablo_")
            assert len(s["name"]) <= 100
            if s["type"] in ("enumeration", "bool"):
                values = [o["value"] for o in s["options"]]
                assert len(values) == len(set(values)), s["name"]
    uniques = [s for s in PROPERTIES["companies"] if s.get("hasUniqueValue")]
    assert uniques == []  # companies are matched on HubSpot's own Domain field
    assert sum(len(v) for v in PROPERTIES.values()) == 17


def test_dry_run_needs_no_key():
    summary = setup_hubspot.run(None, dry_run=True, log=quiet)
    assert summary == {"planned": sum(len(v) for v in PROPERTIES.values())}
