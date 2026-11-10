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

**Big partners only (10 Nov 2026, prompt version 6).** Research looks only for big wholesalers,
distributors, importers and supermarket chains, not small retailers. A market added with button 2 is
searched for: distributors (confectionery importers, snack, health food and British food importers,
distributors of international confectionery brands), FMCG distributors (consumer goods, mass
consumption, sales and distribution companies), wholesalers (confectionery, cash and carry),
kiosk and convenience wholesalers, halal food distributors, kosher food distributors and supermarket
chains. Then distributors, FMCG distributors and wholesalers again in the main business cities and
regional capitals, one per region in a large country, so the strong regional players are found. Every
company must be big enough (HARD RULE 12: about 200 shops or more, regional or national coverage, a big
warehouse, fleet or sales force, the appointed distributor for international brands, or listed; at
least about 10 stores for a chain) and its "Why they fit Diablo" ends with "Scale: " and "Storage: ".
Research searches through the brands first (who distributes Ferrero, Mondelez, Haribo ... in the
country), uses the trade's own words in the local language and follows Diablo's own list of big
distributors. It looks for at most 30 per channel and stops when it runs out. Sports shops, health food
shops, pharmacies, gift and hamper companies, office snack suppliers, vending, travel retail and the
other small or niche channels are no longer searched (`docs/channels.json`).

## HubSpot fields (agreed 13 Oct 2026)

The pipeline uses HubSpot's own fields wherever one fits. It adds only four fields, all on
contacts: **Outreach personal line**, **Outreach company note** (finishes "we noticed <company> ..."
in the first email and gives the reason in the forwards, added 15 Oct 2026), **Outreach order**
(who is emailed first, 1 to 4) and **Outreach contact source** (Apollo, or Company website for a
company's own contact address used when Apollo held nobody, added 19 Oct 2026; run button 1 once
more in each account to add it).
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

**Lead Status** says where each record is (`outreach/stages.py`). Button 1 adds the pipeline's own
choices to it (for example *GATE1: Approved for outreach*, *"New, Personal line filled"* and *GATE2:
Approved to send*). The team's own choices, such as plain Unqualified, are never changed.

| Step | Company | Contact |
|---|---|---|
| Research found it / contact found | New | New |
| No website, or no contacts found | Missing Info | |
| **Gate 1**: a person approves the company | **GATE1: Approved for outreach** | |
| Email line written | | "New, Personal line filled" |
| **Gate 2**: a person reads the line and approves it | | **GATE2: Approved to send** |
| Emails going out | Attempted to Contact | Attempted to Contact (person 1's introduction) |
| Forward sent to the next person (persons 2 to 4) | | Forward sent |
| Person 1's one reminder sent | | Reminder sent |
| They replied | In Progress | In Progress |
| A clear yes or no (Instantly label Interested or Not interested) | END: Forwarded to Sales Team | END: Forwarded to Sales Team (the person and everyone else there) |

**The dead ends (2 Nov 2026).** Each has its own choice starting "Unqualified:", so HubSpot shows why
outreach stopped. Button 1 renamed the older ones in place, so their records moved with them.

| What happened | Company | Person emailed | The others there |
|---|---|---|---|
| You rejected it | Unqualified | Unqualified company | Unqualified company |
| The person said no (before 3 Nov 2026; a clear no now goes to END: Forwarded to Sales Team) | Unqualified: Employee response negative | Unqualified: Response negative | Unqualified: Colleague response negative |
| The person opted out (unsubscribed or blocklisted) | Unqualified: Employee Opted-out/Blocklist | Unqualified: Opted-out/Blocklist | Unqualified: Colleague Opted-out/Blocklist |
| Emailed, no reply after 1 week | Unqualified: Contacted, but no response | Unqualified: Contacted, but no response | Unqualified: Colleague Contacted, but no response |
| Its company inbox bounced and nobody is left | Unqualified: Company inbox bounced | Unqualified: Inbox Bounced | - |
| The person's address is dead, someone else is left | Attempted to Contact (unchanged) | Unqualified: Contact corrupt (Outreach order 0) | the next person moves up to number 1 and goes to GATE2 |
| The person's address is dead, nobody is left | Unqualified: Personal inbox bounced | Unqualified: Contact corrupt | - |
| Bounced for another reason (a full mailbox) | unchanged | Unqualified: Bounced, other reason | unchanged |
| Blocked by the company's mail policy (Google), nobody else there emailed yet | Unqualified: Bounced, other reason | Unqualified: Bounced, other reason | not emailed |
| You mark the person Rejected/Redirected (on leave, or they point to someone else) | unchanged; with nobody left: Unqualified: One contact inputted, which is unavailable | Unqualified: Rejected/Redirected by company owner (Outreach order 0) | the next person moves up (see below) |

Plain "Unqualified" means a person set it, and the pipeline never changes it. Only AUTO-OUTREACH
records are ever changed.

**Bounces (3 Nov 2026).** Microsoft's "5.4.1 Access denied" counts as a dead address. The bounce message
itself is written into the Stop reason, and bounces from before 3 Nov 2026 are read again once to add it (15 a run, so the run stays within its time).

**Replies (3 Nov 2026).** When Instantly labels a reply Interested or Not interested, it is forwarded to
the GitHub secret REPLY_FORWARD_TO, and the company, the person and everyone else there become "END:
Forwarded to Sales Team". The pipeline stops there. Every other reply is forwarded only to the secret
ALERT_TO; opt-outs are not forwarded. Button 4 reads each reply that is not labelled (and each
out-of-office that says the person has left) for 1 to 3 new addresses at the same company with words like
"please contact". When it is sure, it adds them as contacts (AUTO-OUTREACH, job title "Referred by
colleague", legal basis "Legitimate interest - prospect/lead", linked to the company), sets the person
who replied to "Unqualified: Rejected/Redirected by company owner" and puts the company back on
Attempted to Contact (20 replies a run). When it is not sure, it changes nothing. Each morning with the daily summary, an
email goes to ALERT_TO only: how many such replies were seen, switched and left, the details of the ones
left (company, job title, why, part of the reply and the HubSpot link) and how many are still waiting
from earlier days. A company on In Progress whose replier is now Rejected/Redirected, with nobody else
there in conversation, carries on.

**Paused companies that go on by themselves (10 Nov 2026).** A company on In Progress goes back to
Attempted to Contact when:
- the person who replied is Rejected/Redirected and nobody else there really replied (contacts left on In
  Progress by the rules before 2 Nov 2026, who never replied, no longer hold it back);
- the "reply" was an out-of-office after all (it is then read again as one);
- a neutral reply has waited 7 days with nobody changing anything: the person who replied keeps In
  Progress and is never emailed again by the loop, and the others there carry on.
The others paused with it go back to where they were: Attempted to Contact if Instantly already has them,
otherwise GATE2 (with a line) or New. Amodh's daily email lists these under "Back in the loop".

**Colleagues copied in, and stand-ins in out-of-offices (10 Nov 2026).** A colleague copied into a reply
("Kate has been looped into this thread") counts like an address in the text, when the reply's words say
it is a redirect. An out-of-office that names a stand-in at the same company ("in urgent cases contact
shop@...") adds that address as a new contact on New: button 3 numbers it and copies a line, and it gets
its own introduction. The person away stays as they are. Out-of-offices saying when the person is back
are now recognised in French, German, Italian, Spanish and Dutch too.

**When someone is on leave or points you to a colleague (2 Nov 2026).** Add the new person in HubSpot
with their email address and Lead source AUTO-OUTREACH, link them to the company, and leave Lead
Status and Outreach order empty. Then set the original person to "Unqualified: Rejected/Redirected by
company owner". At the next run of button 3 the original person gets Outreach order 0, the people you
added become number 1 (then the backups already there), and are set to New. The next mail-writing run
writes their line, they go to GATE2 by themselves, and the next run of button 4 emails them. Until then
nobody else at the company is emailed and the company is not closed as "no response". Button 3's
summary lists every company it moved on this way, and any person you added without an email address.

**Everyone at a company is emailed (2 Nov 2026).** Each person gets their own introduction through the
month's campaign, 3 days apart in Outreach order (company inbox last), and a reminder a week after their
own introduction, sent as a forward of it ("Fwd: " and its subject) from the mailbox that sent it. The
company closes 3 days after the last reminder with no reply; a reply or opt-out from anyone stops it at
once. Once you approve person 1 at gate 2, everyone else there goes to GATE2 by themselves, with person
1's line copied where theirs is missing. The same happens to a new contact added later at any company on
GATE1 or Attempted to Contact (at the next run of button 3 or 4); they are emailed at the run after. Reminders go on top of each mailbox's 30 introductions, at most
10 a mailbox a day. Every email goes into the campaign of the month it is sent in.

**The backlog (2 Nov 2026).** Companies closed as "no response" where someone got just one email are reopened each day, oldest first, only
in the room the new introductions leave under the day's limit, at most 50 a day (button 4, step 2b). Two
or more people: the next person's introduction at once, person 1's reminder 3 days later, then as above.
One person: their reminder at once, and the company closes 7 days later with no reply.

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

Four numbered buttons, and nothing else in the Actions tab. Everything you never need to think about (strict checks, duplicate checks,
the lists the system keeps) runs inside them by itself. Each run's page shows its steps in order:
**Before** (tests, up to date), the **main steps**, and **After** (save, and fail loudly if any step
failed, so GitHub emails you). One step failing never stops the others.

| Button | What you do | What runs inside it by itself |
|---|---|---|
| **1 - Setup HubSpot (once per account)** | Press once per account, first with "Dry run" ticked | Adds the four contact fields and the Lead Status choices; reads every company already in that account |
| **2 - Research** | Pick "What to do": Add a market (Location, Channels, optional languages and number), Cancel a market, Try a failed market again, or Allow a repeat (Job ID, optional Channel) | **When Claude saves research:** strict check, duplicate check, **website check and Apollo pre-check**, then the companies arrive as New (or Missing Info when a check fails). **Every 3 hours:** refresh the "already in HubSpot" list, import anything waiting, add the next automatic city |
| **3 - Find contacts** | Nothing: the timer runs it every 3 hours (12, 3, 6, 9). Press it to run now | In order: Apollo finds the top 4 people at GATE1 companies; Claude's personal lines into HubSpot (also the moment Claude saves them); the list of people Claude still has to write for. Never emails anyone |
| **4 - Send and follow up** | Nothing: the timer runs it every 3 hours (1, 4, 7, 10). Press it to run now. Its dropdown: "Usual run (results and send)" (picked to start with, and what the timer runs), "Run only Health Check" (nothing sent or changed) or "Run health check in addition to usual flow". Testing only: type CONFIRM in "TEST ONLY" for 15-minute gaps instead of 3 and 7 days (refused on live; the test run may send with the placeholder booking link) | In order: Instantly results into Lead Status (a reply stops a company first) and each company's loop (the forward to the next person naming the colleague before them, person 1's reminder, Unqualified at the end); person 1's introduction for GATE2 people at new companies; the health check only when chosen in the dropdown. The run's page starts with a table of what was sent and what is waiting until when; the health report (`diagnostics/instantly_status.md`) shows where every company is in its loop |
| **R - Daily summary email** | Nothing: the timer runs it at 9 AM India time. Press it with "Preview only" ticked to see the email without sending it | The partner outreach summary of the day before, from admin@diablosnosugar.com to three colleagues (GitHub secrets DAILY_REPORT_TO and DAILY_REPORT_APP_PASSWORD); reads HubSpot and Instantly, changes nothing |

The two Claude scheduled tasks are not GitHub buttons: research runs at 2:28, 5:28, 8:28 and 11:28 (AM and PM
IST) and personal lines at 12:28, 3:28, 6:28 and 9:28 (AM and PM IST), both every 3 hours (agreed 14 Oct 2026). Both can be started by hand in a Claude chat
(`/outreach-research`, `/outreach-mail-writing`).

The earlier buttons (2a to 2g, 3, 4a to 4c, 5 and 6) were removed on 14 Oct 2026 once the new ones
had passed their tests. The version before the change is kept as the branch `v2-before-revamp`.

## Your steps, from a new market to the first email

1. **Button 2:** "Add a market", with the Location (country or city) and the Channels.
2. **Claude researches it:** `/outreach-research` in a Claude chat, or within 3 hours by itself.
3. **Companies arrive in HubSpot by themselves** as soon as the research is saved.
4. **Gate 1:** set the companies worth contacting to *GATE1: Approved for outreach*.
5. **Button 3** (or its 3-hourly run): finds the contacts and puts them on the list for lines.
6. **Claude writes the personal lines:** `/outreach-mail-writing`, or within 3 hours by itself.
7. **Gate 2:** read each contact's line and set it to *GATE2: Approved to send*.
8. **Button 4** (or its 3-hourly run): person 1 is emailed, and the rest of the loop runs by itself.

## How the email lines get written

1. **3 - Find contacts** (every 3 hours) finds the top 4 people at each GATE1 company and saves the new contacts (job title and company research only, no names or
   emails) to `mail/pending.json`.
2. Every 3 hours Claude runs the outreach-mail-writing skill: it writes a personal opening for
   up to 60 contacts, checks them and saves one file to `mail/lines/<date>/`. The subject line is
   fixed in the template.
   A manual run does the same at any time: `/outreach-mail-writing` in a Claude chat.
3. **3 - Find contacts** starts by itself, checks the file again and puts the
   line in each contact's *Outreach personal line* and sets Lead Status to *"New, Personal line filled"*. Gate 2 is
   yours: read it and change Lead Status to *GATE2: Approved to send*. To change a line, edit it in
   HubSpot before approving.

## The outside timer

GitHub's own timer often skips runs, so cron-job.org presses the buttons on time, using one key
limited to starting this repository's buttons: button 3 at 12, 3, 6 and 9 (AM and PM, IST),
button 4 at 1, 4, 7 and 10, and button 2 ("Automatic run") at 2, 5, 8 and 11. Set-up, renewal and the exact
settings: `docs/outside_timer.md`. If cron-job.org stops (for example when its key expires), it
emails a failure notice and the buttons can still be pressed by hand.

## One loop per company, one person at a time

Agreed 14 Oct 2026 (replaces the three rounds of 13 Oct). Button 3 finds the top 4 people at each
company. Each must be approved at gate 2. Then, with one email to the company every 3 days:

| Day (3 people) | Email |
|---|---|
| 0 | Person 1: the introduction (`templates/template_2.json`, from the Instantly campaign) |
| 3 | Person 2: a forward of the chain from the same mailbox (`templates/forward.json`): "In case our earlier note to your colleague [person 1] did not reach the right desk..." with their personal line |
| 6 | Person 3: a forward of the latest email in the chain, naming person 2 (and person 4 on day 9, if there is one) |
| 9 | Person 1: one reminder as a reply in their own thread (`templates/follow_up.json`): "We wrote to you about a week ago...". This is the last email |
| 12 | No reply from anyone: the company becomes **Unqualified** |

- Persons 2 to 4 get one email each and never a second one (fewer emails, less risk of spam).
- Person 1's reminder is at least 7 days after their introduction (2 people: days 0, 3, 7; 1
  person: days 0 and 7).
- The moment anyone at the company replies or opts out, also in reply to a forward, nobody else
  there is emailed. A bounced person is never named; if person 1 bounces, person 2 gets the
  introduction instead. A dead address (28 Oct 2026, `outreach/corrupt.py`) becomes "Unqualified
  Contact: Contact corrupt" with Outreach order 0, everyone below moves up one, and the new number 1
  becomes GATE2 (now, or as soon as its personal line arrives) and gets the introduction at the next
  run of button 4.
- Everything stays in the one monthly campaign and mailbox: only person 1 is a campaign lead, the
  others are reached by forwarding person 1's thread. Who was emailed and when is read from
  Instantly itself, so HubSpot needs no extra fields for it.
- The forwards and the reminder are sent by button 4 (Send and follow up) using Instantly's forward and
  reply features. That needs the GitHub secret `INSTANTLY_EMAILS_KEY` (an Instantly key with the
  scope `emails:all`); until it is added, those emails wait and nothing is marked Unqualified.
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
- A repeat goes On hold until someone presses **2 - Research** with "Allow a repeat".
- A failed Channel runs again by itself once, at the next run, and the new files replace the
  earlier ones. If it fails again it is marked Failed until someone presses **2 - Research** with "Try a failed market again".

## Where things are

| Path | What it is |
|---|---|
| `skills/outreachResearch/SKILL.md` | The steps Claude follows for every research run |
| `skills/outreachResearch/prompts/` | The research prompt, the Location prompt and the Channel templates (version 6 from 10 Nov 2026: `*_6.md`) |
| `skills/outreachResearch/settings.yaml` | Companies wanted, floor and search limits |
| `skills/outreachResearch/output_format.md` | The JSON format and what the strict check rejects |
| `research/<date>/` | Each run's report (`_report.md`) and JSON |
| `skills/outreachMailWriting/` | The steps, writing rules and strict check for the email lines |
| `mail/pending.json` | Contacts waiting for email lines |
| `mail/lines/<date>/` | Each writing run's lines; `mail/imported.txt` records which were imported |
| `data/known_companies.csv` | Companies already in the LIVE HubSpot (refreshed by button 2 when on live, and by button 1 on live) |
| `data/known_companies_test.csv` | The same for the test HubSpot (19 Oct 2026: one list per account; research on test uses no list) |
| `data/pipeline_target.txt` | Which account the pipeline works on (written by button 2), read by the research skill |
| `data/company_notes.json` | What each company distributes and why it fits, for email writing |
| `config/exclude.txt` | Companies that must never be researched or contacted |
| `config/settings.yaml` | Contacts, salesperson assignment, sending and sync settings |
| `templates/` | The introduction, the forward to the next person and person 1's reminder; `email_templates_for_approval.md` holds the per-Channel drafts |

## Secrets

Settings > Secrets and variables > Actions > New repository secret.

| Name | Where to get it |
|---|---|
| `HUBSPOT_TOKEN_TEST` | The test account's key, never the developer account's: in your main (developer) account go to Development > Testing > Test accounts (create one if needed), open the test account, then inside it Development > Legacy apps > Create legacy app (Private). Scopes: crm.objects.companies read and write, crm.objects.contacts read and write, crm.schemas.companies read and write, crm.schemas.contacts read and write, crm.objects.owners read. Create app > Auth > Show token > Copy. Every button 1 run repeats these steps at the top of its page |
| `APOLLO_API_KEY` | Apollo > Settings > Integrations > API keys |
| `INSTANTLY_API_KEY` | Instantly > Settings > Integrations > API keys (scopes: campaigns and leads) |
| `INSTANTLY_EMAILS_KEY` | A third Instantly key with the scope `emails:all`, used only by button 4 to send the forwards and person 1's reminder |
| `INSTANTLY_ACCOUNTS_KEY` | A second, read-only Instantly key with the scope `accounts:read`, used only by button 4's health check to read the mailboxes (`docs/instantly_accounts_key.md`) |
| `REPLY_FORWARD_TO` | Amodh's and Ariel's addresses only (4 Nov 2026), separated by a comma: clear yes or no replies are forwarded here |
| `ALERT_TO` | Amodh's address only: failure emails, every other reply and the daily list of replies that named someone else |
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

To run every check as if it were another day: `CHECK_DATE=2027-01-01T00:30:00+05:30 python -m pytest -q`,
or all the difficult days at once: `bash .github/scripts/date_checks.sh`.

## When the checks run, and the emails when something goes wrong (1 Nov 2026)

On 1 Nov 2026 three checks that assumed it was still October stopped every button. So:

- **The code is checked once, when it changes**, by "Code checks (automatic, nothing to press)": every
  check today, then again as if it were each of the difficult days (month ends, the new year and
  29 February, India and UK time). If both pass, that version is marked as checked (the branch
  `checked-code`).
- **The buttons use only checked code** (`.github/scripts/use_checked_code.sh`) and never run the checks
  themselves, so a date cannot stop them. If the newest change has not passed, a run uses the last
  checked version and says so on its page.
- **Emails ONLY to the GitHub secret ALERT_TO** (since 3 Nov 2026, never the daily summary list; without it nothing is emailed) (`outreach/alert.py`): when any button's run fails (which button, which
  steps failed, which had already done their work, and the link), when a code change fails the checks
  and is held back, and on the 25th of each month when button R's rehearsal of the start of next month
  finds something that would fail (an early warning; the summary email still goes out).
