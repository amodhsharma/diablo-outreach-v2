# Diablo outreach pipeline (version 2)

Finds distributors, wholesalers, retailers and marketplace sellers in a Location, puts them in
HubSpot for approval, finds buyer contacts with Apollo and queues emails in Instantly.

Version 2 uses **no Claude API**. The research is done by Claude through the
**outreachResearch skill** (`skills/outreachResearch`), every 3 hours (2:28, 5:28, 8:28 and 11:28, AM and PM IST) or as a manual
run. The personal opening line for each contact is written by Claude through the
**outreach-mail-writing skill** (`skills/outreachMailWriting`), every 3 hours (12:28, 3:28, 6:28 and 9:28, AM and PM IST) or as a manual run. Everything else runs from buttons in the **Actions** tab. Keys live only in GitHub secrets.

Version 1 (amodhsharma/diablo-outreach) is kept as it is, for reference only.

## How a Location gets researched

1. Press **2 - Research** and choose "Add a market": type the Location, the Channels (separated by
   commas), languages and companies wanted per Channel.
2. Every 3 hours Claude takes the oldest waiting job (one job per run), researches the Location once and sends one
   helper per Channel at the same time, then saves one report and one JSON to `research/<date>/`.
   A manual run does the same at any time: "Run now" on the scheduled task, or `/outreach-research`
   in a Claude chat (name a Location or job ID to run that one).
3. **2 - Research** starts by itself, checks the file again (and each company's website and Apollo) and adds the
   companies to HubSpot with Lead Status *New*. The queue line is marked Done.

## HubSpot fields (agreed 13 Oct 2026)

The pipeline uses HubSpot's own fields wherever one fits. It adds only two fields, both on
contacts: **Outreach personal line** and **Outreach order** (who is emailed first, 1 to 4).
Everything else is an existing field: Lead Source, Lead Status, Industry Type (the Channel),
Ideal Customer Profile Tier, Company name, Domain, City, Country, Company owner, name, email
and job title. Apollo IDs are kept in GitHub (`data/apollo_kept.json`, `data/apollo_skipped.json`),
not in HubSpot.

**The safety rule: Lead Source = AUTO-OUTREACH.** Every company and contact the pipeline
creates carries it, and the pipeline never changes a record without it. Every search for work
includes it; every change re-reads each record first and stops the whole job, saving nothing,
if any record lacks it (`outreach/hubspot_client.py`, TagGuard). Reading every company is
allowed only for the duplicate checks. Tests fail if any code writes to HubSpot another way.
Removing the tag from a record is a "hands off" switch; nobody should type AUTO-OUTREACH on
their own records.

**Lead Status** says where each record is (`outreach/stages.py`). Three choices are added to it:
*GATE1: Approved for outreach* (companies), *"New, Personal line filled"* and *GATE2: Approved to send* (contacts). The existing
choices are never changed.

| Step | Company | Contact |
|---|---|---|
| Research found it / contact found | New | New |
| No website, or no contacts found | Missing Info | |
| **Gate 1**: a person approves the company | **GATE1: Approved for outreach** | |
| Email line written | | "New, Personal line filled" |
| **Gate 2**: a person reads the line and approves it | | **GATE2: Approved to send** |
| Emails going out | Attempted to Contact | Attempted to Contact |
| They replied | In Progress | In Progress |
| Rejected, not interested, no reply, opted out or bounced | Unqualified | Unqualified |

Any other Lead Status (for example Emailed or Won) means a person has taken the record over:
the pipeline stops there and never changes it. To reject a company at gate 1, set it to
Unqualified; to reject one person at gate 2, set them to Unqualified (the others carry on).

**To take a company over from the pipeline**, set its Lead Status to In Progress, Emailed or Won,
or clear its Lead Source. "Attempted to Contact" is the pipeline's own "still emailing" status, so
setting it by hand does not stop the emails. A colleague unsubscribing does not turn a company
Unqualified while someone else there is still talking to us (In Progress).

If HubSpot links a new contact to a second company by itself (by email domain), the pipeline
only ever uses and changes the AUTO-OUTREACH one.

## The buttons (agreed 14 Oct 2026)

Three numbered buttons. Everything you never need to think about (strict checks, duplicate checks,
the lists the system keeps) runs inside them by itself. Each run's page shows its steps in order:
**Before** (tests, up to date), the **main steps**, and **After** (save, and fail loudly if any step
failed, so GitHub emails you). One step failing never stops the others.

| Button | What you do | What runs inside it by itself |
|---|---|---|
| **1 - Setup HubSpot (once per account)** | Press once per account, first with "Dry run" ticked | Adds the two contact fields and the Lead Status choices; reads every company already in that account |
| **2 - Research** | Pick "What to do": Add a market (Location, Channels, optional languages and number), Cancel a market, Try a failed market again, or Allow a repeat (Job ID, optional Channel) | **When Claude saves research:** strict check, duplicate check, **website check and Apollo pre-check**, then the companies arrive as New (or Missing Info when a check fails). **Every 3 hours:** refresh the "already in HubSpot" list, import anything waiting, add the next automatic city |
| **3 - Outreach** | Nothing: the timer runs it every 3 hours. Press it to run now, or tick "Check only" for the health report. Testing only: type CONFIRM in "TEST ONLY" for 15-minute gaps instead of 3 and 7 days (refused on live; the test run may send with the placeholder booking link) | In order: Instantly results into Lead Status (a reply stops a company first), the next person in line and rounds 2 and 3; Apollo finds the top 4 people at GATE1 companies; Claude's personal lines into HubSpot (also the moment Claude saves them); GATE2 people sent to Instantly; health check; the list of people Claude still has to write for |

The two Claude scheduled tasks are not GitHub buttons: research runs at 2:28, 5:28, 8:28 and 11:28 (AM and PM
IST) and personal lines at 12:28, 3:28, 6:28 and 9:28 (AM and PM IST), both every 3 hours (agreed 14 Oct 2026). Both can be started by hand in a Claude chat
(`/outreach-research`, `/outreach-mail-writing`).

**Changing over (14 Oct 2026):** today's version is frozen as the branch `v2-before-revamp`. The
old buttons (1, 2a to 2g, 3, 4a to 4c, 5, 6) stay until the three new ones have been tested, then
they are removed. Until then, the new buttons start by themselves when Claude saves research or
lines; the old ones only run when pressed or by the old timer jobs.

## How the email lines get written

1. **3 - Outreach** (every 3 hours) finds the top 4 people at each GATE1 company and saves the new contacts (job title and company research only, no names or
   emails) to `mail/pending.json`.
2. Every 3 hours Claude runs the outreach-mail-writing skill: it writes a personal opening for
   up to 60 contacts, checks them and saves one file to `mail/lines/<date>/`. The subject line is
   fixed in the template.
   A manual run does the same at any time: `/outreach-mail-writing` in a Claude chat.
3. **3 - Outreach** starts by itself, checks the file again and puts the
   line in each contact's *Outreach personal line* and sets Lead Status to *"New, Personal line filled"*. Gate 2 is
   yours: read it and change Lead Status to *GATE2: Approved to send*. To change a line, edit it in
   HubSpot before approving.

## The outside timer

GitHub's own timer often skips runs, so cron-job.org presses the buttons on time, using one key
limited to starting this repository's buttons. From the change-over: button 3 at 12, 3, 6 and 9
(AM and PM, IST) and button 2 ("Automatic run") at 2, 5, 8 and 11. Set-up, renewal and the exact
settings: `docs/outside_timer.md`. If cron-job.org stops (for example when its key expires), it
emails a failure notice and the buttons can still be pressed by hand.

## One person per company at a time, in turn

Agreed 13 Oct 2026. Button 3 finds the top 4 people at each company. Each must be approved at
gate 2. Then, with one email to the company every 3 days:

| Day | Email |
|---|---|
| 0, 3, 6, 9 | Person 1, 2, 3 and 4 get their first email (from Instantly) |
| 12, 15, 18, 21 | Round 2: each gets the reminder (`templates/follow_up.json`) as a reply in their own thread |
| 24, 27, 30, 33 | Round 3: each gets the same reminder again the same way (one template for both rounds, agreed 14 Oct 2026) |

- Nobody gets another email less than 7 days after their previous one: with fewer people, the
  next email waits until the week is up (2 people: days 0, 3, 7, 10, 14, 17).
- The moment anyone at the company replies or opts out, nobody else there is emailed. A bounced
  person is skipped.
- After round 3 with no reply, the company becomes **Unqualified**.
- Who was emailed and when is read from Instantly itself, so HubSpot needs no extra fields for it.
- Rounds 2 and 3 are sent by button 3 (Outreach) using Instantly's reply feature. That needs the
  GitHub secret `INSTANTLY_EMAILS_KEY` (an Instantly key with the scope `emails:all`); until it
  is added, those emails wait and nothing is marked Unqualified.
- Settings: `send.next_contact_after_days` and `send.rotation` in `config/settings.yaml`.
- Everyone whose email Apollo revealed is listed in `data/apollo_kept.json` (kept as a contact)
  or `data/apollo_skipped.json` (e.g. unverified), by Apollo's ID, so nobody is paid for twice.

## Countries we never research

`data/excluded_countries.txt` lists the countries Diablo does not look for leads in (set 12 Oct
2026), one per line. Button 2 refuses a market in any of them, and the automatic city list
skips them. To allow a country again, delete its line.

## The queue

`research/queue.csv` holds one line per Location and Channel, and lines are never deleted, so it
is also the record of everything covered. It opens on GitHub as a table. Statuses: Waiting,
On hold: already covered, Done, Done fewer than wanted, Failed, Cancelled.

- A repeat is the same Location with the same Channel. Capitals, spaces and singular or plural
  are ignored ("Wholesaler" matches "wholesalers"); any other wording is new.
- The country must be real: a typo such as "Mumbai, Infia" stops the button with "Did you mean
  India?" and nothing is added. Short forms like UK, USA and UAE are accepted, and a Location typed
  in lower case gets capitals ("dublin, ireland" is saved as "Dublin, Ireland").
- Locations match as written: "UK" and "United Kingdom" are different.
- A repeat goes On hold until someone presses **2d - Manual - Research: allow a market we have done before**.
- A failed Channel runs again by itself once, at the next run, and the new files replace the
  earlier ones. If it fails again it is marked Failed until someone presses **2c - Manual - Research: try a failed market again**.

## Where things are

| Path | What it is |
|---|---|
| `skills/outreachResearch/SKILL.md` | The steps Claude follows for every research run |
| `skills/outreachResearch/prompts/` | The research prompt, the Location prompt and the four Channel templates |
| `skills/outreachResearch/settings.yaml` | Companies wanted, floor and search limits |
| `skills/outreachResearch/output_format.md` | The JSON format and what the strict check rejects |
| `research/<date>/` | Each run's report (`_report.md`) and JSON |
| `skills/outreachMailWriting/` | The steps, writing rules and strict check for the email lines |
| `mail/pending.json` | Contacts waiting for email lines |
| `mail/lines/<date>/` | Each writing run's lines; `mail/imported.txt` records which were imported |
| `data/known_companies.csv` | Companies already in HubSpot (nightly) |
| `data/company_notes.json` | What each company distributes and why it fits, for email writing |
| `config/exclude.txt` | Companies that must never be researched or contacted |
| `config/settings.yaml` | Contacts, salesperson assignment, sending and sync settings |
| `templates/` | The first email and the reminder; `email_templates_for_approval.md` holds the per-Channel drafts |

## Secrets

Settings > Secrets and variables > Actions > New repository secret.

| Name | Where to get it |
|---|---|
| `HUBSPOT_TOKEN_TEST` | The test account > Development > Legacy apps > the private app. Scopes: crm.objects.companies read and write, crm.objects.contacts read and write, crm.schemas.companies read and write, crm.schemas.contacts read and write, crm.objects.owners read |
| `APOLLO_API_KEY` | Apollo > Settings > Integrations > API keys |
| `INSTANTLY_API_KEY` | Instantly > Settings > Integrations > API keys (scopes: campaigns and leads) |
| `INSTANTLY_EMAILS_KEY` | A third Instantly key with the scope `emails:all`, used only by button 3 to send rounds 2 and 3 as replies in each person's thread |
| `INSTANTLY_ACCOUNTS_KEY` | A second, read-only Instantly key with the scope `accounts:read`, used only by button 3's health check to read the mailboxes (`docs/instantly_accounts_key.md`) |
| `HUBSPOT_TOKEN_LIVE` | Only when testing is finished: the same kind of private app, made in the live account, with the same scopes |

To use the live HubSpot account for the automatic jobs, add a repository variable
`PIPELINE_TARGET` = `live` (Settings > Secrets and variables > Actions > Variables).

## Safety built in

- The strict check runs twice: in Claude before saving and in GitHub before importing. A file
  that fails is rejected whole and the job is marked Failed with the reason.
- Every job checks which HubSpot account the key belongs to and stops on a mismatch.
- Only records with Lead Source AUTO-OUTREACH are ever changed (see "HubSpot fields").
- Nothing is sent without both gates; Instantly campaigns are created paused.
- Companies already in HubSpot are never added again; Apollo spend stops at the credit cap.

## Running the tests

```
pip install -r requirements.txt
python -m pytest -q
```
