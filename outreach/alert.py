"""Emails when something goes wrong, to the daily summary's recipients (agreed 1 Nov 2026, Ariel).

Sent from admin@diablosnosugar.com through Google, like the daily summary: the recipients are the GitHub
secret DAILY_REPORT_TO and the mailbox's app password DAILY_REPORT_APP_PASSWORD.

    python -m outreach.alert --run-failed      a button's run did not finish: which button, which steps
                                               failed, which had already done their work, and the link
    python -m outreach.alert --held-back       a code change failed the automatic checks; the buttons keep
                                               using the last checked version
    python -m outreach.alert --early-warning   the 25th's rehearsal: the code would fail on the 1st of
                                               next month (or around it); nothing has failed yet

Never stops anything: when the email cannot be sent, the reason is printed and the run carries on.
"""

import argparse
import datetime as dt
import html as html_lib
import json
import os
import sys
import urllib.request

INDIA = dt.timezone(dt.timedelta(hours=5, minutes=30))
SIGN_OFF = "Kind regards,\nDiablo Partner Outreach"


def _today():
    d = dt.datetime.now(dt.timezone.utc).astimezone(INDIA)
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B %Y')}"


def run_link():
    server, repo, run = (os.environ.get(k, "") for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run}" if server and repo and run else ""


def _steps():
    """[(step name, conclusion)] of this run's job, from GitHub, or [] when they cannot be read."""
    repo, run, token = (os.environ.get(k, "") for k in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_TOKEN"))
    if not (repo and run and token):
        return []
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/actions/runs/{run}/jobs",
                                     headers={"Authorization": f"Bearer {token}",
                                              "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            jobs = json.load(resp).get("jobs") or []
    except Exception:
        return []
    return [(s.get("name") or "", s.get("conclusion") or s.get("status") or "")
            for j in jobs for s in j.get("steps") or []]


# Housekeeping steps, never worth naming in the email.
_QUIET = ("Set up job", "Complete job", "Post ", "Run actions/", "uses:", "Run pip install", "pip install",
          "actions/checkout", "actions/setup-python", "actions/upload-artifact", "After: email")


def _named(steps):
    return [(n, c) for n, c in steps if n and not n.startswith(_QUIET)]


def run_failed_text(button, steps, failed_env="", link=""):
    """(subject, text) of the email for a run that did not finish."""
    steps = _named(steps)
    # "After: did every step work?" only repeats the steps above it; their names come from FAILED_STEPS.
    failed = [n for n, c in steps if c == "failure" and not n.startswith("After: did every step")]
    done = [n for n, c in steps if c == "success" and not n.startswith("After: did every step")]
    lines = ["Hello,", "",
             f'The GitHub button "{button}" did not finish its run on {_today()}.', ""]
    if failed:
        lines += ["What failed:"] + [f"- {n}" for n in failed] + [""]
    elif failed_env.strip():
        lines += ["What failed:"] + [f"- step {x.strip()}" for x in failed_env.split(";") if x.strip()] + [""]
    else:
        lines += ["GitHub did not say which step failed; the link below shows it.", ""]
    if any(n.startswith("Before") for n in failed):
        lines += ["It stopped before doing anything: nothing was sent or changed by this run.", ""]
    elif done:
        lines += ["These steps had already finished and did their work:"] + [f"- {n}" for n in done] + [""]
    lines += ["Nothing needs doing if the next scheduled run works; if it fails again, please look into it."]
    if link:
        lines += ["", f"The run, with the full reason: {link}"]
    lines += ["", SIGN_OFF]
    return f"Partner outreach: {button} did not finish ({_today()})", "\n".join(lines)


def held_back_text(link=""):
    lines = ["Hello,", "",
             "A change to the outreach code did not pass the automatic checks, so it has been held back. "
             "The buttons keep running on the last version that passed; nothing has stopped.", "",
             "The change needs fixing before it is used."]
    if link:
        lines += ["", f"The checks, with the reason: {link}"]
    lines += ["", SIGN_OFF]
    return f"Partner outreach: a code change was held back ({_today()})", "\n".join(lines)


def early_warning_text(days="", link=""):
    lines = ["Hello,", "",
             "This is the monthly early warning. Tested as if it were the start of next month, the outreach code "
             "would fail"
             + (f" on: {days.strip()}" if days.strip() else "") + ".",
             "", "Nothing has failed yet and everything runs as normal today. It needs fixing before the 1st.", ""]
    if link:
        lines += [f"The rehearsal, with the reason: {link}", ""]
    lines += [SIGN_OFF]
    return f"Partner outreach: early warning for next month ({_today()})", "\n".join(lines)


def send(subject, text, log=print, smtp=None):
    """Send to DAILY_REPORT_TO. Returns True when sent."""
    from .daily_report import DEFAULTS, recipients, send_mail
    to = recipients()
    password = os.environ.get("DAILY_REPORT_APP_PASSWORD", "")
    if not to or not password:
        log("Not emailed: the GitHub secrets DAILY_REPORT_TO and DAILY_REPORT_APP_PASSWORD are needed")
        return False
    body = "".join(f"<div>{html_lib.escape(line) or '<br>'}</div>" for line in text.split("\n"))
    try:
        send_mail(subject, text, body, dict(DEFAULTS), to, password, smtp)
    except Exception as err:
        log(f"Not emailed: {str(err)[:200]}")
        return False
    log(f"Emailed to {len(to)} recipient(s): {subject}")
    return True


def main(argv=None):
    p = argparse.ArgumentParser(description="Email the daily summary's recipients when something goes wrong")
    kind = p.add_mutually_exclusive_group(required=True)
    kind.add_argument("--run-failed", action="store_true")
    kind.add_argument("--held-back", action="store_true")
    kind.add_argument("--early-warning", action="store_true")
    args = p.parse_args(argv)
    link = run_link()
    if args.run_failed:
        subject, text = run_failed_text(os.environ.get("GITHUB_WORKFLOW", "a button"), _steps(),
                                        os.environ.get("FAILED_STEPS", ""), link)
    elif args.held_back:
        subject, text = held_back_text(link)
    else:
        subject, text = early_warning_text(os.environ.get("DATE_CHECKS_FAILED", ""), link)
    print(text)
    send(subject, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
