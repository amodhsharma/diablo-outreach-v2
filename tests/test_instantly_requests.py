"""Instantly refuses a request marked as JSON with no body (26 Oct 2026: the "Other channels"
campaigns could not be deleted)."""

import requests

from outreach.instantly_client import Instantly


class Answer:
    status_code, content, headers = 200, b"{}", {}

    def json(self):
        return {}


def test_a_delete_is_sent_without_the_json_mark_and_a_post_keeps_it():
    sent = []
    session = requests.Session()
    session.send = lambda prepared, **kw: sent.append(prepared) or Answer()
    client = Instantly(api_key="test", session=session)
    client.delete_lead("L1")
    client.delete_campaign("C1")
    client.request("POST", "/leads/list", json={"limit": 1})
    assert "Content-Type" not in sent[0].headers and "Content-Type" not in sent[1].headers
    assert sent[2].headers["Content-Type"] == "application/json"
    assert sent[0].headers["Authorization"] == "Bearer test"


def test_a_restart_campaign_sends_every_skip_flag_off():
    """20 Nov 2026: Instantly's skip_if_in_campaign skips a lead in ANY campaign, so a restart turns it off."""
    import json
    sent = []
    session = requests.Session()
    session.send = lambda prepared, **kw: sent.append(prepared) or Answer()
    client = Instantly(api_key="test", session=session)
    client.add_leads("C1", [{"email": "a@x.example"}])
    client.add_leads("C2", [{"email": "a@x.example"}], only_this_campaign=True)
    usual, restart = (json.loads(p.body) for p in sent)
    assert usual["skip_if_in_workspace"] is True
    assert restart["skip_if_in_workspace"] is False and restart["skip_if_in_campaign"] is False
    assert restart["skip_if_in_list"] is False
