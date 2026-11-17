"""Bounce check, read only (17 Nov 2026, Ariel): finds where Instantly keeps each bounce notice and what it
says, changes nothing, and never shows a prospect's address."""

import copy

from outreach import bounce_check
from outreach.common import load_settings

from .fakes import FakeCRM, FakeInstantly

SENT = "2026-11-17T08:20:25.165Z"


class FakeEmailList:
    """Instantly's /emails list: notices live in the "others" tab and are not linked to the lead."""

    def __init__(self, emails, refuse=()):
        self.emails, self.refuse, self.asked, self.writes = emails, set(refuse), [], 0

    def request(self, method, path, params=None, **_):
        if method != "GET":
            self.writes += 1
        self.asked.append(dict(params or {}))
        if any(k in self.refuse for k in params or {}):
            raise RuntimeError("400 Bad Request: unknown parameter")
        out = []
        for e in self.emails:
            if e.get("tab") == "others" and params.get("mode") != "emode_all":
                continue
            if "lead" in params and e.get("lead") != params["lead"]:
                continue
            if "search" in params and params["search"] not in (e.get("text") or "") + (e.get("lead") or ""):
                continue
            if "eaccount" in params and e.get("eaccount") != params["eaccount"]:
                continue
            out.append({k: v for k, v in e.items() if k != "text"} | {"content_preview": e.get("text")})
        return {"items": out}

    def get_email(self, email_id):
        return next(({"body": {"text": e["text"]}} for e in self.emails if e["id"] == email_id), None)


def notice(i, about, text, tab="others", lead=None, account="dana@meetdiablo.com"):
    return {"id": f"n{i}", "ue_type": 2, "from_address_email": "mailer-daemon@googlemail.com",
            "subject": "Delivery Status Notification (Failure)", "tab": tab, "lead": lead, "eaccount": account,
            "text": f"Your message to {about} was not delivered. {text}"}


def setup(emails):
    hs, inst = FakeCRM(), FakeInstantly()
    inst.campaigns["c1"] = {"name": "Diablo | NOV2026 | Company inboxes"}
    leads = []
    for n, (addr, esp) in enumerate(emails):
        leads.append({"id": f"l{n}", "email": addr, "status": -1, "esp_code": esp,
                      "status_summary": {"lastStep": {"from": "dana@meetdiablo.com", "timestamp_executed": SENT}}})
        hs.add("contacts", email=addr, jobtitle="Company inbox (from website)")
    leads.append({"id": "ok", "email": "fine@ok.example", "status": 1})
    inst.leads["c1"] = leads
    return hs, inst


def test_finds_notices_sorts_them_and_hides_addresses():
    hs, inst = setup([("info@dead.example", 1), ("info@full.example", 999), ("info@gone.example", 1000),
                      ("info@broken.example", 999)])
    before = copy.deepcopy((hs.records, inst.leads))
    api = FakeEmailList([
        notice(1, "info@dead.example", "550 5.1.1 The email account info@dead.example does not exist."),
        notice(2, "info@full.example", "552 5.2.2 The recipient's inbox is full.", tab="focused",
               lead="info@full.example"),
        notice(3, "info@broken.example", "DNS Error: DNS type 'mx' lookup of broken.example responded with "
                                         "code SERVFAIL"),
    ])
    log = []
    out = bounce_check.run(hs, inst, api, load_settings(), log=log.append, sleep=lambda _: None)
    kinds = {r["contact"]: r["kind"] for r in out["rows"]}
    ids = {p["email"]: rid for rid, p in hs.records["contacts"].items()}
    assert kinds[ids["info@dead.example"]] == "Address does not exist"
    assert kinds[ids["info@full.example"]] == "Inbox full"
    assert kinds[ids["info@broken.example"]] == "Domain cannot receive email"
    assert kinds[ids["info@gone.example"]] == "Domain cannot receive email"  # no notice, but no mail system
    # The notice in the "others" tab is missed the way button 4 asks today (A), found in every tab (B, C).
    rows = {r["contact"]: r for r in out["rows"]}
    assert rows[ids["info@dead.example"]]["found"] == "C, D"
    assert rows[ids["info@full.example"]]["found"].startswith("A, B, C")
    # Nothing is changed, and no prospect's address is shown.
    assert api.writes == 0 and (hs.records, inst.leads) == before
    text = "\n".join(log)
    assert "dead.example" not in text.replace("@dead", "") and "info@" not in text
    assert "<address>" in text and "dana@meetdiablo.com" in text


def test_a_way_instantly_refuses_is_reported_not_fatal():
    hs, inst = setup([("info@dead.example", 1)])
    api = FakeEmailList([notice(1, "info@dead.example", "550 5.1.1 does not exist")], refuse={"eaccount"})
    out = bounce_check.run(hs, inst, api, load_settings(), log=lambda _: None, sleep=lambda _: None)
    row = out["rows"][0]
    assert row["found"] == "C" and "D: 400 Bad Request" in row["refused"]
    assert row["kind"] == "Address does not exist"


def test_reads_slowly():
    waits = []
    reader = bounce_check.Reader(FakeEmailList([]), sleep=waits.append)
    for _ in range(3):
        reader.emails({"lead": "x@y.example"})
    assert waits == [bounce_check.PAUSE] * 2
