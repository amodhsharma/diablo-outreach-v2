---
name: outreach-research
description: Run Diablo's distributor outreach research for the waiting jobs in the queue (research/queue.csv in amodhsharma/diablo-outreach-v2), one after another, up to 8 per run, saving one report and one JSON per job to the repo. Use for the scheduled run (every hour), and when someone asks to "run outreach research", "run the next job", or names a Location or job ID to research now.
---

# outreachResearch

You research the waiting jobs in the queue **one after another, up to 8 in one run** (agreed
22 Oct 2026), and the same goes for a scheduled run and a manual one. Each job is its own job:
one Location and one or more Channels, its own two files, its own commit and its own import
into HubSpot. For each job you are the **manager**: you research the Location once, send one
**helper** per Channel, merge their results, write the report and save the two files to GitHub.
Then you go straight on to the next waiting job. The scripts in `scripts/` do every mechanical
step; follow them exactly and do not edit the queue.

Work without asking questions: a scheduled run has nobody to answer. Write any
problem into the report and the final summary instead.

## Hard rules

- Only push to **amodhsharma/diablo-outreach-v2**. Never touch amodhsharma/diablo-outreach (version 1).
- Never edit `research/queue.csv`, `data/` or `config/`. GitHub updates them.
- Never use the Claude API or any API key. Never write people, emails or phone numbers anywhere.
- British English. No em dashes or en dashes. No Oxford commas.

## Step 1: get the repository

1. If the current folder (or a folder below it) already holds `skills/outreachResearch/SKILL.md`
   for diablo-outreach-v2, go to its top folder and run `git pull --rebase`.
2. Otherwise: `git clone https://github.com/amodhsharma/diablo-outreach-v2 && cd diablo-outreach-v2`.
3. Run every command below from that top folder.

## Step 1b: make sure no other run is working (once per run)

Scheduled run: `python3 skills/outreachResearch/scripts/run_lock.py take`
Manual run: `python3 skills/outreachResearch/scripts/run_lock.py take --manual`

If it prints `ANOTHER RUN IS WORKING`, stop at once: report that one line and save nothing. The
run that is working carries on through the list. Otherwise it prints `TAKEN`.

## Step 2: pick the next job and write the prompts (once per job)

Scheduled run (every hour):
`python3 skills/outreachResearch/scripts/prepare_run.py`

Manual run (someone asked in a chat or pressed Run now):
`python3 skills/outreachResearch/scripts/prepare_run.py --manual`
- For the **first** job only: if they named a Location, add `--location "Mumbai, India"`; if
  they named a job ID, add `--job J0003`. From the second job on, run it without them, so the
  run carries on with the oldest waiting job.

It skips the jobs this run has already finished. If it prints `NOTHING TO DO` or
`RUN LIMIT REACHED`, go to Step 7. Otherwise mark the job as the one being worked on:
`python3 skills/outreachResearch/scripts/run_lock.py job <job ID>`
Then read `work/plan.json`. Channels marked `on_hold` are not researched (another job
already covered them); the scripts record that, you do nothing for them.
If every Channel is on hold, go straight to Step 5.
If the plan lists `replaces`, this is a retry: only the Channels that failed last time run, and
the merge keeps the earlier run's finished Channels and removes the earlier files.

## Step 3: research, all at the same time

In **one message**, start every task below so they run in parallel:

- **Helpers:** for each Channel with `"status": "run"`, start one helper with the Agent tool
  (general-purpose). Its prompt is the full text of that Channel's `prompt_file`, followed by:
  "You are a helper in an outreachResearch run. Work in the folder <top folder>. Do exactly what
  the prompt says, save the file it names, run the check it gives until it prints PASSED (at most
  three tries) and reply in one line. Do not touch any other file and do not push to git."
- **You (manager):** do the Location research yourself: follow `work/location_prompt.md` and save
  `work/location.md`. Stay within its search limit.

If the Agent tool is not available, research the Channels yourself one after another, each
exactly as its prompt says, and add a warning line to `work/closing.md` later saying the
Channels ran one after another.

Wait until every helper has replied before Step 4. A helper that stops early (for example on a
usage limit) is fine: the merge marks that Channel as failed and the others carry on.

## Step 4: merge

`python3 skills/outreachResearch/scripts/finalise.py merge`

It prints each Channel's result, the Tier 1 companies and the check result.
- If the check FAILED, read the errors, fix the cause in the helper files in `work/` (never invent
  data; delete a bad company entry rather than guess) and run merge again. At most two fixes.
- If it still fails after two fixes, go to Step 5 anyway; the import job will reject the file and
  mark the job Failed with the reason.

## Step 5: closing analysis and report

1. Write `work/closing.md`: which three companies to approach first across all Channels and why,
   in three short bullets, using only the facts in the merged JSON. If no companies were found,
   write one line saying so. If the Agent tool was missing, add that warning here.
2. Run `python3 skills/outreachResearch/scripts/finalise.py report`.
3. If the check FAILED: fix what it names (for example shorten Market structure in
   `work/location.md` to 200 words or fewer) and run the report step again. At most two fixes.

## Step 6: save to GitHub (once per job)

```
python3 skills/outreachResearch/scripts/run_lock.py done <job ID>
git add -A research/
git commit -m "Research: <job ID> <Location>"
git pull --rebase
git push
```

The job is now saved for good, whatever happens to the rest of the run, and GitHub imports it
into HubSpot within a few minutes. Keep one line for the summary (Step 7): the job, Location,
companies found per Channel and any problem. Then go back to **Step 2** for the next job. Do not
carry the earlier job's research into the next one: each job starts from its own plan.

Only the two new files in `research/<date>/` (and, on a retry, the removal of the earlier two)
and `research/run_lock.json` should be in the commit. If the push is refused, try
`git pull --rebase` and `git push` once more; if it is still refused, say so plainly in the
summary (the files are lost when this session ends) and go to Step 7.

## Step 7: end of the run and summary

When Step 2 says `NOTHING TO DO` or `RUN LIMIT REACHED` (or a job could not be saved at all):
`python3 skills/outreachResearch/scripts/run_lock.py release`

Always release, also when something went wrong, so the next run is not held back. (A run that
ends without releasing is not stuck for ever: its lock goes stale after 2 hours.)

Finish with:
1. Whether this was a scheduled or a manual run, and how many jobs it finished.
2. One line per job: the job ID, Location and Channels, companies found per Channel, and any
   Channel on hold, failed or below the floor.
3. Where the files are (research/<date>/...), that GitHub imports each job into HubSpot, and
   whether jobs are still waiting (the next run carries on with them).
If the first Step 2 said `NOTHING TO DO`, the summary is one line: "Nothing waiting in the queue."

## What the files are

- Five versions of the prompts sit side by side (agreed 14 Oct 2026). `prompt_version` in
  `settings.yaml` picks one, and prepare_run.py writes the chosen version into `work/`:
  - version 5 (in use from 22 Oct 2026): `prompts/channel_prompt_5.md` and
    `prompts/channels/*_5.md`. Version 4 loosened after Ariel found it too strict: reject only on
    evidence, list a company that passes even when a detail such as the warehouse is not on its
    website (state it plainly, tier 3 if needed), sports shops (also sports equipment shops with
    healthy food), sports nutrition and fitness shops, online
    health shops, snack vending and petrol station chains count, closing-down companies are out,
    and the lessons from Ariel's review of the HubSpot companies (beeovita, Big Biceps, Barkat).
    Same `--catalogue` check as version 4;
  - version 4 (used from 21 Oct 2026, evening, to 22 Oct 2026): `prompts/channel_prompt_4.md` and
    `prompts/channels/*_4.md`. The final version after Ariel reviewed all 97 Swiss companies
    (J0001 to J0008): who Diablo wants, eleven hard rules for every channel (each channel template
    says how they apply to it), how to check each company step by step (website, About page, range,
    storage, then decide), the review's rejects and approved models grouped by reason, 50 as a
    maximum and firm rejection. Its check (`--catalogue`) also refuses a company without its own
    website, except for marketplace sellers;
  - version 3 (used on 21 Oct 2026): `prompts/channel_prompt_3.md` and `prompts/channels/*_3.md`.
    Version 2 plus Diablo's nine hard rules (no company selling its own products, own range or
    goods it makes; distributors and wholesalers need their own storage; it must already sell
    something from Diablo's catalogue; no pharmacy, packaging or drinks-only suppliers; no
    ingredients for professionals; no deli or single cuisine specialists; the website must open),
    the full catalogue and the lessons from Ariel's review of the Swiss research. Its check
    command adds `--catalogue`, which refuses a company whose "distributes" names nothing from
    the catalogue;
  - version 2: `prompts/channel_prompt_2.md` and `prompts/channels/*_2.md`. No agencies,
    importer directories and trade press as starting points (confirmed on the company's own
    website), ranking by fit, importers of European or UK brands first, 30 companies wanted;
  - version 1 (the originals, kept unchanged): `prompts/channel_prompt.md` and
    `prompts/channels/*.md`, 60 companies wanted.
- Each version has the four Channel templates (distributor, wholesaler, retailer, marketplace
  seller) plus `general` for a Channel that matches none. The `matches:` line says which typed
  words pick each template.
- `prompts/location_prompt.md`: market structure and barriers to entry, done once per Location.
- `output_format.md`: the JSON format, field by field.
- `settings.yaml`: companies wanted, floor and search limits.
- `scripts/`: run_lock.py (Steps 1b, 2, 6 and 8: one run at a time, the job being worked on and
  the jobs finished, in `research/run_lock.json`), prepare_run.py (Step 2), finalise.py (Steps 4
  and 5), check_output.py (the strict check, also used by GitHub before importing).
- `settings.yaml`: `max_jobs_per_run` (8) is the most jobs one run works through.
