"""The strain test helper (19 Oct 2026): test addresses for the test account only."""

import pytest

from outreach import test_addresses as ta
from outreach.common import PipelineError, PRODUCTION_PORTAL_ID

from .fakes import FakeCRM

MAILBOXES = "c1=one@x.example, c2=two@y.example, c3=three@x.example, c4=four@y.example, " \
            "c5=five@y.example, c6=six@y.example, c7=seven@x.example"
# From 19 Oct 2026: five cases with the round letter e (the last one the one-contact case).
FIVE = "e1=two@y.example, e2=three@x.example, e3=five@y.example, e4=six@y.example, e5=four@y.example"


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
    assert {"two+c2p1@y.example", "two+c2p2@y.example", "two+c2p3@y.example", "seven+c7p1@x.example"} <= emails
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
    with pytest.raises(PipelineError, match="No mailbox given"):
        ta.parse_mailboxes("")
    with pytest.raises(PipelineError, match='no "\\+" part'):
        ta.parse_mailboxes(MAILBOXES.replace("one@", "one+x@"))
    live = FakeCRM(portal=PRODUCTION_PORTAL_ID)
    with pytest.raises(PipelineError):
        ta.run("test", live, ta.parse_mailboxes(MAILBOXES), log=quiet)  # a live key is refused too


def test_dry_run_changes_nothing():
    hs, ids = crm([3, 3, 3, 3, 3, 3, 1])
    ta.run("test", hs, ta.parse_mailboxes(MAILBOXES), dry_run=True, log=quiet)
    assert all(p["email"].startswith("real") for p in hs.records["contacts"].values())


def test_five_cases_with_the_round_letter():
    """19 Oct 2026: c2 and c4 retired; the next round is e1 to e5 (e5 the one-contact case). A new
    letter keeps the addresses apart from Instantly's emails of an earlier round."""
    hs, ids = crm([3, 3, 3, 3, 1, 3])
    mailboxes = ta.parse_mailboxes(FIVE)
    assert list(mailboxes) == ["e1", "e2", "e3", "e4", "e5"]
    out = ta.run("test", hs, mailboxes, log=quiet)
    assert set(out["cases"]) == {"e1", "e2", "e3", "e4", "e5"}
    emails = {p["email"] for p in hs.records["contacts"].values()}
    assert {"two+e1p1@y.example", "two+e1p3@y.example", "six+e4p2@y.example", "four+e5p1@y.example"} <= emails
    assert "four+e5p2@y.example" not in emails  # the last case has one contact
    assert out["unused"] == ["Company F"]
    with pytest.raises(PipelineError, match="Name exactly 5 companies"):
        ta.run("test", crm([3, 3, 3, 3, 1])[0], mailboxes, ["Company A"], log=quiet)
    with pytest.raises(PipelineError, match="one letter for every case"):
        ta.parse_mailboxes("e1=a@x.example, f2=b@x.example")
    with pytest.raises(PipelineError, match="not a case"):
        ta.parse_mailboxes("e10=a@x.example")
