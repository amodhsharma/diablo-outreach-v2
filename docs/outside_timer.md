# Outside timer: pressing the GitHub buttons on time

GitHub's own timer is best effort: on 7 and 8 Oct 2026 it ran "4b. Send to Instantly" twice
overnight instead of about seven times, and "5. Sync" three times instead of five. So a free
outside timer, cron-job.org, presses those buttons on time through the GitHub API (agreed with
Ariel on 8 Oct 2026).

**One rhythm for all three (agreed 8 Oct 2026):** the timer presses one button every hour, in
turn, so each button runs 8 times a day, every 3 hours:

| Time (IST) | Button |
|---|---|
| 12, 3, 6 and 9, AM and PM | 4b. Send to Instantly |
| 1, 4, 7 and 10, AM and PM | 5. Sync Instantly to HubSpot |
| 2, 5, 8 and 11, AM and PM | 2f. Save the HubSpot company list |

Send comes first, so the sync an hour later already sees the emails that went out. GitHub's
own timer stays on only until the three jobs below pass their test run; after that it is
switched off, so there is one timer to manage.

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

## Step 2: set up cron-job.org (about 10 minutes)

1. Sign up for a free account at https://cron-job.org.
2. In **Settings**, set the time zone to **Asia/Kolkata**.
3. Create the three jobs below with **Create cronjob**. For each one, in the **Advanced** tab:
   - **Request method:** POST
   - **Headers** (four of them):
     - `Accept` = `application/vnd.github+json`
     - `Authorization` = `Bearer ` followed by the key from step 1 (one space after Bearer)
     - `X-GitHub-Api-Version` = `2022-11-28`
     - `Content-Type` = `application/json`
   - **Request body:** as shown for each job
   - **Notifications:** tick "notify me when an execution fails"

| Job title | URL | Schedule | Request body |
|---|---|---|---|
| Diablo 4b Send to Instantly | `https://api.github.com/repos/amodhsharma/diablo-outreach-v2/actions/workflows/send.yml/dispatches` | Every 3 hours from midnight, on the hour: 0, 3, 6, 9, 12, 15, 18, 21 | `{"ref":"main","inputs":{"target":"auto","dry_run":false}}` |
| Diablo 5 Sync | `https://api.github.com/repos/amodhsharma/diablo-outreach-v2/actions/workflows/sync.yml/dispatches` | Every 3 hours from 1 AM, on the hour: 1, 4, 7, 10, 13, 16, 19, 22 | `{"ref":"main"}` |
| Diablo 2f Company list | `https://api.github.com/repos/amodhsharma/diablo-outreach-v2/actions/workflows/known-companies.yml/dispatches` | Every 3 hours from 2 AM, on the hour: 2, 5, 8, 11, 14, 17, 20, 23 | `{"ref":"main"}` |

4. Use **Test run** on each job. A good answer is **204 No Content**, and a new run appears in
   the repository's **Actions** tab within a minute. A 401 or 403 means the key was copied
   wrongly or is missing "Actions: Read and write"; a 404 means the URL has a typo.

`"target":"auto"` sends to the HubSpot account in the repository variable PIPELINE_TARGET
(test until it is set to live), so the timer needs no change when going live.

## Renewing or stopping

- **Renewing:** before the key expires, make a new one (step 1) and paste it into the three
  jobs' Authorization headers, then delete the old key.
- **Pausing everything:** switch the jobs off in cron-job.org. GitHub's own backup timer keeps
  running unless it is also turned off.
