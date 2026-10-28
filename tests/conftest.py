import pytest


@pytest.fixture(autouse=True)
def no_real_timeline_notes(tmp_path, monkeypatch):
    """No test reads or writes the real list of timeline notes already written."""
    from outreach import timeline
    monkeypatch.setattr(timeline, "NOTES_FILE", tmp_path / "timeline_notes.json")


@pytest.fixture(autouse=True)
def no_real_run_summary(monkeypatch):
    """Tests never write to the GitHub run's summary page (23 Oct 2026, Ariel: the made-up companies of the
    tests, such as Beta Foods and Noble Foods, showed up on every button's summary). A test that checks
    the summary sets its own file."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


@pytest.fixture(autouse=True)
def no_real_websites(monkeypatch):
    """No test ever visits a real website for a company's contact address (company_inbox.py);
    tests that need one replace find_inbox themselves."""
    from outreach import company_inbox
    monkeypatch.setattr(company_inbox, "find_inbox", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def no_real_company_lists(tmp_path, monkeypatch):
    """No test reads or writes the real "already in HubSpot" lists or the account marker."""
    from outreach import common, known_companies
    monkeypatch.setattr(common, "KNOWN_FILE", tmp_path / "known_companies.csv")
    monkeypatch.setattr(common, "KNOWN_FILE_TEST", tmp_path / "known_companies_test.csv")
    monkeypatch.setattr(common, "TARGET_FILE", tmp_path / "pipeline_target.txt")
    monkeypatch.setattr(known_companies, "KNOWN_FILE", tmp_path / "known_companies.csv")


@pytest.fixture(autouse=True)
def no_real_apollo_lists(tmp_path, monkeypatch):
    """No test reads or writes the real lists of people already revealed in Apollo."""
    from outreach import find_contacts
    monkeypatch.setattr(find_contacts, "SKIPPED_FILE", tmp_path / "apollo_skipped.json")
    monkeypatch.setattr(find_contacts, "KEPT_FILE", tmp_path / "apollo_kept.json")
    monkeypatch.setattr(find_contacts, "TOPPED_FILE", tmp_path / "topped_up.json")


@pytest.fixture(autouse=True)
def no_real_keys_or_reports(tmp_path, monkeypatch):
    """No test uses a real Instantly blocklist key or writes the real last-run report."""
    from outreach import sync
    monkeypatch.delenv("INSTANTLY_BLOCKLIST_KEY", raising=False)
    monkeypatch.setattr(sync, "LAST_RUN", tmp_path / "sync_last_run.md")


@pytest.fixture(autouse=True)
def no_real_job_counter(tmp_path, monkeypatch):
    """No test reads or writes the real research/last_job_id.txt."""
    from outreach import research_queue
    monkeypatch.setattr(research_queue, "LAST_ID_FILE", tmp_path / "last_job_id.txt")


@pytest.fixture(autouse=True)
def no_real_daily_log(tmp_path, monkeypatch):
    """No test reads or writes the real daily log of the summary email (27 Oct 2026)."""
    from outreach import daily_log
    monkeypatch.setattr(daily_log, "LOG_FILE", tmp_path / "daily_log.json")
    monkeypatch.delenv("DAILY_REPORT_TO", raising=False)
    monkeypatch.delenv("DAILY_REPORT_APP_PASSWORD", raising=False)
    monkeypatch.delenv("REPLY_FORWARD_TO", raising=False)
    from outreach import reply_forward
    monkeypatch.setattr(reply_forward, "FILE", tmp_path / "forwarded_replies.json")


@pytest.fixture(autouse=True)
def no_real_promoted_list(tmp_path, monkeypatch):
    """No test reads or writes the real list of contacts moved up after a dead address (28 Oct 2026)."""
    from outreach import corrupt
    monkeypatch.setattr(corrupt, "PROMOTED_FILE", tmp_path / "promoted.json")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
