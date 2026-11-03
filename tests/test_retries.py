"""When HubSpot or Instantly does not answer, the request is tried again, up to 3 times, but only where a
second try can do no harm (agreed 3 Nov 2026, Ariel)."""

import pytest
import requests

from outreach import hubspot_client, instantly_client
from outreach.hubspot_client import HubSpot, HubSpotError
from outreach.instantly_client import Instantly, InstantlyError


class Resp:
    status_code, content, headers, text = 200, b'{"ok": true}', {}, ""

    def json(self):
        return {"ok": True}


class FlakySession:
    """Fails `fails` times (a timeout or a dropped connection), then answers."""

    def __init__(self, fails, error=requests.exceptions.ReadTimeout):
        self.fails, self.error, self.calls, self.headers = fails, error, 0, {}

    def request(self, *a, **k):
        self.calls += 1
        if self.calls <= self.fails:
            raise self.error("no answer")
        return Resp()


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(hubspot_client.time, "sleep", lambda *_: None)
    monkeypatch.setattr(instantly_client.time, "sleep", lambda *_: None)


def test_hubspot_asks_again_up_to_3_times():
    s = FlakySession(3)
    assert HubSpot(token="t", session=s).request("POST", "/crm/v3/objects/contacts/batch/update", json={}) == {"ok": True}
    assert s.calls == 4
    with pytest.raises(HubSpotError, match="did not answer"):
        HubSpot(token="t", session=FlakySession(4)).request("GET", "/crm/v3/objects/contacts")


def test_hubspot_never_repeats_creating_a_record_or_a_note():
    s = FlakySession(1)
    with pytest.raises(HubSpotError):
        HubSpot(token="t", session=s).request("POST", "/crm/v3/objects/contacts/batch/create", json={})
    assert s.calls == 1
    with pytest.raises(HubSpotError):
        HubSpot(token="t", session=FlakySession(1)).request("POST", "/crm/v3/objects/notes", json={})


def test_instantly_asks_again_when_the_connection_drops():
    s = FlakySession(2, requests.exceptions.ConnectionError)
    assert Instantly(api_key="k", session=s).request("POST", "/leads/list", json={}) == {"ok": True}
    assert s.calls == 3


def test_instantly_never_repeats_an_email_or_a_new_campaign():
    for path in ("/emails/forward", "/emails/reply", "/campaigns"):
        s = FlakySession(1)
        with pytest.raises(InstantlyError, match="did not answer"):
            Instantly(api_key="k", session=s).request("POST", path, json={})
        assert s.calls == 1
