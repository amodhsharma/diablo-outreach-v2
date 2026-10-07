# Diablo outreach pipeline (version 2)

Finds distributors, wholesalers, retailers and marketplace sellers in a Location, puts them in
HubSpot for approval, finds buyer contacts with Apollo and queues emails in Instantly.

Version 2 uses **no Claude API**. The research is done by Claude through the
**outreachResearch skill** (`skills/outreachResearch`), every day at 8 AM IST or as a manual
run. Everything else runs from buttons in the **Actions** tab. Keys live only in GitHub secrets.

Version 1 (amodhsharma/diablo-outreach) is kept as it is, for reference only.

## How a Location gets researched

1. Press **2a. Add research to the queue**: type the Location, the Channels (separated by
   commas), languages and companies wanted per Channel.
2. At 8 AM IST Claude takes the oldest waiting job, researches the Location once and sends one
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
| 3. Find contacts | For Approved companies: Apollo finds up to 10 verified buyer emails, most senior first |
| 4b. Send to Instantly | Adds Approved to send contacts to a paused campaign per Location and Channel |
| 5. Sync Instantly to HubSpot | Every 3 hours: Sent, Replied, Interested, Bounced and Opted out back to HubSpot |

Step 4a (writing each subject line and personal line) becomes its own Claude skill and is
switched on once its code is written. Until then no contact reaches *Copy ready*.

## The queue

`research/queue.csv` holds one line per Location and Channel, and lines are never deleted, so it
is also the record of everything covered. It opens on GitHub as a table. Statuses: Waiting,
On hold: already covered, Done, Done fewer than wanted, Failed, Cancelled.

- A repeat is the same Location with the same Channel. Capitals, spaces and singular or plural
  are ignored ("Wholesaler" matches "wholesalers"); any other wording is new.
- Locations match as written: "UK" and "United Kingdom" are different.
- A repeat goes On hold until someone presses **2d. Approve a repeat**.

## Where things are

| Path | What it is |
|---|---|
| `skills/outreachResearch/SKILL.md` | The steps Claude follows for every research run |
| `skills/outreachResearch/prompts/` | The research prompt, the Location prompt and the four Channel templates |
| `skills/outreachResearch/settings.yaml` | Companies wanted, floor and search limits |
| `skills/outreachResearch/output_format.md` | The JSON format and what the strict check rejects |
| `research/<date>/` | Each run's report (`_report.md`) and JSON |
| `data/known_companies.csv` | Companies already in HubSpot (nightly) |
| `data/company_notes.json` | What each company distributes and why it fits, for email writing |
| `config/exclude.txt` | Companies that must never be researched or contacted |
| `config/settings.yaml` | Contacts, salesperson assignment, sending and sync settings |
| `templates/` | The first email and the reminder |

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
