---
name: outreach-research
description: Run Diablo's distributor outreach research for the next job in the queue (research/queue.csv in amodhsharma/diablo-outreach-v2) and save one report and one JSON to the repo. Use for the scheduled run (every 6 hours), and when someone asks to "run outreach research", "run the next job", or names a Location or job ID to research now.
---

# outreachResearch

You research one job from the queue: one Location and one or more Channels. You are
the **manager**: you research the Location once, send one **helper** per Channel, merge
their results, write the report and save two files to GitHub. The scripts in `scripts/`
do every mechanical step; follow them exactly and do not edit the queue.

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

## Step 2: pick the job and write the prompts

Scheduled run (every 6 hours):
`python3 skills/outreachResearch/scripts/prepare_run.py`

Manual run (someone asked in a chat or pressed Run now):
`python3 skills/outreachResearch/scripts/prepare_run.py --manual`
- If they named a Location: add `--location "Mumbai, India"`.
- If they named a job ID: add `--job J0003`.

If it prints `NOTHING TO DO`, stop: report "Nothing waiting in the queue today" and save nothing.
Otherwise read `work/plan.json`. Channels marked `on_hold` are not researched (another job
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

## Step 6: save to GitHub

```
git add -A research/
git commit -m "Research: <job ID> <Location>"
git pull --rebase
git push
```

Only the two new files in `research/<date>/` (and, on a retry, the removal of the earlier two)
should be in the commit. If the push is refused,
say so plainly in the summary; the files are lost when this session ends.

## Step 7: summary

Finish with three lines:
1. The job, Location and Channels, and whether this was a scheduled run or a manual run.
2. Companies found per Channel, and any Channel on hold, failed or below the floor.
3. Where the files are (research/<date>/...) and that GitHub will now import them into HubSpot.

## What the files are

- `prompts/channel_prompt.md`: the research prompt (Ariel's), one per Channel.
- `prompts/channels/*.md`: the four Channel templates (distributor, wholesaler, retailer,
  marketplace seller) plus `general.md` for a Channel that matches none. The `matches:` line says
  which typed words pick each template.
- `prompts/location_prompt.md`: market structure and barriers to entry, done once per Location.
- `output_format.md`: the JSON format, field by field.
- `settings.yaml`: companies wanted, floor and search limits.
- `scripts/`: prepare_run.py (Step 2), finalise.py (Steps 4 and 5), check_output.py (the strict
  check, also used by GitHub before importing).
