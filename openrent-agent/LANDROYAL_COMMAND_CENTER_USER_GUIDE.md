# Land Royal Command Center

## Client User Guide

The Land Royal Command Center is used to configure property searches, monitor automated outreach, review landlord conversations, and manage account health.

> **Dashboard URL:** Use the secure dashboard link provided by your administrator.

## Quick Start

For a new setup, complete these steps in order:

1. Add and enable a proxy in **Proxies**.
2. Add the required search areas in **Locations**.
3. Add an OpenRent account in **Accounts** and assign its proxy.
4. Create at least one search profile for the account in **Search Profiles**.
5. Test the account's proxy and refresh its session.
6. Start or resume the account worker.
7. Monitor activity from **Dashboard**, **Leads**, and **Workers**.

## Navigation

Use the left sidebar to move between sections.

On mobile, tap the sidebar button in the top-left corner. The sidebar closes automatically after selecting a page.

The top bar shows:

- The current backend connection status.
- A shortcut for searching leads.
- A light/dark theme button.

## Dashboard

The **Dashboard** provides a summary of current performance and system health.

Use it to review:

- Reply rate.
- Phone numbers collected.
- Active conversations.
- Conversations needing attention.
- Active, queued, and available workers.
- Healthy and failed proxies.
- Recent landlord conversations.
- Failed account warnings.

The dashboard updates automatically. Use the recent activity filters to focus on active conversations, conversations needing attention, or leads with phone numbers.

## Recommended Daily Workflow

1. Open **Dashboard** and check for warnings.
2. Review **Failed Accounts** and **Needs attention**.
3. Open **Workers** and confirm workers are running without errors.
4. Open **Leads** and review new replies, phone numbers, and viewings.
5. Open any important conversation and check the full message history.
6. Check **Logs** if an account, worker, or conversation has failed.

## Leads and Conversations

The **Leads** page shows landlord conversations discovered and managed by the system.

### Filtering Leads

Use the controls at the top of the page to filter by:

- Search text, including thread, location, or property.
- Conversation status.
- OpenRent account.
- Search profile.
- Leads with phone numbers.
- AI failures.
- Active conversations.
- Conversations with viewings.

### Opening a Conversation

Select a thread number or use the three-dot menu and choose **Open thread**.

The conversation page shows:

- The real persisted conversation history.
- Lead status and conversation stage.
- Property and account information.
- Extracted phone number, when available.
- Account persona details.
- A timeline of important activity.

Conversation history refreshes automatically. Landlord messages appear on the left, and successfully sent account messages appear on the right.

Generated messages that failed to send are not displayed as successfully sent messages.

### Conversation Actions

- **Back:** Return to the Leads list.
- **Open property:** Open the original property listing.
- **Complete:** Mark the conversation as complete.
- **Invalid:** Mark the lead as invalid.
- **Copy phone:** Copy an extracted phone number.
- **Mark resolved:** Mark a conversation as resolved from the Leads table.

Only mark a conversation complete or invalid after confirming that no further automated action is required.

## Accounts

The **Accounts** page manages OpenRent accounts and their automation settings.

Each account displays:

- Session and worker status.
- Daily message usage.
- Last and next run times.
- Assigned proxy and proxy health.
- Persona and conversation settings.
- Whether the account is active.

### Adding an Account

1. Open **Accounts**.
2. Select **Add Account**.
3. Enter the account email and OpenRent password.
4. Set a suitable daily message limit.
5. Assign an active proxy.
6. Enter the mobile number used by the account persona, if required.
7. Select the phone strategy and conversation style.
8. Set the initial message.
9. Select **Create**.

Do not share account credentials outside the authorized team.

### Account Controls

Use the three-dot menu beside an account:

- **Start worker:** Start an automation run.
- **Stop worker:** Stop the current worker.
- **Pause account:** Prevent future automated runs.
- **Resume account:** Allow automated runs again.
- **Test proxy:** Confirm that the assigned proxy is working.
- **Refresh session:** Queue a login/session refresh.
- **Invalidate session:** Remove the saved session so the account must authenticate again.
- **Edit account:** Change account configuration.
- **Delete account:** Permanently remove the account and its related data.

> **Caution:** Use **Invalidate session** only when login/session recovery is required. Use **Delete account** only after confirming that its related data is no longer needed.

## Workers

The **Workers** page shows the live automation process for every account.

Review:

- Worker status.
- Current processing phase.
- Latest heartbeat.
- Queue job and retry information.
- Last error.
- Available worker capacity.

### Worker Status Guide

- **Running:** The account is currently being processed.
- **Queued:** The account is waiting for an available worker slot.
- **Idle / Completed / Stopped:** The account is not currently processing.
- **Paused:** Automation is disabled for the account.
- **Retrying:** The system will retry after a temporary failure.
- **Proxy error:** The assigned proxy needs attention.
- **Login error:** The account session or credentials need attention.
- **Error:** Review the worker's last error and the Logs page.

Use the controls on the right to start, stop, pause, or resume a worker.

## Proxies

The **Proxies** page manages the shared proxy pool used by OpenRent accounts.

### Adding a Proxy

1. Open **Proxies**.
2. Select **Add Proxy**.
3. Enter the host, port, username, and password supplied by the proxy provider.
4. Leave **Active** enabled.
5. Select **Create**.

After adding a proxy, assign it to an account from the **Accounts** page and run **Test proxy**.

Do not disable or delete a proxy that is assigned to an active account. A proxy assigned to accounts cannot be deleted until those accounts are reassigned.

## Locations

The **Locations** page defines the OpenRent areas available for search profiles.

To add a location:

1. Select **Add Location**.
2. Enter a clear display name.
3. Enter the exact OpenRent location search term.
4. Keep the location active.
5. Select **Create**.

Disabling a location prevents it from being selected for new search activity.

## Search Profiles

The **Search Profiles** page defines what each account searches for.

To create a profile:

1. Select **Add Profile**.
2. Select the OpenRent account.
3. Select an active location.
4. Enter the search radius.
5. Enter minimum and maximum prices.
6. Enter minimum and maximum bedrooms.
7. Enable **Pets allowed** only when required.
8. Select **Create**.

Use the active switch to temporarily enable or disable a profile. Use **Edit** to change its criteria.

## Failed Accounts

The **Failed Accounts** page identifies accounts that have sent outreach for two consecutive days without receiving landlord replies.

Available actions:

- **Retry:** Queue the account for another attempt.
- **Clear:** Remove the failed status after reviewing the account.
- **Disable:** Disable the account to stop further activity.

Before retrying, check:

1. The account session status.
2. The assigned proxy health.
3. Recent worker errors.
4. Recent login and error logs.

## Logs

The **Logs** page is used for troubleshooting.

Filter logs by:

- Worker events.
- Errors.
- AI failures.
- Login events.
- Retries.
- Agent skips.

Use the search field to find an account email, thread ID, or error message. Select a log row to view additional context.

Select **Full Logs** when the recent log list does not include the event you need.

## Settings

The **Settings** page contains global automation controls.

It includes:

- Auto-send AI replies.
- OpenAI model selection.
- Minimum and maximum action delays.
- Retry limit.
- Maximum simultaneous workers.
- Default daily message limit.
- Backend, Redis, worker, and queue status.

Use **Test API** to check backend connectivity.

> **Administrator control:** Changes on this page affect all accounts. Do not change global settings without approval.

## Troubleshooting

### The dashboard says the backend is unavailable

1. Open **Settings**.
2. Select **Test API**.
3. If the backend remains unavailable, contact the system administrator.

### An account has a login error

1. Confirm the account credentials are correct.
2. Use **Refresh session**.
3. Review the **Login** tab in Logs.
4. If required, use **Invalidate session**, then refresh it again.

### An account has a proxy error

1. Open **Accounts**.
2. Use **Test proxy** for the affected account.
3. Confirm the assigned proxy is active.
4. Reassign the account to a healthy proxy if necessary.

### A worker is not running

1. Confirm the account is active and not paused.
2. Confirm its proxy is healthy.
3. Check whether all worker slots are already in use.
4. Select **Start worker**.
5. Review the last worker error and Logs if it fails again.

### A conversation is missing recent messages

The dashboard shows messages that have already been persisted by the automation worker. Wait for the account worker to process the OpenRent inbox, then allow up to approximately 10 seconds for the conversation page to refresh.

## Safety Guidelines

- Review account, proxy, and search-profile details before starting automation.
- Keep daily message limits conservative unless an administrator approves changes.
- Do not delete accounts, proxies, locations, or profiles without confirming their dependencies.
- Do not invalidate healthy account sessions.
- Review failed conversations before marking them complete or invalid.
- Contact the system administrator when repeated proxy, login, backend, or worker errors occur.
