"""1 Nov 2026 (Ariel): an email to DAILY_REPORT_TO when a button fails, when a code change is held back
and on the 25th when next month would fail."""

from outreach import alert


class FakeSMTP:
    def __init__(self):
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        self.sent.append(msg)


def test_a_failed_run_names_the_failed_step_and_what_had_finished():
    steps = [("Set up job", "success"), ("Run actions/checkout@v5", "success"),
             ("Before: use only checked code", "success"),
             ("1. Instantly results to HubSpot", "success"), ("2. Send person 1's introduction", "failure"),
             ("After: did every step work?", "failure"), ("After: email if this run failed", "in_progress")]
    subject, text = alert.run_failed_text("4 - Send and follow up", steps, link="https://github.com/x/runs/1")
    assert subject.startswith("Partner outreach: 4 - Send and follow up did not finish")
    assert "- 2. Send person 1's introduction" in text
    assert "already finished and did their work:\n- Before: use only checked code\n- 1. Instantly results" in text
    assert "https://github.com/x/runs/1" in text and "checkout" not in text


def test_a_run_that_stopped_before_doing_anything_says_nothing_was_sent():
    _, text = alert.run_failed_text("3 - Find contacts", [("Before: use only checked code", "failure")])
    assert "nothing was sent or changed" in text


def test_the_emails_go_only_to_alert_to_never_the_daily_summary_list(monkeypatch):
    monkeypatch.setenv("ALERT_TO", "one@team.example, two@team.example")
    monkeypatch.setenv("DAILY_REPORT_TO", "everyone@team.example")
    monkeypatch.setenv("DAILY_REPORT_APP_PASSWORD", "secret")
    smtp = FakeSMTP()
    subject, text = alert.held_back_text()
    assert alert.send(subject, text, log=lambda *_: None, smtp=smtp)
    assert smtp.sent[0]["To"] == "one@team.example, two@team.example"
    assert "held back" in smtp.sent[0]["Subject"]
    _, warning = alert.early_warning_text(" 2026-12-01T00:20:00+05:30")
    assert "would fail on: 2026-12-01T00:20:00+05:30" in warning


def test_no_secrets_no_email_and_no_error(monkeypatch):
    monkeypatch.delenv("ALERT_TO", raising=False)
    said = []
    assert alert.send("s", "t", log=said.append) is False and "ALERT_TO" in said[0]


def test_a_step_that_failed_but_let_the_run_go_on_is_named_from_the_run():
    steps = [("Before: use only checked code", "success"), ("1. Find people at GATE1 companies (Apollo)", "success"),
             ("After: did every step work?", "failure")]
    _, text = alert.run_failed_text("3 - Find contacts", steps, failed_env=" 1 (find people);")
    assert "What failed:\n- step 1 (find people)" in text
