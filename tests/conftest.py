import pytest


@pytest.fixture(autouse=True)
def no_real_websites(monkeypatch):
    """No test ever visits a real website for a company's contact address (company_inbox.py);
    tests that need one replace find_inbox themselves."""
    from outreach import company_inbox
    monkeypatch.setattr(company_inbox, "find_inbox", lambda *a, **k: None)
