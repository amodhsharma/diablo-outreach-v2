import pytest


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


@pytest.fixture(autouse=True)
def no_real_keys_or_reports(tmp_path, monkeypatch):
    """No test uses a real Instantly blocklist key or writes the real last-run report."""
    from outreach import sync
    monkeypatch.delenv("INSTANTLY_BLOCKLIST_KEY", raising=False)
    monkeypatch.setattr(sync, "LAST_RUN", tmp_path / "sync_last_run.md")
