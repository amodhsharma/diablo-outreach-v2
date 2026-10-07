---
name: outreach-mail-writing
description: Write the personalised subject line and opening line for Diablo outreach contacts waiting for them (mail/pending.json in amodhsharma/diablo-outreach-v2) and save one lines file to the repo, which GitHub imports into HubSpot as Copy ready. Use for the scheduled run (every 2 hours), and when someone asks to "write the email lines", "run outreach mail writing" or "write lines for the new contacts".
---

# outreach-mail-writing

You write two short pieces of text for each contact that needs them: a **subject line** and a
**personal opening line**. The rest of the email is a fixed template. The scripts in `scripts/` do
every mechanical step; follow them exactly.

Work without asking questions: a scheduled run has nobody to answer. Write any problem into the
final summary instead.

## Hard rules

- Only push to **amodhsharma/diablo-outreach-v2**. Never touch amodhsharma/diablo-outreach (version 1).
- Never edit `mail/pending.json`, `mail/imported.txt`, `research/`, `data/` or `config/`. GitHub updates them.
- Never use the Claude API or any API key. Never write names, emails or phone numbers anywhere.
- Never search the web for this task: use only the facts in the batch.
- British English. No em dashes or en dashes. No Oxford commas.

## Step 1: get the repository

1. If the current folder (or a folder below it) already holds `skills/outreachMailWriting/SKILL.md`
   for diablo-outreach-v2, go to its top folder and run `git pull --rebase`.
2. Otherwise: `git clone https://github.com/amodhsharma/diablo-outreach-v2 && cd diablo-outreach-v2`.
3. Run every command below from that top folder.

## Step 2: pick the contacts

Scheduled run (every 2 hours): `python3 skills/outreachMailWriting/scripts/prepare_lines.py`

Manual run (someone asked in a chat): `python3 skills/outreachMailWriting/scripts/prepare_lines.py --manual`

If it prints `NOTHING TO DO`, stop: report that line and save nothing.

## Step 3: write the lines

Read `work_mail/prompt.md` in full and do exactly what it says. Write every contact's lines
yourself (no helpers are needed) and save `work_mail/draft.json`.

## Step 4: check and save

`python3 skills/outreachMailWriting/scripts/finalise_lines.py`

- If it prints FAILED, rewrite only the lines it names in `work_mail/draft.json` and run it again.
  At most two fixes.
- If it still fails, run it with `--drop-failing`: the lines that pass are saved and the others
  stay on the list for the next run.

## Step 5: save to GitHub

```
git add mail/lines/
git commit -m "Email lines: <number> contacts"
git pull --rebase
git push
```

Only the one new file in `mail/lines/<date>/` should be in the commit. If the push is refused, say
so plainly in the summary; the file is lost when this session ends.

## Step 6: summary

Finish with three lines:
1. Scheduled or manual run, and how many contacts got lines (and how many wait for the next run).
2. Any contact left out and why.
3. Where the file is (mail/lines/<date>/...) and that GitHub will now put the lines into HubSpot
   as Copy ready, ready for gate 2.

## What the files are

- `prompts/lines_prompt.md`: the writing rules, agreed in `templates/email_templates_for_approval.md`.
- `settings.yaml`: how many contacts one run writes for.
- `scripts/`: prepare_lines.py (Step 2), finalise_lines.py (Step 4), check_lines.py (the strict
  check, also used by GitHub before importing).
