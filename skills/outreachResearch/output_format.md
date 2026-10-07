# outreachResearch output format

Each run saves two files in `research/<date>/`, named `<job ID>_<date>_<location>_<channels>`,
for example `J0001_2026-10-09_mumbai-india_distributors-retailers.json`:

- `.json`: read by GitHub to add the companies to HubSpot.
- `_report.md`: the readable report for the team.

`scripts/check_output.py` checks both before they are saved, and GitHub checks the JSON
again before importing. A file that fails is rejected whole; nothing half reaches HubSpot.

## The JSON file

| Field | Meaning |
|---|---|
| format | Always "outreachResearch v1" |
| job_id | The queue job, e.g. J0001 |
| location | The Location as queued, e.g. "Mumbai, India" |
| run_date | The run's date in India time, e.g. 2026-10-09 |
| run_type | scheduled (every 6 hours) or manual |
| replaces | On a retry, the earlier files this run replaces (empty otherwise) |
| channels | One entry per Channel in the job (below) |
| companies | One entry per company (below), each company once |

**Each Channel:** channel, template, status (done, failed or on_hold), reason (why failed or
on hold), companies_wanted, companies_found, searches_used.

**Each company (13 fields):**

| Field | Shown to people as | Rule |
|---|---|---|
| name | Company name | Not empty |
| based_out_of | Based out of | City and country of its head office, e.g. "Pune, India", or null |
| domain | Domain of the found company | Written like abc.com (no https://, www or page), or "no domain" |
| channel_category | Channel | The Channel(s) it was found under; the first is its main Channel |
| tier | Tier | 1, 2 or 3 |
| tier_rank | Rank within the tier | 1, 2, 3... within its main Channel and tier |
| distributes | What they distribute | Text or null |
| channels_supplied | Retailers or channels they supply | Text or null |
| sf_brands_carried | Sugar free brands carried | Text or null |
| competing_brand_flag | Carries a direct competitor | true, false or null |
| fit_rationale | Why they fit Diablo | Not empty |
| confidence | Confidence | high, medium or low |
| source_urls | Found the company from | At least one web link |

## What the strict check rejects

- Missing or extra fields, or a value of the wrong kind.
- A domain not written plainly, or a directory, marketplace or social page used as a domain.
- A company without a "Found the company from" link.
- The same company twice, or a company on the exclusion list.
- Two companies with the same Tier and Rank in one Channel.
- Email addresses, phone numbers, em dashes or en dashes in any field.
- A report whose company lists do not match the JSON, whose Market structure is over 200 words,
  or with a section missing.

## When a Channel fails

A failed Channel goes back to Waiting once and runs again by itself at the next run (retries go
before other jobs). The retry keeps the earlier run's finished Channels, researches only the
failed ones and replaces the earlier two files with one new pair. If it fails again it is marked
Failed until someone presses "Retry a failed job". If a run stops without saving anything, the
job simply stays Waiting and runs at the next run.
