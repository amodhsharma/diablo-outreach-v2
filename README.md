# Diablo outreach pipeline (version 2)

Finds distributors, wholesalers, retailers and marketplace sellers in a Location, puts them in
HubSpot for approval, finds buyer contacts with Apollo and queues emails in Instantly.

Version 2 uses **no Claude API**. The research is done by Claude through the
**outreachResearch skill** (`skills/outreachResearch`), every 6 hours (about 2 AM, 8 AM, 2 PM and 8 PM IST) or as a manual
run. The subject line and personal opening for each contact are written by Claude through the
**outreach-mail-writing skill** (`skills/outreachMailWriting`), every 2 hours or as a manual run. Everything else runs from buttons in the **Actions** tab. Keys live only in GitHub secrets.

Version 1 (amodhsharma/diablo-outreach) is kept as it is, for reference only.

## How a Location gets researched

1. Press **2a. Add research to the queue**: type the Location, the Channels (separated by
   commas), languages and companies wanted per Channel.
2. Every 6 hours Claude takes the oldest waiting job (one job per run), researches the Location once and sends one
   helper per Channel at the same time, then saves one report and one JSON to `research/<date>/`.
   A manual run does the same at any time: "Run now" on the scheduled task, or `/outreach-research`
   in a Claude chat (name a Location or job ID to run that one).
3. **2e. Import research into HubSpot** starts by itself, checks the file again and adds the
   companies to HubSpot as *Awaiting review*. The queue line is marked Done.

You approve work in HubSpot by changing one dropdown:

- **Gate 1**: company field *Outreach company status*: `Awaiting review` to `Approved` or `Rejected`.
- **Gate 2**: contact field *Outreach contact status*: `Copy ready` to `Approved to send`.
- *Outreach suppress reason* on a company stops all outreach to it.

## The buttons

| Button | What it does |
|---|---|
| 1. Set up HubSpot fields | Creates the 17 Diablo outreach fields (once per account) |
| 2a. Add research to the queue | Adds a job: one Location, one or more Channels |
| 2b. Cancel a waiting job | Stops a Waiting or On hold job (or one Channel of it) |
| 2c. Retry a failed job | Puts a Failed job (or one Channel of it) back to Waiting |
| 2d. Approve a repeat | Lets an On hold repeat run |
| 2e. Import research into HubSpot | Runs by itself when new research is saved; can be pressed by hand |
| 2f. Save the HubSpot company list | Runs every night; saves the companies already in HubSpot so research skips them |
| 3. Find contacts | For Approved companies: Apollo finds the top 3 verified buyer emails, most senior first. Run it again on a company set back to Approved to get the next 3 (nobody is paid for twice) |
| 4a. Refresh contacts needing email lines | Saves the Contact found contacts to `mail/pending.json` for the writing skill. Runs by itself after 3 and 4c; press it after editing contacts in HubSpot |
| 4c. Import email lines into HubSpot | Runs by itself when new lines are saved: puts them on the contacts and moves them to Copy ready |
| 4b. Send to Instantly | Every hour by itself (or pressed by hand): starts each company with its most senior Approved to send contact. A new Location and Channel gets a paused campaign; press Start on it in Instantly once |
| 5. Sync Instantly to HubSpot | Every 3 hours: Sent, Replied, Interested, Bounced and Opted out back to HubSpot, and moves companies on to their next person |

## How the email lines get written

1. **3. Find contacts** saves the new contacts (job title and company research only, no names or
   emails) to `mail/pending.json`.
2. Every 2 hours Claude runs the outreach-mail-writing skill: it writes a subject line and a
   personal opening for up to 60 contacts, checks them and saves one file to `mail/lines/<date>/`.
   A manual run does the same at any time: `/outreach-mail-writing` in a Claude chat.
3. **4c. Import email lines into HubSpot** starts by itself, checks the file again and puts the
   lines on each contact as *Copy ready*. Gate 2 is yours: read them and change the status to
   *Approved to send*. To change a line, edit it in HubSpot before approving.

## One person per company at a time

- The most senior approved contact gets the first email, and a reminder 3 days later if they have not replied.
- On day 4 with no reply from anyone at the company, the next person in line gets their own email
  (the sync job does this by itself). Each person must still be approved at gate 2.
- The moment anyone at the company replies, nobody else there is emailed.
- When everyone found has been emailed without a reply, the company becomes **No reply**. To go
  deeper, set it back to **Approved** and press **3. Find contacts** for the next 3.

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
- A repeat goes On hold until someone presses **2d. Approve a repeat**.
- A failed Channel runs again by itself once, at the next run, and the new files replace the
  earlier ones. If it fails again it is marked Failed until someone presses **2c. Retry a failed job**.

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
| `HUBSPOT_TOKEN_TEST` | Outreach Test account > Development > Legacy apps > the private app |
| `APOLLO_API_KEY` | Apollo > Settings > Integrations > API keys |
| `INSTANTLY_API_KEY` | Instantly > Settings > Integrations > API keys |
| `HUBSPOT_TOKEN_LIVE` | Only when testing is finished |

To use the live HubSpot account for the automatic jobs, add a repository variable
`PIPELINE_TARGET` = `live` (Settings > Secrets and variables > Actions > Variables).

## Safety built in

- The strict check runs twice: in Claude before saving and in GitHub before importing. A file
  that fails is rejected whole and the job is marked Failed with the reason.
- Every job checks which HubSpot account the key belongs to and stops on a mismatch.
- Nothing is sent without both gates; Instantly campaigns are created paused.
- Companies already in HubSpot are never added again; Apollo spend stops at the credit cap.

## Running the tests

```
pip install -r requirements.txt
python -m pytest -q
```
