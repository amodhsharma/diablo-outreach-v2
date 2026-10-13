# Diablo outreach pipeline (version 2)

Finds distributors, wholesalers, retailers and marketplace sellers in a Location, puts them in
HubSpot for approval, finds buyer contacts with Apollo and queues emails in Instantly.

Version 2 uses **no Claude API**. The research is done by Claude through the
**outreachResearch skill** (`skills/outreachResearch`), every 6 hours (about 2 AM, 8 AM, 2 PM and 8 PM IST) or as a manual
run. The personal opening line for each contact is written by Claude through the
**outreach-mail-writing skill** (`skills/outreachMailWriting`), every 2 hours or as a manual run. Everything else runs from buttons in the **Actions** tab. Keys live only in GitHub secrets.

Version 1 (amodhsharma/diablo-outreach) is kept as it is, for reference only.

## How a Location gets researched

1. Press **2a - Manual - Research: add a new market to the queue**: type the Location, the Channels (separated by
   commas), languages and companies wanted per Channel.
2. Every 6 hours Claude takes the oldest waiting job (one job per run), researches the Location once and sends one
   helper per Channel at the same time, then saves one report and one JSON to `research/<date>/`.
   A manual run does the same at any time: "Run now" on the scheduled task, or `/outreach-research`
   in a Claude chat (name a Location or job ID to run that one).
3. **2e - Automatic/Manual - Put new companies into HubSpot for review** starts by itself, checks the file again and adds the
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

## The buttons

| Button | What it does |
|---|---|
| 1 - Manual - One-time setup: create the Outreach fields in HubSpot | Adds the two contact fields and any missing Lead Status choices (once per account). In a test account it also creates Lead Source and Industry Type to match live. A dry run reads the account and lists exactly what would be added |
| 2a - Manual - Research: add a new market to the queue | Adds a job: one Location, one or more Channels |
| 2b - Manual - Research: cancel a market not yet researched | Stops a Waiting or On hold job (or one Channel of it) |
| 2c - Manual - Research: try a failed market again | Puts a Failed job (or one Channel of it) back to Waiting |
| 2d - Manual - Research: allow a market we have done before | Lets an On hold repeat run |
| 2e - Automatic/Manual - Put new companies into HubSpot for review | Runs by itself when new research is saved; can be pressed by hand |
| 2f - Timer/Manual - Refresh the "already in HubSpot" list so research skips them | Runs every 3 hours; keeps `data/known_companies.csv`, every company in HubSpot (no 10,000 limit). Most runs only read what was added or changed since the last run; Sundays, the first run and a run after switching account read everything. Research checks every company it finds against the full list, and the import checks again live in HubSpot |
| 2g - Automatic/Manual - Research: add the next city from the automatic list | Runs by itself after every 2f run. Adds the next city from `data/auto_markets.csv` (UK, EU, Canada and South America, in a random order that takes turns between regions) to the queue: at most one a day, only when nothing is waiting in the queue and fewer than 100 AUTO-OUTREACH companies wait for review (Lead Status New) in HubSpot. Canada, Germany and Austria are left out until a lawyer has checked the cold email rules there, and so is every country in `data/excluded_countries.txt`. Markets added by hand with 2a always run first. Settings: `auto_markets` in `config/settings.yaml` |
| 3 - Manual - Find the top 4 people at each approved company | For companies set to GATE1: Approved for outreach that have no contacts yet: Apollo finds the top 4 verified buyer emails, most senior first. An email already in HubSpot is never added. Nobody is paid for twice |
| 4a - Manual - Refresh the list of contacts that still need email lines | Saves the AUTO-OUTREACH contacts with Lead Status New to `mail/pending.json` for the writing skill. Buttons 3 and 4c already refresh this list themselves at the end of their run; press 4a only after editing contacts in HubSpot by hand |
| 4c - Automatic/Manual - Put written email lines into HubSpot for approval | Runs by itself when new lines are saved: puts them in Outreach personal line and sets Lead Status to "New, Personal line filled" |
| 4b - Timer/Manual - Send approved contacts to Instantly to be emailed | Every 3 hours by itself (or pressed by hand): starts each company with its most senior GATE2: Approved to send contact. Every Location and Channel shares one campaign per month (e.g. "Diablo | NOV2026"), created paused: press Start on it in Instantly once a month. A company's later contacts stay in the campaign of its first email |
| 5 - Timer/Manual - Update HubSpot with who was emailed, replied or bounced, and line up the next person | Every 3 hours: replies, interest, bounces and opt-outs back to Lead Status (AUTO-OUTREACH records only), and moves companies on to their next person |
| 6 - Manual - Health check: mailboxes, campaigns and why someone isn't being emailed | Changes nothing. **Mailboxes:** every sending mailbox in Instantly marked Ready, Warming up or Problem (sending on or not, warm-up score, warm-up emails landing in inbox or spam, sender name, daily limit, campaigns using it), with a "Needs attention" list. **Campaigns:** whether each is sending and if not why. **HubSpot:** what 4b would do now with each GATE2: Approved to send contact. Answer on the run's summary page and in `diagnostics/instantly_status.md` |

## How the email lines get written

1. **3 - Manual - Find the top 4 people at each approved company** saves the new contacts (job title and company research only, no names or
   emails) to `mail/pending.json`.
2. Every 2 hours Claude runs the outreach-mail-writing skill: it writes a personal opening for
   up to 60 contacts, checks them and saves one file to `mail/lines/<date>/`. The subject line is
   fixed in the template.
   A manual run does the same at any time: `/outreach-mail-writing` in a Claude chat.
3. **4c - Automatic/Manual - Put written email lines into HubSpot for approval** starts by itself, checks the file again and puts the
   line in each contact's *Outreach personal line* and sets Lead Status to *"New, Personal line filled"*. Gate 2 is
   yours: read it and change Lead Status to *GATE2: Approved to send*. To change a line, edit it in
   HubSpot before approving.

## How each button runs

After each number, the name says how the button runs; where two are given, the first is the
usual way.

- **Manual:** only when someone presses it.
- **Automatic:** by itself straight after the step before it (2e when research is saved, 2g after
  every 2f run, 4c when email lines are saved). Pressing it by hand imports anything not yet imported; nothing is done
  twice.
- **Timer:** cron-job.org presses it 8 times a day. Pressing it by hand as well is safe: if a run
  is already going, the second one waits and then finds nothing left to do.
- **4b by hand starts as a dry run** (it only shows the plan). Untick "Dry run" to really send. The
  timer always sends for real.
- **4a is Manual only**, but 3 and 4c refresh the same list themselves at the end of their run.
- **The two Claude tasks are not GitHub buttons:** research runs at 1:58 and 7:58 (AM and PM IST)
  and email lines every 2 hours, and both can be started by hand in a Claude chat
  (`/outreach-research`, `/outreach-mail-writing`).
- **If cron-job.org stops** (for example when its GitHub key expires), the Timer buttons stop until
  it is fixed; cron-job.org emails a failure notice, and the buttons can still be pressed by hand.

## The outside timer

GitHub's own timer often skips runs, so cron-job.org presses one button every hour in turn:
4b at 12, 3, 6 and 9 (AM and PM, IST), 5 at 1, 4, 7 and 10, and 2f at 2, 5, 8 and 11. Each
runs 8 times a day. It uses one key limited to starting this repository's buttons. Set-up and
renewal: `docs/outside_timer.md`.

## One person per company at a time, in turn

Agreed 13 Oct 2026. Button 3 finds the top 4 people at each company. Each must be approved at
gate 2. Then, with one email to the company every 3 days:

| Day | Email |
|---|---|
| 0, 3, 6, 9 | Person 1, 2, 3 and 4 get their first email (from Instantly) |
| 12, 15, 18, 21 | Round 2: each gets the reminder (`templates/follow_up.json`) as a reply in their own thread |
| 24, 27, 30, 33 | Round 3: each gets the last note (`templates/follow_up_2.json`) the same way |

- Nobody gets another email less than 7 days after their previous one: with fewer people, the
  next email waits until the week is up (2 people: days 0, 3, 7, 10, 14, 17).
- The moment anyone at the company replies or opts out, nobody else there is emailed. A bounced
  person is skipped.
- After round 3 with no reply, the company becomes **Unqualified**.
- Who was emailed and when is read from Instantly itself, so HubSpot needs no extra fields for it.
- Rounds 2 and 3 are sent by button 5 (Sync) using Instantly's reply feature. That needs the
  GitHub secret `INSTANTLY_EMAILS_KEY` (an Instantly key with the scope `emails:all`); until it
  is added, those emails wait and nothing is marked Unqualified.
- Settings: `send.next_contact_after_days` and `send.rotation` in `config/settings.yaml`.
- Everyone whose email Apollo revealed is listed in `data/apollo_kept.json` (kept as a contact)
  or `data/apollo_skipped.json` (e.g. unverified), by Apollo's ID, so nobody is paid for twice.

## Countries we never research

`data/excluded_countries.txt` lists the countries Diablo does not look for leads in (set 12 Oct
2026), one per line. Button 2a refuses a market in any of them, and the automatic city list (2g)
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
| `INSTANTLY_EMAILS_KEY` | A third Instantly key with the scope `emails:all`, used only by button 5 to send rounds 2 and 3 as replies in each person's thread |
| `INSTANTLY_ACCOUNTS_KEY` | A second, read-only Instantly key with the scope `accounts:read`, used only by button 6 to check the mailboxes (`docs/instantly_accounts_key.md`) |
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
