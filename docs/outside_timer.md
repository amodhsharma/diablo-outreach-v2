# Outside timer: pressing the GitHub buttons on time

GitHub's own timer is best effort (on 7 and 8 Oct 2026 it skipped most of its runs), so a free
outside timer, cron-job.org, presses the buttons on time through the GitHub API (agreed with Ariel
on 8 Oct 2026). Three jobs, one button each, every 3 hours, one hour apart (set 14 Oct 2026):

| Time (Asia/Kolkata) | Job | Button |
|---|---|---|
| 12, 3, 6 and 9, AM and PM | Diablo NEW 3 Outreach | 3 - Find contacts |
| 1, 4, 7 and 10, AM and PM | Diablo NEW 4 Send | 4 - Send and follow up |
| 2, 5, 8 and 11, AM and PM | Diablo NEW 2 Research | 2 - Research ("Automatic run") |

Claude's two scheduled tasks fit in between: personal lines 28 minutes after button 3, research 28
minutes after button 2.

The timer uses one GitHub key. This is the one key that does not live in GitHub's secrets:
cron-job.org has to hold it to press the buttons. It is limited so that it can only start the
buttons of this one repository.

## Step 1: make the GitHub key (about 3 minutes)

Do this signed in to the GitHub account that owns the repository (amodhsharma).

1. Click your profile picture (top right), then **Settings**.
2. At the bottom of the left menu: **Developer settings**, then **Personal access tokens**,
   then **Fine-grained tokens**, then **Generate new token**.
3. Fill in:
   - **Token name:** Outreach timer
   - **Expiration:** Custom, one year from today (put a reminder in your calendar to renew it)
   - **Resource owner:** amodhsharma
   - **Repository access:** Only select repositories, then pick **diablo-outreach-v2**
   - **Permissions, Repository permissions:** **Actions: Read and write**. Leave everything
     else as it is (GitHub adds "Metadata: Read-only" by itself).
4. Click **Generate token** and copy it. GitHub shows it only once. Do not paste it into a chat,
   an email or a document: it goes straight into cron-job.org in step 2.

What this key can do: start the GitHub buttons of diablo-outreach-v2 and see their runs.
What it cannot do: read or change the code, see the HubSpot, Apollo or Instantly keys, or
touch any other repository. To cut it off at any time, delete it on the same GitHub page.

## Step 2: the three jobs in cron-job.org

In **Settings**, the time zone is **Asia/Kolkata**. For each job: **Create cronjob**, then

- **Common tab:** the title and URL below; **Enable job** on; **Execution schedule: Custom**, with
  the crontab below (or tick the same hours, minute 0, every day of month, week and month).
- **Advanced tab:** time zone **Asia/Kolkata**; request method **POST**; four headers:
  - `Accept` = `application/vnd.github+json`
  - `Authorization` = `Bearer ` followed by the key from step 1 (one space after Bearer)
  - `X-GitHub-Api-Version` = `2022-11-28`
  - `Content-Type` = `application/json`
- the request body below, and tick "notify me when an execution fails".

| Job title | URL | Crontab | Request body |
|---|---|---|---|
| Diablo NEW 3 Outreach | `https://api.github.com/repos/amodhsharma/diablo-outreach-v2/actions/workflows/outreach.yml/dispatches` | `0 0,3,6,9,12,15,18,21 * * *` | `{"ref":"main","inputs":{"check_only":"false"}}` |
| Diablo NEW 4 Send | `https://api.github.com/repos/amodhsharma/diablo-outreach-v2/actions/workflows/send-loop.yml/dispatches` | `0 1,4,7,10,13,16,19,22 * * *` | `{"ref":"main"}` |
| Diablo NEW 2 Research | `https://api.github.com/repos/amodhsharma/diablo-outreach-v2/actions/workflows/research.yml/dispatches` | `0 2,5,8,11,14,17,20,23 * * *` | `{"ref":"main","inputs":{"action":"Automatic run"}}` |

Button 4's body has no inputs since 26 Oct 2026: its "Check only" box became a dropdown, and a run
started without one does the usual run (results and send), with no health check.

Use **Test run** on each job. A good answer is **204 No Content**, and a new run appears in the
repository's **Actions** tab within a minute. A 401 or 403 means the key was copied wrongly or
is missing "Actions: Read and write"; a 404 means the URL has a typo (or the button was removed);
a 422 means the request body does not match.

The old jobs (Diablo 4b, 5 and 2f) press buttons that were removed on 14 Oct 2026. Keep them
paused, or delete them. Going back to the earlier version would mean restoring the branch
`v2-before-revamp`, after which they would work again.

## Renewing or stopping

- **Renewing:** before the key expires, make a new one (step 1) and paste it into the three
  jobs' Authorization headers, then delete the old key.
- **Pausing everything:** switch the jobs off in cron-job.org ("Enable job" off on each job's
  page). Nothing else presses these buttons by itself, except Claude saving research or lines,
  which starts buttons 2 and 3 for those files only.
