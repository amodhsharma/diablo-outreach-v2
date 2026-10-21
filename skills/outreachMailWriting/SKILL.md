---
name: outreach-mail-writing
description: Write the personal line (one of four styles) for Diablo outreach contacts waiting for them (mail/pending.json in amodhsharma/diablo-outreach-v2) and save one lines file to the repo, which GitHub imports into HubSpot as "New, Personal line filled". Use for the scheduled run (every 3 hours), and when someone asks to "write the email lines", "run outreach mail writing" or "write lines for the new contacts".
---

# outreach-mail-writing

You write two short pieces of text for each contact that needs them (from 15 Oct 2026): the
**company note**, which finishes "we noticed <company> ..." in the first email (template 3), and a
**personal line**, used when the email is forwarded to a colleague. Each contact is given one of four styles at random
(agreed 14 Oct 2026); you fill that style's [brackets] from the company's research. The rest of the
email, the subject line included, is a fixed template. The scripts in `scripts/` do every
mechanical step; follow them exactly.

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

Scheduled run (every 3 hours): `python3 skills/outreachMailWriting/scripts/prepare_lines.py`

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
   as "New, Personal line filled", ready for gate 2.

## What the files are

- `prompts/lines_prompt_8.md` (in use from 21 Oct 2026): as lines_prompt_7.md, plus when the research
  shows a company focuses on vegan products, its note names its vegan sweets or snacks and ends with
  ", and several of ours are vegan too" (for example "distributes vegan snacks and sweets, and several
  of ours are vegan too"). The check allows "ours" only in that exact ending.
- `prompts/lines_prompt_7.md` (used from 20 Oct 2026, later the same day): as lines_prompt_6.md,
  plus the note must read like a person wrote it: what they sell and to which kind of shop, never
  their premises or format (cash and carry, depot, warehouse) or vague buyers ("trade customers",
  "food retail"). Wrong: "stocks confectionery in its cash and carry for small retailers".
- `prompts/lines_prompt_6.md` (used on 20 Oct 2026): the company note always names our range
  (sweets, chocolate, confectionery, biscuits, snacks or sugar free products); when the research
  shows nothing specific it is the fixed note "is in the distribution space for confectionery
  products" (or "sugar free products"; retailers: "is in the retail space for ..."). The check refuses
  any other note without those words.
- `prompts/lines_prompt_5.md` (used on 19 Oct 2026): the same as lines_prompt_4.md, plus the rule
  that we do not sell ingredients: the note never names bakeries, bakers, canteens, kitchens or other
  food makers as customers, and never says "grocery products".
- `prompts/lines_prompt_4.md` (used until 19 Oct 2026): the company note (4 to 12 words, always about
  sweets, snacks or the shops where they sell; never organic, catering, non-food and the like; no
  places or numbers) and the personal line with its four styles. `prompts/lines_prompt_3.md`,
  `prompts/lines_prompt_2.md` and `prompts/lines_prompt.md` are the earlier versions, kept unchanged
  and not used.
- `settings.yaml`: how many contacts one run writes for.
- `scripts/`: prepare_lines.py (Step 2, also picks each contact's style), finalise_lines.py (Step 4),
  check_lines.py (the strict check and the four styles, also used by GitHub before importing).
