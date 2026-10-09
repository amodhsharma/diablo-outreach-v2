# Instantly health check

Checked 2026-10-09T09:04:02+00:00 (UTC).

## Mailboxes

- Could not be read. If the message mentions permission or scope, the Instantly key needs read access to accounts. Instantly said: GET /accounts failed with 401: {"statusCode":401,"error":"Unauthorized","message":"Invalid scope. Required: accounts:read. Found: campaigns:all, leads:all"}

## Campaign: Diablo | Dublin, Ireland | Retailers | OCT2026

- Campaign status: Completed
- Instantly says: **campaign_completed**. Campaign has completed
- schedule_status: `{"in_schedule": true}`
- campaign_daily_limit: `{"limit": 30, "sent": 0, "limit_hit": false}`
- new_lead_limit: `{"enabled": false, "limit": null, "contacted": 0, "limit_hit": false}`
- accounts_summary: `{"total_connected": 1, "available": 1, "unavailable": {"daily_limit_hit": 0, "slow_ramp_limit_hit": 0, "disconnected": 0, "global_gap_not_met": 0}}`
- leads_status: `{"no_leads_ready": true, "account_unavailable_skips": 0, "delay_not_met_skips": 0}`
- follow_ups_waiting: `{"count": 0, "earliest_wait_time_seconds": null}`
- issue_tracking: `{"current_status_code": "waiting_for_leads", "issue_first_seen_at": "2026-10-08T09:07:46.825Z", "consecutive_loops_with_issue": 1, "last_healthy_send_at": null}`
- Mailboxes it sends from: sales@diablosnosugar.com
- Leads: 0
- Emails in the sequence: 2 (characters in each body: [726, 545])

## Campaign: Diablo | OCT2026

- Campaign status: Active
- Instantly says: **follow_up_delay_not_met**. Follow-up delays have not been met yet
- Instantly's explanation: Your campaign is currently waiting to send follow-up emails. It has 4 follow-ups scheduled, but they are not yet ready to be sent as their defined waiting periods have not passed. No action is required; the campaign will automatically resume sending once these delays are met.
- schedule_status: `{"in_schedule": true}`
- campaign_daily_limit: `{"limit": 30, "sent": 0, "limit_hit": false}`
- new_lead_limit: `{"enabled": false, "limit": null, "contacted": 0, "limit_hit": false}`
- accounts_summary: `{"total_connected": 1, "available": 1, "unavailable": {"daily_limit_hit": 0, "slow_ramp_limit_hit": 0, "disconnected": 0, "global_gap_not_met": 0}}`
- leads_status: `{"no_leads_ready": true, "account_unavailable_skips": 0, "delay_not_met_skips": 4}`
- follow_ups_waiting: `{"count": 4, "earliest_wait_time_seconds": null}`
- issue_tracking: `{"current_status_code": "follow_up_delay_not_met", "issue_first_seen_at": "2026-10-09T09:02:56.289Z", "consecutive_loops_with_issue": 1, "last_healthy_send_at": null}`
- Mailboxes it sends from: sales@diablosnosugar.com
- Leads: 4
  - 2 Completed, emailed, replied
  - 2 Completed, emailed
- Emails in the sequence: 2 (characters in each body: [726, 545])


## Approved to send in HubSpot (what 4b would do now)

- 0 contacts approved to send
