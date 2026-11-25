import os

import pytest

# 1 Nov 2026 (Ariel): no date may ever stop the buttons again. With CHECK_DATE set (for example
# CHECK_DATE=2027-01-01T00:30:00+05:30), every check runs as if that were the time now; the clock keeps
# ticking from there. .github/scripts/date_checks.sh runs all the checks this way on the difficult days
# (month ends, the new year, 29 February) whenever the code changes, and on the 25th of each month.
_PRETEND = None


def pytest_configure(config):
    global _PRETEND
    config.addinivalue_line("markers", "channels: run the real channel check (20 Nov 2026)")
    config.addinivalue_line("markers", "address_checks: run the real free address checks (20 Nov 2026)")
    when = os.environ.get("CHECK_DATE", "").strip()
    if when:
        from freezegun import freeze_time
        _PRETEND = freeze_time(when, tick=True)
        _PRETEND.start()


def pytest_unconfigure(config):
    if _PRETEND is not None:
        _PRETEND.stop()


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
    monkeypatch.setattr(corrupt, "TEMPORARY_FILE", tmp_path / "temporary_bounces.json")  # 16 Nov 2026
    from outreach import campaign_guard
    monkeypatch.setattr(campaign_guard, "FILE", tmp_path / "campaign_guard.json")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)


@pytest.fixture(autouse=True)
def no_real_website_recheck_list(tmp_path, monkeypatch):
    """No test reads or writes the real list of Missing Info websites read again (1 Nov 2026)."""
    from outreach import apollo_status
    monkeypatch.setattr(apollo_status, "_rechecked_file", lambda: tmp_path / "website_rechecked.json")


@pytest.fixture(autouse=True)
def no_real_chain_state(tmp_path, monkeypatch):
    """No test reads or writes the real list of reopened companies and the day's counts (2 Nov 2026)."""
    from outreach import chain
    monkeypatch.setattr(chain, "STATE_FILE", tmp_path / "chain_state.json")


@pytest.fixture(autouse=True)
def no_real_referrals_list(tmp_path, monkeypatch):
    """No test reads or writes the real list of replies that named someone else (3 Nov 2026)."""
    from outreach import referrals
    monkeypatch.setattr(referrals, "FILE", tmp_path / "referrals.json")


@pytest.fixture(autouse=True)
def no_real_blocklist(monkeypatch):
    """No test reads Instantly's real blocklist when button 3 takes over existing contacts (10 Nov 2026).
    Unread, nobody is taken over; tests of the take-over give their own list."""
    from outreach import takeover
    from outreach.sync import BlockList
    monkeypatch.setattr(takeover, "read_blocked", lambda log=print: BlockList(ok=False, problem="not read in tests"))


@pytest.fixture(autouse=True)
def no_real_mail_watch(tmp_path, monkeypatch):
    """No test reads or writes the real record of which email threads button 4 read (10 Nov 2026)."""
    from outreach import mail_watch
    monkeypatch.setattr(mail_watch, "FILE", tmp_path / "mail_watch.json")


@pytest.fixture(autouse=True)
def no_real_send_memory(tmp_path, monkeypatch):
    """No test reads or writes button 4's real memory (17 Nov 2026)."""
    from outreach import send_memory
    monkeypatch.setattr(send_memory, "FILE", tmp_path / "send_memory.json")


@pytest.fixture(autouse=True)
def no_real_restarts_file(tmp_path, monkeypatch):
    """No test reads or writes the real list of restarted companies (19 Nov 2026)."""
    from outreach import restart
    monkeypatch.setattr(restart, "FILE", tmp_path / "restarts.json")


@pytest.fixture(autouse=True)
def restarts_off_unless_a_test_says_so(monkeypatch):
    """Tests run with restarts switched off, whatever config/settings.yaml says (19 Nov 2026).

    A test that wants restarts on builds its own settings with restart.enabled set to true and passes them in,
    as tests/test_restart.py does. This keeps every other test checking the usual flow."""
    import importlib
    import pkgutil
    import sys
    import outreach
    from outreach import common

    real = common.load_settings

    def load_settings(path=None):
        s = real(path)
        if isinstance(s, dict) and isinstance(s.get("restart"), dict):
            s["restart"] = dict(s["restart"], enabled=False)
        return s

    for info in pkgutil.iter_modules(outreach.__path__):
        importlib.import_module(f"outreach.{info.name}")
    for mod in list(sys.modules.values()):
        if getattr(mod, "load_settings", None) is real:
            monkeypatch.setattr(mod, "load_settings", load_settings)


@pytest.fixture(autouse=True)
def every_channel_goes_ahead_unless_a_test_says_so(tmp_path, monkeypatch, request):
    """20 Nov 2026 (Ariel, HARD RULE): the channel is the first filter for every company. Most tests' made-up
    companies have no channel, so the check lets them through; a test marked @pytest.mark.channels runs the real
    check. No test reads the real config/company_channels.json."""
    from outreach import channels, common
    monkeypatch.setattr(common, "CHANNELS_FILE", tmp_path / "company_channels.json")
    monkeypatch.setattr(common, "_CHANNELS", {})
    if request.node.get_closest_marker("channels") is None:
        monkeypatch.setattr(channels, "verdict", lambda props, notes=None: True)


@pytest.fixture(autouse=True)
def no_real_address_checks(tmp_path, monkeypatch, request):
    """20 Nov 2026: no test asks real DNS whether a domain takes email, or reads or writes the real counters of
    data/address_checks.json; the made-up domains of the tests take email unless a test says otherwise. Old and
    hand-added addresses are not held back to 20 a day unless the test has @pytest.mark.address_checks."""
    from outreach import address_checks
    monkeypatch.setattr(address_checks, "FILE", tmp_path / "address_checks.json")
    address_checks._MAIL.clear()
    if "address_checks" not in request.keywords:
        monkeypatch.setattr(address_checks, "domain_ok", lambda email, check=None: True)
        real = address_checks.settings_of
        monkeypatch.setattr(address_checks, "settings_of", lambda settings: dict(real(settings), risky_per_day=10 ** 6))


@pytest.fixture(autouse=True)
def no_real_old_record_checks(tmp_path, monkeypatch):
    """25 Nov 2026: no test reads or writes the real record of old records checked with Apollo."""
    from outreach import old_records
    monkeypatch.setattr(old_records, "FILE", tmp_path / "old_record_checks.json")
