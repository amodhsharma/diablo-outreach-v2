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
