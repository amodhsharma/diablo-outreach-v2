"""The strain test helper (19 Oct 2026): test addresses for the test account only."""

import pytest

from outreach import test_addresses as ta
from outreach.common import PipelineError, PRODUCTION_PORTAL_ID

from .fakes import FakeCRM

MAILBOXES = "c1=rafi@x.example, c2=amodhextra@gmail.com, c3=amodh@x.example, c4=a.r@gmail.com, " \
            "c5=clg@gmail.com, c6=a1014@gmail.com, c7=ariel@x.example"


def quiet(_):
    pass


def crm(sizes):
    hs = FakeCRM()
    ids = {}
    for i, n in enumerate(sizes):
        cid = hs.add("companies", name=f"Company {chr(65 + i)}", domain=f"c{i}.example",
                     hs_lead_status="GATE1: Approved for outreach")
        people = []
        for k in range(n):
            pid = hs.add("contacts", email=f"real{k}@c{i}.example", jobtitle=f"T{k}", diablo_outreach_order=str(k + 1),
                         hs_lead_status="NEW")
            hs.links[pid] = [cid]
            people.append(pid)
        ids[cid] = people
    return hs, ids


def test_cases_get_plus_addresses_and_extra_contacts_are_closed():
    hs, ids = crm([4, 3, 3, 3, 3, 3, 1, 2])
    out = ta.run("test", hs, ta.parse_mailboxes(MAILBOXES), log=quiet)
    emails = {p["email"] for p in hs.records["contacts"].values()}
    assert {"amodhextra+c2p1@gmail.com", "amodhextra+c2p2@gmail.com", "amodhextra+c2p3@gmail.com",
            "ariel+c7p1@x.example"} <= emails
    first = next(cid for cid in ids if len(ids[cid]) == 4)
    assert hs.records["contacts"][ids[first][3]]["hs_lead_status"] == "UNQUALIFIED"  # the 4th person
    assert out["unused"] == ["Company H"]  # an approved company not used: listed, untouched
    assert all(p["email"].startswith("real") for pid in ids[[*ids][-1]] for p in [hs.records["contacts"][pid]])


def test_named_companies_and_refusals():
    hs, ids = crm([3, 3, 3, 3, 3, 3, 1])
    names = ["Company G", "Company A", "Company B", "Company C", "Company D", "Company E", "Company F"]
    with pytest.raises(PipelineError, match="fewer than 3"):
        ta.run("test", hs, ta.parse_mailboxes(MAILBOXES), names, log=quiet)  # G has only 1 contact for c1
    with pytest.raises(PipelineError, match="test account only"):
        ta.run("live", hs, ta.parse_mailboxes(MAILBOXES), log=quiet)
    with pytest.raises(PipelineError, match="No mailbox given for c7"):
        ta.parse_mailboxes(MAILBOXES.rsplit(",", 1)[0])
    with pytest.raises(PipelineError, match='no "\\+" part'):
        ta.parse_mailboxes(MAILBOXES.replace("rafi@", "rafi+x@"))
    live = FakeCRM(portal=PRODUCTION_PORTAL_ID)
    with pytest.raises(PipelineError):
        ta.run("test", live, ta.parse_mailboxes(MAILBOXES), log=quiet)  # a live key is refused too


def test_dry_run_changes_nothing():
    hs, ids = crm([3, 3, 3, 3, 3, 3, 1])
    ta.run("test", hs, ta.parse_mailboxes(MAILBOXES), dry_run=True, log=quiet)
    assert all(p["email"].startswith("real") for p in hs.records["contacts"].values())
