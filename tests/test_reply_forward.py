"""Real replies forwarded to Ariel once, tagged Positive, Negative or Neutral (Ariel, 27 Oct 2026)."""

from outreach import reply_forward
from outreach.common import load_settings

from .fakes import FakeCRM, FakeEmails
from .test_daily_report import FakeSMTP


def quiet(_):
    pass


def _setup(monkeypatch):
    monkeypatch.setenv("REPLY_FORWARD_TO", "owner@team.example")
    monkeypatch.setenv("DAILY_REPORT_APP_PASSWORD", "app-password")
    hs, emails = FakeCRM(), FakeEmails()
    cid = hs.add("companies", name="FELFEL", country="Switzerland")
    pid = hs.add("contacts", email="alina@felfel.example", jobtitle="Senior Product Owner")
    hs.links[pid] = [cid]
    emails.campaign_email("alina@felfel.example", "2026-10-24T08:00:00Z", subject="A sugar-free brand with no Swiss partner yet")
    return hs, emails, pid


def _record(hs, pid):
    return {"id": pid, "properties": dict(hs.records["contacts"][pid])}


def test_a_positive_reply_is_forwarded_once_with_the_agreed_header(monkeypatch):
    hs, emails, pid = _setup(monkeypatch)
    emails.received("alina@felfel.example", "2026-10-26T09:00:00Z", subject="Re: A sugar-free brand with no Swiss partner yet",
                    text="Thank you, please send prices.")
    smtp = FakeSMTP()
    seen = [(_record(hs, pid), {}, "marked interested")]
    assert reply_forward.forward_replies(hs, emails, seen, load_settings(), quiet, smtp=smtp) == 1
    msg = smtp.sent[0]
    assert msg["Subject"] == "[Outreach reply: Positive] Re: A sugar-free brand with no Swiss partner yet (FELFEL)"
    assert msg["From"] == "Diablo Partner Outreach <admin@diablosnosugar.com>" and msg["To"] == "owner@team.example"
    text = msg.get_body(("plain",)).get_content()
    assert text.startswith("Company: FELFEL (Switzerland)\nContact: Senior Product Owner, alina@felfel.example\n"
                           "Their reply: positive, received Monday 26 October 2026\n")
    assert "Thank you, please send prices." in text
    assert text.index("please send prices") < text.index("Subject: A sugar-free brand with no Swiss partner yet")
    assert "Reply to the client" not in text
    assert reply_forward.forward_replies(hs, emails, seen, load_settings(), quiet, smtp=smtp) == 0  # once only
    assert emails.forwards == []  # never through Instantly, so the client's thread is untouched


def test_neutral_then_marked_goes_again_once_and_automatic_answers_never_go(monkeypatch):
    hs, emails, pid = _setup(monkeypatch)
    smtp = FakeSMTP()
    emails.received("alina@felfel.example", "2026-10-25T09:00:00Z", subject="Out of office", text="I am out of office until 3 November.")
    assert reply_forward.forward_replies(hs, emails, [(_record(hs, pid), {}, "replied")], load_settings(), quiet,
                                         smtp=smtp) == 0  # only an automatic answer so far: nothing goes
    emails.received("alina@felfel.example", "2026-10-26T09:00:00Z", subject="Re: hello", text="Interesting, tell me more.")
    assert reply_forward.forward_replies(hs, emails, [(_record(hs, pid), {}, "replied")], load_settings(), quiet,
                                         smtp=smtp) == 1
    assert smtp.sent[-1]["Subject"].startswith("[Outreach reply: Neutral] Re: hello")
    assert reply_forward.forward_replies(hs, emails, [(_record(hs, pid), {}, "marked not interested")],
                                         load_settings(), quiet, smtp=smtp) == 1
    assert smtp.sent[-1]["Subject"].startswith("[Outreach reply: Negative]")
    for event in ("marked not interested", "replied", "out of office", "unsubscribed"):
        assert reply_forward.forward_replies(hs, emails, [(_record(hs, pid), {}, event)], load_settings(), quiet,
                                             smtp=smtp) == 0
    assert len(smtp.sent) == 2


def test_nothing_goes_without_the_secrets(monkeypatch):
    hs, emails, pid = _setup(monkeypatch)
    monkeypatch.delenv("REPLY_FORWARD_TO")
    emails.received("alina@felfel.example", "2026-10-26T09:00:00Z", text="Yes please.")
    said = []
    assert reply_forward.forward_replies(hs, emails, [(_record(hs, pid), {}, "marked interested")], load_settings(),
                                         said.append, smtp=FakeSMTP()) == 0
    assert "REPLY_FORWARD_TO" in said[0]
