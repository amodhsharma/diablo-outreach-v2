# Read-only Instantly key for the mailbox health check

Button 6 ("6 - Manual - Health check: mailboxes, campaigns and why someone isn't being
emailed") lists every sending mailbox in Instantly. The main Instantly key
(`INSTANTLY_API_KEY`) can only manage campaigns and leads, so it cannot read mailboxes. Rather
than give the sending key more access, button 6 uses a second key that can only read mailboxes.

## Steps (about 3 minutes)

1. In Instantly: **Settings**, **Integrations**, **API keys**, **Create API key**.
2. Name: `Diablo health check (read only)`.
3. Scopes: tick only **accounts:read** (it may be shown as Accounts, Read). Nothing else.
4. Create it and copy the key. Do not paste it into a chat, an email or a document.
5. In GitHub, in the diablo-outreach-v2 repository: **Settings**, **Secrets and variables**,
   **Actions**, **New repository secret**. Name `INSTANTLY_ACCOUNTS_KEY`, paste the key, save.
6. Press button 6. The **Mailboxes** section now lists every mailbox.

What this key can do: see the mailboxes and their warm-up numbers. What it cannot do: send,
change a mailbox, or see campaigns or leads. To cut it off, delete it on the same Instantly page.
Leave the existing `INSTANTLY_API_KEY` as it is: 4b and 5 keep using it.
