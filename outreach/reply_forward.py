"""Every real reply forwarded to Ariel, tagged Positive, Negative or Neutral (agreed 27 Oct 2026).

At each run of button 4, Sync sorts every answer in Instantly (see sync.run). Each real reply, never
an automatic one, is forwarded once to the address in the GitHub secret REPLY_FORWARD_TO, from
admin@diablosnosugar.com through Google (the mailbox of the daily summary; its app password is the
secret DAILY_REPORT_APP_PASSWORD). Sending it this way keeps it out of the client's own thread in
Instantly. The subject starts with "[Outreach reply: Positive]", "[Outreach reply: Negative]" or
"[Outreach reply: Neutral]", so an Outlook rule files it in "Outreach replies" with that tag.

    Instantly                                   Forwarded as    To (3 Nov 2026, Ariel)
    marked interested                           Positive        REPLY_FORWARD_TO (the sales team)
    marked not interested                       Negative        REPLY_FORWARD_TO (the sales team)
    a real reply with no mark                   Neutral         ALERT_TO only (handled by Amodh)
    a reply asking not to be emailed again      not forwarded (an opt-out, not a sales lead)
    a reply handing us to someone else          Referral        REPLY_FORWARD_TO (12 Nov 2026, Ariel), whatever
                                                                Instantly's label; the automation emails the new
                                                                person (referrals.py, referral_intro.py)

The email starts with (agreed with Ariel):
    Company: FELFEL (Switzerland)
    Contact: Senior Product Owner, <their address>
    Their reply: positive, received Monday 26 October 2026
then their reply, then our email underneath. Each reply goes once; when its mark changes later
(Neutral, then Positive), it goes once more with the new tag. data/forwarded_replies.json keeps the
tags already sent per HubSpot contact ID (no names or addresses).
"""

import datetime as dt
import html as html_lib
import json
import os

from .common import ROOT, from_us
from .next_in_line import parse_time, tagged_company_of

FILE = ROOT / "data" / "forwarded_replies.json"
KIND = {"marked interested": "Positive", "marked not interested": "Negative", "replied": "Neutral"}
# Who gets each kind (3 Nov 2026, Ariel): a clear yes or no goes to the sales team, the rest only to Amodh.
SECRET = {"Positive": "REPLY_FORWARD_TO", "Negative": "REPLY_FORWARD_TO", "Neutral": "ALERT_TO",
          "Referral": "REPLY_FORWARD_TO"}
INDIA = dt.timezone(dt.timedelta(hours=5, minutes=30))


def load(path=None):
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data, path=None):
    path = path or FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(data.items())), indent=1) + "\n", encoding="utf-8")


def due(seen, done, referral_ids=()):
    """[(contact record, kind)] to forward now: a tag not sent yet; Neutral only as the first one. A reply that
    hands us to someone else (referral_ids) goes as "Referral" instead of its label (12 Nov 2026)."""
    out = []
    referral_ids = {str(i) for i in referral_ids}
    for record, _lead, event in seen:
        kind = "Referral" if str(record["id"]) in referral_ids else KIND.get(event)
        had = done.get(str(record["id"])) or []
        if kind and kind not in had and not (kind == "Neutral" and had):
            out.append((record, kind))
    return out


def _long_date(when):
    d = (when or dt.datetime.now(dt.timezone.utc)).astimezone(INDIA).date()
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B %Y')}"


def their_reply(emails_api, address):
    """(their latest real reply, our email before it) from the thread, or (None, None)."""
    from .sync import _with_body, auto_reply_reason
    thread = emails_api.thread_emails(address)
    real = []
    for e in thread:
        if e.get("ue_type") == 2 and not from_us(e):  # 12 Nov 2026: never a Diablo address writing in
            full = _with_body(emails_api, e)
            if not auto_reply_reason(full):
                real.append(full)
    if not real:
        return None, None
    reply = real[-1]
    sent = [e for e in thread if e.get("ue_type") in (1, 3)
            and str(e.get("timestamp_email") or "") <= str(reply.get("timestamp_email") or "")]
    original = _with_body(emails_api, sent[-1]) if sent else None
    return reply, original


def compose(kind, company, country, job, address, reply, original):
    """(subject, html, text) of the forward."""
    from .sync import add_forwarded
    when = parse_time(reply.get("timestamp_email") or reply.get("timestamp_created"))
    lines = [f"Company: {company}" + (f" ({country})" if country else ""),
             f"Contact: {job or 'Contact'}, {address}",
             f"Their reply: {kind.lower()}, received {_long_date(when)}"]
    html = "".join(f"<div>{html_lib.escape(line)}</div>" for line in lines)
    text = "\n".join(lines)
    html, text = add_forwarded(html, text, reply)
    if original:
        html, text = add_forwarded(html, text, original)
    subject = f"[Outreach reply: {kind}] {reply.get('subject') or 'Reply'} ({company})"
    return subject, html, text


def forward_replies(hs, emails_api, seen, settings, log=print, smtp=None, path=None, referral_ids=()):
    """Forward the replies not forwarded yet. Returns how many went. Never stops the run."""
    from .daily_report import DEFAULTS, recipients, send_mail
    done = load(path)
    todo = due(seen, done, referral_ids)
    if not todo:
        return 0
    password = os.environ.get("DAILY_REPORT_APP_PASSWORD", "")
    to_for = {kind: recipients(os.environ.get(secret, "")) for kind, secret in SECRET.items()}
    if not password or emails_api is None:
        log(f"{len(todo)} replies wait to be forwarded: add the GitHub secrets DAILY_REPORT_APP_PASSWORD and "
            "INSTANTLY_EMAILS_KEY (to read the replies)")
        return 0
    cfg = dict(DEFAULTS, **(settings.get("daily_report") or {}))
    owner_of, companies = tagged_company_of(hs, [r["id"] for r, _ in todo], ["name", "country"])
    sent = 0
    for record, kind in todo:
        to = to_for.get(kind) or []
        if not to:
            log(f"A {kind.lower()} reply waits to be forwarded: add the GitHub secret {SECRET[kind]}")
            continue
        p = record.get("properties") or {}
        address = p.get("email") or ""
        company = (companies.get(owner_of.get(str(record["id"]))) or {}).get("properties") or {}
        name = company.get("name") or "a company"
        try:
            reply, original = their_reply(emails_api, address)
            if not reply:
                continue  # Instantly holds no real reply yet: tried again at the next run
            subject, html, text = compose(kind, name, company.get("country"), p.get("jobtitle"), address, reply,
                                          original)
            send_mail(subject, text, html, cfg, to, password, smtp)
        except Exception as err:
            log(f"{name}: the {kind.lower()} reply could not be forwarded ({str(err)[:200]}); tried again next run")
            continue
        done[str(record["id"])] = (done.get(str(record["id"])) or []) + [kind]
        save(done, path)
        sent += 1
        log(f"{name}: {kind.lower()} reply forwarded")
    return sent
