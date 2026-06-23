# Land Royal — Operator Troubleshooting Guide

> **Audience:** This guide is written for operators and virtual assistants who manage the Land Royal platform. No technical knowledge is required. All steps assume you are working from the platform dashboard only.

---

## How to Use This Guide

1. Find the section that matches your problem (Accounts, Proxies, Messaging, etc.).
2. Find the specific issue name that best describes what you are seeing.
3. Read **What this means** to confirm it matches your situation.
4. Follow the numbered steps under **How to fix it**.
5. If the steps do not solve the problem, go to **When to contact an administrator**.

If you are unsure what a word means, check the **Glossary** at the end of this guide.

---

## Quick Reference — Most Common Issues

| Problem you see | Go to section |
|---|---|
| Account shows red or error badge | Accounts → Account cannot log in |
| No messages sent today | Messaging → No messages sent today |
| Proxy shows as Down or Degraded | Proxies → Proxy down |
| Dashboard not loading | Platform Issues → Dashboard not loading |
| Phone number not captured | Messaging → Phone number not extracted |
| AI did not reply to a landlord | Messaging → Reply received but AI did not respond |
| Worker stuck on "Running" | Accounts → Account stuck in processing state |

---

# Section 1: Accounts

---

## Account Cannot Log In

### What this means
The platform tried to sign in to an OpenRent account on your behalf and failed. The account may show a red badge, an error status, or simply stop sending messages.

### Common causes
- The OpenRent password was changed on the OpenRent website but not updated in Land Royal.
- OpenRent showed a security check or verification page that the platform could not pass automatically.
- The account was temporarily blocked by OpenRent after too many failed attempts.
- The internet connection service (proxy) assigned to this account stopped working.
- OpenRent's website changed its layout, causing the login step to fail.

### How to fix it
1. Go to the **Accounts** page in the dashboard.
2. Find the account showing the login error.
3. Click the account to open its details.
4. Check the **Session status** field — it will show something like "Login failed" or "Captcha suspected."
5. If the password may have changed: click **Edit Account** and re-enter the correct OpenRent password, then click **Save**.
6. Click **Restart Worker** to try logging in again.
7. Wait 5–10 minutes and check if the status changes to "Active."
8. If the status is "Captcha suspected," wait 30–60 minutes before restarting — OpenRent may have flagged the account temporarily.
9. If the proxy assigned to this account shows as "Down" or "Degraded," fix the proxy first (see **Proxies** section), then restart the worker.

### When to contact an administrator
- The account keeps failing after 3 restart attempts with a fresh password.
- The account shows "Permanently failed."
- You suspect OpenRent has suspended or banned the account.
- The captcha check keeps reappearing after waiting.

### Related issues
- Account Suspended
- Session Expired
- Account Requires Verification
- Proxy Down

---

## Account Disabled

### What this means
The account has been turned off inside Land Royal. It will not send messages, check for replies, or do anything until it is turned back on. This is different from an account being suspended by OpenRent — a disabled account was switched off by an operator.

### Common causes
- An operator manually disabled the account.
- The account was automatically disabled after repeated failures.
- The account reached a failure limit set by the platform.

### How to fix it
1. Go to the **Accounts** page.
2. Find the account that appears greyed out or shows "Inactive."
3. Click the account to open its details.
4. Look for a toggle labelled **Active** or **Enabled** — switch it on.
5. Click **Save**.
6. Click **Restart Worker** to start the account again.
7. Wait 5 minutes and refresh the page. The status should change to "Running" or "Idle."

### When to contact an administrator
- You cannot find the Active toggle.
- The account re-disables itself immediately after being turned on.
- You are unsure why the account was disabled in the first place.

### Related issues
- Account Cannot Log In
- Account Stuck in Processing State

---

## Account Suspended

### What this means
OpenRent has placed a restriction on the account. This is different from a login failure — OpenRent itself has blocked the account from sending messages or viewing listings. The account may still appear to log in successfully but messages will not go through.

### Common causes
- The account sent too many messages in a short time.
- OpenRent detected unusual activity and flagged the account.
- The account was reported by a landlord.
- The account did not complete OpenRent's identity verification requirements.

### How to fix it
1. Go to the **Accounts** page and open the affected account.
2. Check the **Status** badge. If it shows "Reply Disabled" across multiple conversations, this may indicate a suspension.
3. Manually log in to the OpenRent account through a web browser (outside Land Royal) to check for any warning or restriction notices.
4. If OpenRent shows a verification email, complete it.
5. If OpenRent shows a suspension message, do not restart the worker — contact an administrator.
6. If the account appears normal on the OpenRent website, try restarting the worker in Land Royal.

### When to contact an administrator
- OpenRent shows an explicit suspension or ban message on the account.
- Multiple conversations show "Reply Disabled" status at the same time.
- The account passes login but no messages can be sent to any landlord.

### Related issues
- Account Cannot Log In
- Account Requires Verification
- Login Successful but Messages Not Sending

---

## Session Expired

### What this means
The platform keeps a saved login for each account so it does not need to enter the password every time. When this saved login becomes too old or gets invalidated by OpenRent, the account session expires. The platform then needs to log in again before it can continue working.

### Common causes
- The account has not been active for a long time and OpenRent ended the saved login.
- OpenRent updated its security settings and invalidated all saved logins.
- The proxy (internet connection) changed, causing OpenRent to distrust the saved login.
- The account password was changed.

### How to fix it
1. Go to the **Accounts** page.
2. Find the account showing "Session expired" or "Login failed."
3. Click the account and then click **Restart Worker**.
4. The platform will attempt a fresh login automatically.
5. Wait 10 minutes and check if the session status changes to "Active."
6. If it fails again, verify the password is correct by clicking **Edit Account**.

### When to contact an administrator
- The session expires repeatedly every day without explanation.
- The account cannot log in even with the correct password.
- Multiple accounts lose their session at the same time (this may indicate a platform-wide issue).

### Related issues
- Account Cannot Log In
- Proxy Down

---

## Account Requires Verification

### What this means
OpenRent is asking the account to prove it is real before allowing further activity. This is usually a one-time check triggered by a verification email, phone code, or identity question. Until the check is completed, the account cannot send or receive messages.

### Common causes
- A new account that has not yet been verified.
- OpenRent sent a verification email that was not clicked.
- OpenRent detected unusual login activity and is asking for extra confirmation.
- The account phone number needs to be verified.

### How to fix it
1. Go to the email inbox linked to this OpenRent account.
2. Look for an email from OpenRent with a subject like "Verify your account" or "Confirm your email."
3. Click the verification link in the email.
4. If OpenRent requires a phone code, enter the code sent to the registered number.
5. Once verified, go back to the **Accounts** page in Land Royal.
6. Click **Restart Worker** for that account.
7. Wait 5–10 minutes and check the status.

### When to contact an administrator
- You cannot access the email inbox for this account.
- No verification email was received even after checking spam/junk folders.
- OpenRent is asking for identity documents that you cannot provide.
- The verification step keeps reappearing after being completed.

### Related issues
- Account Cannot Log In
- Account Suspended

---

## Login Successful but Messages Not Sending

### What this means
The account logs in to OpenRent without errors, but no messages are being sent out. The account appears healthy but is not doing any work.

### Common causes
- The **AI Enabled** or **Outreach Enabled** setting is switched off for this account.
- The daily message limit has been reached.
- No active search profiles are linked to this account.
- The search area has no new listings to contact.
- The worker completed its run and is in a cooldown period (waiting before the next run).

### How to fix it
1. Go to the **Accounts** page and open the account.
2. Check that **AI Enabled** and **Outreach Enabled** are both turned on.
3. Check the **Messages Sent Today** count — if it matches or exceeds the daily limit, the account will not send more until midnight.
4. Check the **Next Run At** field — if it shows a future time, the account is waiting before its next run. This is normal.
5. Go to **Search Profiles** and confirm at least one active profile is linked to this account.
6. Check that the search profile area has listings available (see **Listings** section).
7. If everything looks correct, click **Restart Worker** to trigger a fresh run.

### When to contact an administrator
- All settings are correct but no messages have been sent for more than 24 hours.
- The account is active, the daily limit is not reached, and a search profile exists — but still nothing happens.

### Related issues
- Daily Message Limit Reached
- No Messages Sent Today
- No Listings Found

---

## Account Stuck in Processing State

### What this means
The account shows a status of "Running" or "Processing" but has been in that state for much longer than expected. A normal worker run takes 5–30 minutes. If an account has been showing "Running" for several hours, it is stuck.

### Common causes
- The automated browser crashed during a run and did not report back.
- An unexpected page appeared on OpenRent (such as a captcha or an error page) and the browser stopped.
- A connection problem caused the run to freeze.
- The previous run did not finish cleanly before the next one started.

### How to fix it
1. Go to the **Accounts** page.
2. Find the account showing "Running" for more than 1 hour.
3. Check the **Last Heartbeat** field — this shows the last time the account reported it was alive. If the heartbeat is more than 30 minutes old, the account is stuck.
4. Click **Stop Worker** to force-stop the current run.
5. Wait 2 minutes.
6. Click **Restart Worker** to start a fresh run.
7. Watch the status for the next 10 minutes to confirm it moves through "Running" and back to "Idle" or "Completed."

### When to contact an administrator
- The account keeps getting stuck on every run.
- **Stop Worker** does not change the status.
- The heartbeat shows the account has been stuck for more than 4 hours.

### Related issues
- Browser Failed to Start
- Browser Crashed
- Account Cannot Log In

---

# Section 2: Proxies

---

## Proxy Degraded

### What this means
A proxy is a service that gives an account a different internet address, making it look like the account is browsing from a different location. When a proxy is "degraded," it is still working but is slower than normal or less reliable than expected. Messages can still be sent but there may be delays.

### Common causes
- The proxy provider's servers are under heavy load.
- The internet connection between Land Royal and the proxy is slow.
- The proxy is connecting to OpenRent but taking longer than usual to load pages.
- The proxy is approaching its data or connection limit for the period.

### How to fix it
1. Go to the **Proxies** page in the dashboard.
2. Find the proxy showing a "Degraded" badge.
3. Click **Test Proxy** to run a fresh speed check.
4. If the test improves and shows "OK," the issue was temporary — no action needed.
5. If the test still shows "Degraded," check how many accounts are using this proxy. If more than 2 accounts share one proxy, performance will be reduced.
6. Try moving one of the accounts to a different proxy if available.
7. Wait 15–30 minutes and test again — degraded status often resolves on its own.

### When to contact an administrator
- The proxy has shown "Degraded" for more than 6 hours without improvement.
- All proxies are showing "Degraded" at the same time.
- Moving accounts to other proxies is not possible because all proxies are degraded.

### Related issues
- Proxy Down
- Connection Timeout
- Multiple Accounts Using Same Proxy

---

## Proxy Down

### What this means
The proxy is completely unreachable. Any account using this proxy cannot connect to OpenRent and will fail to log in or send messages until the proxy is restored.

### Common causes
- The proxy provider is experiencing an outage.
- The proxy login credentials (username and password for the proxy service) are wrong or have expired.
- The proxy subscription has expired and the provider has cut off access.
- A network issue between Land Royal and the proxy provider.

### How to fix it
1. Go to the **Proxies** page.
2. Find the proxy showing "Down."
3. Click **Test Proxy** — if it still shows "Down," the proxy is genuinely unreachable.
4. Check with your proxy provider's website or status page to see if they are reporting an outage.
5. If the proxy credentials may have changed, click **Edit Proxy** and update the username, password, and port if needed, then click **Save** and test again.
6. If the proxy is down, temporarily move accounts to another working proxy:
   - Go to **Accounts**, open each affected account, and assign a different proxy.
7. Once the proxy provider resolves their issue, move the accounts back.

### When to contact an administrator
- No other proxies are available to reassign accounts to.
- The proxy credentials are correct but it is still showing "Down."
- The proxy has been down for more than 24 hours.
- You do not have login access to the proxy provider's account.

### Related issues
- Proxy Degraded
- Tunnel Error
- Account Cannot Log In

---

## Proxy Test Failed

### What this means
A manual test was run on the proxy and it did not pass. The platform could not confirm the proxy is working correctly. This does not always mean the proxy is completely broken — sometimes a test fails briefly even when the proxy is mostly fine.

### Common causes
- Temporary network interruption during the test.
- The proxy is overloaded and timed out during the test.
- The proxy credentials are incorrect.
- The proxy server address or port number is entered wrongly.

### How to fix it
1. Go to the **Proxies** page and find the proxy that failed the test.
2. Wait 5 minutes and click **Test Proxy** again — a single failed test does not always mean a real problem.
3. If it fails again, click **Edit Proxy** and double-check:
   - Server address (e.g. `proxy.example.com`)
   - Port number (e.g. `8080`)
   - Username and password
4. Correct any mistakes, click **Save**, then test again.
5. If the proxy uses a static IP and the platform's outgoing IP has changed, contact your proxy provider to whitelist the new IP.

### When to contact an administrator
- The proxy details are correct but tests keep failing.
- You do not know what the correct proxy credentials should be.
- The proxy was working yesterday and nothing was changed.

### Related issues
- Proxy Down
- Proxy Degraded
- Connection Timeout

---

## Tunnel Error

### What this means
A tunnel error means the connection between Land Royal and the proxy broke partway through. The platform managed to reach the proxy but then lost the connection before it could complete its work. Think of it like a phone call that connects but then cuts out.

### Common causes
- The proxy provider disconnected the session due to inactivity or timeout.
- A network hiccup between the platform's servers and the proxy.
- The proxy server restarted during an active session.
- Too many simultaneous connections through the same proxy.

### How to fix it
1. Go to the **Accounts** page and find accounts that errored due to a tunnel issue (they will show a worker error or login failure).
2. Click **Restart Worker** on the affected accounts.
3. Go to the **Proxies** page and click **Test Proxy** on the proxy used by those accounts.
4. If the proxy tests OK, the tunnel error was temporary — the restart should be enough.
5. If tunnel errors keep happening, reduce the number of accounts sharing this proxy to 1–2.

### When to contact an administrator
- Tunnel errors are happening on every run, not just occasionally.
- The proxy tests fine but accounts keep getting tunnel errors during runs.

### Related issues
- Proxy Down
- Connection Timeout
- Account Stuck in Processing State

---

## Connection Timeout

### What this means
The platform tried to connect to OpenRent through the proxy but waited too long and gave up. The connection simply never completed in time.

### Common causes
- The proxy is slow or overloaded.
- The OpenRent website was slow to respond at that moment.
- Too many accounts running at the same time through the same proxy.
- A firewall or network restriction is blocking the connection.

### How to fix it
1. Go to the **Proxies** page and run a test on the affected proxy — check the response time shown.
2. If the response time is very high (over 3,000 milliseconds), the proxy is too slow.
3. Reduce the number of accounts on this proxy.
4. Try reassigning the account to a faster proxy.
5. Restart the worker for the affected account — the timeout may have been a one-off.
6. Check if OpenRent's website is accessible normally (try opening it in your browser). If OpenRent itself is down, wait and retry later.

### When to contact an administrator
- Connection timeouts are happening consistently across many accounts.
- The proxy shows a fast response time but accounts still time out.
- OpenRent appears to be blocking the proxy's IP address.

### Related issues
- Proxy Down
- Proxy Degraded
- Tunnel Error

---

## Proxy Assigned Incorrectly

### What this means
An account is either using the wrong proxy or has no proxy assigned when it should have one. This can cause accounts to look like they are connecting from the same location, which increases the risk of OpenRent flagging them.

### Common causes
- The proxy was deleted and the account was left with no proxy assigned.
- A new account was set up without assigning a proxy.
- The proxy was reassigned to a different account and this account was forgotten.

### How to fix it
1. Go to the **Accounts** page.
2. Click the account and look at the **Proxy** field.
3. If it is empty or shows a deleted proxy, click **Edit Account**.
4. Select the correct proxy from the dropdown list.
5. Click **Save**, then restart the worker.
6. Confirm the account is now using the correct proxy by checking the **Proxy IP** field after the next run.

### When to contact an administrator
- You are unsure which proxy should be assigned to which account.
- No proxies are available to assign.

### Related issues
- Multiple Accounts Using Same Proxy
- Proxy Down

---

## Multiple Accounts Using Same Proxy

### What this means
Two or more accounts are sharing one proxy. While this is sometimes intentional, having too many accounts on one proxy increases the chance of OpenRent detecting that they are related. It can also make the proxy slower.

### Common causes
- Limited number of proxies available.
- Accounts were set up without checking proxy assignments.
- A proxy was deleted and multiple accounts defaulted to the same remaining proxy.

### How to fix it
1. Go to the **Proxies** page and click a proxy to see which accounts are using it.
2. Check the **Account Count** column — if it shows more than 2, consider reducing.
3. To reassign: go to **Accounts**, open the account you want to move, click **Edit Account**, choose a different proxy, and click **Save**.
4. Aim for a maximum of 1–2 accounts per proxy where possible.
5. If you do not have enough proxies, contact your proxy provider to purchase more.

### When to contact an administrator
- You need more proxies but do not have access to the proxy provider account.
- You are unsure how many accounts per proxy is safe.

### Related issues
- Proxy Degraded
- Proxy Assigned Incorrectly

---

## Proxy Rotation Failed

### What this means
Some proxies automatically cycle through different IP addresses (known as rotating proxies). If the rotation fails, the proxy stops changing addresses, which means accounts may appear to use the same internet address for too long.

### Common causes
- The rotation service from the proxy provider has a fault.
- The proxy credentials for the rotation service have expired.
- The proxy type was set up as "Rotating" in Land Royal but the provider actually gave a static proxy.

### How to fix it
1. Go to the **Proxies** page and find the rotating proxy.
2. Click **Test Proxy** to confirm it is still reachable.
3. Check the **Proxy Type** setting — confirm it says "Rotating."
4. Run the test twice and compare the **IP address** shown each time — if the IP is the same both times, the rotation is not working.
5. Contact your proxy provider to confirm the rotation service is active on your account.
6. If rotation cannot be fixed, treat the proxy as a static proxy and assign only one account to it.

### When to contact an administrator
- The proxy provider confirms the rotation is active but Land Royal keeps seeing the same IP.
- You need to change the proxy type setting.

### Related issues
- Proxy Test Failed
- Multiple Accounts Using Same Proxy

---

# Section 3: Messaging

---

## No Messages Sent Today

### What this means
The account is active and healthy but has not sent a single message today. This is one of the most common issues to investigate.

### Common causes
- The **Outreach Enabled** switch is turned off.
- No new listings were found in the search area.
- The daily message limit was already reached (unlikely if it's early in the day).
- The account is in a cooldown period and has not yet run today.
- The search profile area is too narrow and all available listings have already been contacted.

### How to fix it
1. Go to **Accounts** and open the account in question.
2. Confirm **Outreach Enabled** is switched on.
3. Check **Messages Sent Today** — if it is already at the daily limit, this is expected behaviour.
4. Check **Last Run At** — if the account ran recently and found nothing new, that is also normal.
5. Go to **Search Profiles** and check the search area and price range are set correctly.
6. Try widening the search area slightly (add a nearby town or increase the radius).
7. Click **Restart Worker** to trigger a fresh run now rather than waiting for the next scheduled run.
8. Wait 20 minutes and check **Messages Sent Today** again.

### When to contact an administrator
- No messages have been sent for 3 or more consecutive days despite an active account and valid search profile.
- You have widened the search area and still nothing is found.

### Related issues
- Daily Message Limit Reached
- No Listings Found
- Login Successful but Messages Not Sending

---

## Messages Queued but Not Sent

### What this means
Listings have been found and the platform is ready to send messages, but they are sitting in a queue and not actually being sent. The worker may appear to be running but messages are not going out.

### Common causes
- The worker is processing a large number of listings — give it time.
- The browser is loading OpenRent pages slowly due to a slow proxy.
- The account hit an error partway through a run, stopping the batch.
- OpenRent displayed a pop-up or verification step that blocked the run.

### How to fix it
1. Check if the worker is currently running — go to **Accounts** and look at the status.
2. If status is "Running," wait 15–20 more minutes before taking action. Large batches take time.
3. If the status is "Error" or has not changed in over 1 hour, click **Stop Worker** then **Restart Worker**.
4. After restarting, watch the **Messages Sent Today** count — it should start increasing within 10 minutes.
5. If a proxy error is showing, fix the proxy first (see **Proxies** section).

### When to contact an administrator
- The worker shows "Running" for more than 2 hours and no messages are going out.
- Messages were queued yesterday but never sent — now the listings have been skipped.

### Related issues
- Account Stuck in Processing State
- Proxy Down
- Browser Crashed

---

## Daily Message Limit Reached

### What this means
Each account is set to send a maximum number of messages per day. Once that limit is reached, the account will not send any more messages until midnight (UTC). This is by design and is a safety measure to avoid OpenRent flagging the account for sending too many messages.

### Common causes
- The account is performing well and has genuinely reached its daily quota — this is good.
- The daily limit is set too low for your needs.
- The limit was accidentally set to a very low number.

### How to fix it
1. Go to **Accounts** and check the **Messages Sent Today** and **Daily Message Limit** fields.
2. If the limit is reached and it is early in the day, this means the account is very active — good sign.
3. The counter resets automatically at midnight. No action is needed.
4. If you want to increase the daily limit: go to **Settings** and adjust **Daily Message Limit**. Be cautious — very high limits (above 30–40 per account per day) increase the risk of the account being flagged by OpenRent.
5. If you need more messages per day, add more accounts rather than raising the limit on existing ones.

### When to contact an administrator
- The daily limit needs to be increased beyond the current maximum allowed.
- The counter is showing as reached but you cannot see any messages in the Leads section.

### Related issues
- No Messages Sent Today
- Understanding Daily Messaging Limits

---

## Reply Received but AI Did Not Respond

### What this means
A landlord has replied to one of your messages, but the platform has not sent an AI response. The conversation is sitting there unacknowledged.

### Common causes
- The account's **AI Enabled** setting is switched off.
- The account has not yet run since the reply arrived — it checks for replies on a schedule (every 20–40 minutes).
- The AI failed to generate a reply for this specific conversation (see the conversation status in Leads).
- The platform detected the conversation should be skipped (e.g. reply disabled, or duplicate).
- The landlord's message was very short or unusual and the AI skipped it.
- The conversation has been marked as "Closed" or "Complete."

### How to fix it
1. Go to **Leads** and find the conversation.
2. Check the **Status** badge — if it shows "AI Failed," "Reply Disabled," or "Closed," that explains it.
3. Go to **Accounts** and confirm **AI Enabled** is switched on for this account.
4. Check **Last Run At** — if the account ran more than 1 hour ago without replying, the AI may have failed.
5. Click **Restart Worker** for the account to trigger a fresh check.
6. Wait 15 minutes and check the conversation again.
7. If the status shows "AI Failed," try refreshing — the next run will retry automatically.

### When to contact an administrator
- The conversation has been waiting for a reply for more than 3 hours with a working account.
- Multiple conversations across multiple accounts are all failing to get AI replies.
- The status shows "AI Failed" repeatedly on the same conversation.

### Related issues
- AI Reply Failed
- Conversation Stuck
- Account Stuck in Processing State

---

## AI Reply Failed

### What this means
The platform tried to generate a reply using AI but something went wrong and no reply was produced. The conversation will show an "AI Failed" status badge.

### Common causes
- The AI service was temporarily unavailable (rare, usually resolves in minutes).
- The conversation content was unusual and the AI could not produce a suitable reply.
- A settings issue with how the account is configured.
- The reply was generated but contained something the platform filtered out (such as an invalid phone number format).

### How to fix it
1. Go to **Leads** and find the conversation showing "AI Failed."
2. Note when the failure happened — if it was within the last 30 minutes, wait for the next automatic run.
3. Go to **Accounts** and click **Restart Worker** for the relevant account.
4. The platform will retry the AI reply on the next run automatically.
5. If the conversation has been failing for more than 24 hours, open the conversation to read the full thread — the landlord's message may require a manual response or the conversation may be a natural dead end.

### When to contact an administrator
- AI reply failures are happening across many conversations simultaneously.
- The same conversation has shown "AI Failed" for more than 3 days.
- You believe the AI is generating inappropriate or incorrect replies.

### Related issues
- Reply Received but AI Did Not Respond
- Conversation Stuck

---

## Conversation Stuck

### What this means
A conversation appears to be at a standstill — the landlord has sent a message, the AI has not replied, and no progress is being made. The conversation is neither advancing nor being closed.

### Common causes
- The account's worker is not running correctly.
- The conversation was marked in a state that prevents AI replies (e.g. "Agent Skipped" or "Inactive").
- The landlord's last message was too long ago and the conversation has gone cold.
- The AI has been retrying and failing silently.

### How to fix it
1. Go to **Leads** and open the conversation.
2. Read the **Status** badge — common stuck states are:
   - **Agent Skipped**: the AI decided to let this one pass (unusual content, very short reply, etc.)
   - **AI Failed**: tried and failed — will retry next run
   - **Inactive – No Reply**: the landlord never replied, this is expected
3. Check when the last activity happened (the **Last Updated** column).
4. If the landlord replied within the last 48 hours and no AI reply went out, restart the account worker.
5. If the conversation has been cold for more than 1 week, it may be best to mark it as resolved and move on.

### When to contact an administrator
- The conversation is an important lead and the AI has not replied for more than 6 hours despite a working account.
- You need to manually send a reply (this would need to be done through OpenRent's website directly, outside of Land Royal).

### Related issues
- Reply Received but AI Did Not Respond
- AI Reply Failed

---

## Phone Number Not Extracted

### What this means
A landlord shared their phone number in a message, but Land Royal has not captured it in the **Phone** column of the Leads page. The number is visible in the conversation thread but has not been saved.

### Common causes
- The phone number was written in an unusual format (e.g. "zero seven nine..." written out as words).
- The number was included in a longer message and the platform missed it.
- The account's run has not yet processed the new message containing the number.
- The number was shared via an image or attachment (the platform reads text only).

### How to fix it
1. Go to **Leads** and find the conversation.
2. Open the conversation thread and locate the message where the landlord shared their number.
3. If the number is there but not in the **Phone** column, wait for the next account run (up to 40 minutes) — the extraction happens automatically on each run.
4. Click **Restart Worker** for that account to trigger a faster re-check.
5. After the run, check the **Phone** column again.
6. If the number is still not captured after two run cycles, manually copy it from the conversation thread and note it elsewhere for now.

### When to contact an administrator
- Phone numbers are consistently not being extracted across multiple conversations.
- You need the extraction to happen immediately and cannot wait for the next run.

### Related issues
- Phone Number Missing
- Conversation Stuck

---

## Viewing Appointment Not Scheduled

### What this means
A landlord has offered a viewing time in the conversation, but Land Royal has not marked the conversation as having a viewing arranged. This matters because it affects when the platform might send a cancellation message.

### Common causes
- The viewing was mentioned informally without both sides confirming a specific time and date.
- OpenRent's viewing confirmation banner did not appear (it only appears after both sides formally agree via OpenRent's booking system).
- The landlord gave a time but the AI has not yet confirmed it back.
- The conversation is still in the "discussing availability" stage.

### How to fix it
1. Go to **Leads** and find the conversation.
2. Read through the thread — was a specific date and time agreed by both parties?
3. If yes: restart the worker for that account. The platform re-checks viewing status on every run.
4. If the viewing was only loosely suggested (e.g. "sometime next week"), this is correct — no viewing is considered booked yet.
5. Check the **Stage** column in Leads — "Viewing Booked" means the platform has detected a confirmed viewing.

### When to contact an administrator
- A viewing is clearly confirmed in the conversation but the stage still does not show "Viewing Booked" after 24 hours.

### Related issues
- Conversation Stuck
- Viewing Cancellation Not Triggered

---

## Duplicate Messages Detected

### What this means
The same message has been sent to the same landlord more than once. The landlord may have received an identical message twice, which can look unprofessional.

### Common causes
- The worker ran twice very close together (e.g. a manual restart overlapped with a scheduled run).
- A conversation was processed by two different accounts by mistake.
- The platform sent a message, the send appeared to fail, and then retried — but the original message actually did go through.

### How to fix it
1. Go to **Leads** and open the conversation where duplicates occurred.
2. Check the message timestamps — this helps confirm if two runs fired at nearly the same time.
3. You cannot unsend messages from within Land Royal — they are already on OpenRent.
4. If this is a new conversation, do not worry too much — landlords generally understand occasional double messages.
5. To prevent future duplicates: avoid manually restarting workers while they are already running. Wait until the status changes to "Idle" before restarting.
6. If a specific conversation keeps getting duplicates, mark it as "Resolved" or "Closed" to prevent further automated messages.

### When to contact an administrator
- Duplicate messages are happening frequently across many conversations.
- The same initial enquiry was sent to the same listing multiple times.

### Related issues
- Duplicate Conversations
- Account Stuck in Processing State

---

# Section 4: Listings

---

## No Listings Found

### What this means
The platform searched OpenRent for properties matching your search profile settings but found nothing. No messages will be sent if no listings are found.

### Common causes
- The search area is too small or too specific.
- The price range is too narrow — no available listings fall within it.
- All available listings in the area have already been contacted.
- The bedroom requirement is too restrictive.
- OpenRent does not currently have any new listings in that area.

### How to fix it
1. Go to **Search Profiles** and open the profile for the affected account.
2. Review the search settings:
   - **Location**: is the area large enough? Try a city-level search instead of a specific postcode.
   - **Price range**: is the range realistic for that area?
   - **Bedrooms**: is the minimum/maximum too restrictive?
3. Widen at least one setting (e.g. increase max rent by £200 or add a nearby city).
4. Save the profile and restart the worker.
5. Wait for the next run and check the **Messages Sent Today** counter.

### When to contact an administrator
- The search area is already very wide and still nothing is found.
- The area genuinely has no available listings on OpenRent (the market may be slow).

### Related issues
- Very Few Listings Found
- Area Search Returning No Results
- Low Listing Count

---

## Very Few Listings Found

### What this means
The search is working but only returning a small number of results — fewer than expected. The account may be sending 1–2 messages per day instead of the 10–20 it could reach.

### Common causes
- The search area is medium-sized but the market is slow.
- Many of the available listings have already been contacted previously.
- The search filters (pets, furnished, etc.) are eliminating too many listings.
- Seasonal slowdown — rental markets are often quieter in winter months.

### How to fix it
1. Go to **Search Profiles** and loosen any filters that are not essential (e.g. "pets allowed" if it is not required, or furnishing requirements).
2. Expand the price range slightly above and below your ideal range.
3. Add a second nearby location to the search profile if possible.
4. Consider adding a second account targeting a different area to compensate.

### When to contact an administrator
- The area truly has very few listings and you need to discuss strategy.

### Related issues
- No Listings Found
- Low Listing Count

---

## Duplicate Listings

### What this means
The same property appears to be contacted more than once. This can happen when a landlord re-lists the same property under a different listing ID.

### Common causes
- The landlord deleted their listing and reposted it (creating a new ID).
- The same property appears under two different listings (e.g. different bedroom configurations for the same flat).
- The platform contacted the property through two different accounts.

### How to fix it
1. Go to **Leads** and search for the property address using the search bar.
2. If you find two conversations for the same address, check the **Landlord Name** on both — if it is the same person, one of them is a duplicate.
3. Mark the older or less active one as "Resolved" to prevent further AI messages going to the same landlord.
4. No further action is needed — duplicate detection is built into the platform, but re-listed properties can occasionally slip through.

### When to contact an administrator
- Duplicate listings are happening very frequently (more than 5 per week).
- The same landlord is being contacted by multiple accounts simultaneously.

### Related issues
- Duplicate Conversations
- Listing Already Contacted

---

## Area Search Returning No Results

### What this means
The search area specified in the search profile is not returning any results on OpenRent. This could mean the location name is not recognised by OpenRent, or the area genuinely has no listings.

### Common causes
- The location name is misspelled or uses an abbreviation OpenRent does not recognise.
- The area is too rural or specific (e.g. a very small village name).
- The platform's connection to OpenRent did not complete the search properly.

### How to fix it
1. Go to **Search Profiles** and open the affected profile.
2. Check the **Location** field — try replacing a specific street or village name with a nearby town or city name.
3. Open OpenRent's website in your browser and manually search for the same location and price range — check if any listings appear. If not, the market is genuinely empty there.
4. Save the updated profile and restart the worker.

### When to contact an administrator
- The location is correct and OpenRent shows listings when you search manually, but Land Royal still finds nothing.

### Related issues
- No Listings Found
- Search Profile Not Working

---

## Listing Skipped

### What this means
The platform found a listing but decided not to send a message to it. Each skipped listing is intentional — the platform follows rules about which listings to contact.

### Common causes
- The listing was already contacted previously (the platform remembers).
- The listing was marked as a duplicate.
- The listing ID matched a known skip pattern.
- The listing did not meet the minimum requirements of the search profile (e.g. pets policy mismatch).

### How to fix it
1. Skipped listings are usually correct behaviour — no action is needed.
2. If you believe a specific listing was skipped wrongly: go to **Leads**, search for the listing ID, and check its history.
3. If you want to manually contact a listing that was skipped, do so directly through OpenRent's website — Land Royal will then pick up any reply that comes in.

### When to contact an administrator
- A large proportion of found listings are being skipped (e.g. more than 50%).
- A specific listing you know is new is being skipped repeatedly.

### Related issues
- No Listings Found
- Listing Already Contacted

---

## Listing Already Contacted

### What this means
The platform has already sent an initial message to this listing in the past and will not send another one. This is deliberate — sending two initial messages to the same landlord would look odd.

### Common causes
- The listing was contacted previously and is still active on OpenRent (landlord has not taken it down).
- The listing was re-found by the search after being contacted weeks or months ago.

### How to fix it
1. This is correct behaviour and does not need fixing.
2. If the landlord has not replied and you want to follow up: go to **Leads**, find the conversation, and check if the AI has sent a follow-up message. The platform sends follow-ups automatically.
3. If the listing has been re-posted by the landlord as a brand new listing (new ID), it will be treated as fresh and contacted again automatically.

### When to contact an administrator
- You believe an important listing was not contacted and cannot see it in Leads at all.

### Related issues
- Listing Skipped
- Duplicate Listings

---

# Section 5: Browser Automation

---

## Browser Failed to Start

### What this means
The platform uses an automated browser (like a computer program that opens a web browser) to interact with OpenRent. When this browser fails to start, the worker cannot do anything at all.

### Common causes
- A resource issue on the platform's hosting environment (temporary, usually resolves itself).
- A conflict with a previous browser session that did not close cleanly.
- The account tried to start too many browser sessions at once.

### How to fix it
1. Go to **Accounts** and find the account showing a startup error.
2. Wait 5 minutes — sometimes the system resolves this on its own.
3. Click **Stop Worker** then **Restart Worker**.
4. Watch the status for the next few minutes.
5. If the issue repeats, check if too many accounts are running simultaneously — the platform can only run a limited number at once.

### When to contact an administrator
- Browser startup failures are happening on every single run.
- Multiple accounts all fail to start at the same time.

### Related issues
- Browser Crashed
- Account Stuck in Processing State

---

## Browser Crashed

### What this means
The automated browser started successfully but stopped unexpectedly in the middle of a run. The worker was doing something (logging in, checking messages, sending a reply) when the browser closed without warning.

### Common causes
- A web page on OpenRent was very slow to load and the browser gave up.
- An unexpected pop-up, error page, or CAPTCHA appeared.
- A memory issue caused the browser to close.
- The proxy connection dropped while the browser was active.

### How to fix it
1. Go to **Accounts** and find the crashed account — it will likely show "Error" status.
2. Check if the proxy for this account is working (go to **Proxies** and test it).
3. Fix any proxy issues first.
4. Click **Restart Worker** for the affected account.
5. The platform will pick up where it left off on the next run — any messages that were mid-send may be retried.

### When to contact an administrator
- The browser crashes on every run, even with a working proxy.
- The crash is causing duplicate messages to be sent (message sent, browser crashed before confirming, message retried).

### Related issues
- Browser Failed to Start
- Account Stuck in Processing State
- Tunnel Error

---

## Browser Closed Unexpectedly

### What this means
Similar to a crash, but slightly different — the browser opened, completed some work, and then closed before it finished the full run. The account may have partially processed a batch of conversations.

### Common causes
- A timeout: the run was taking too long and the system closed the browser to free up resources.
- A network interruption mid-run.
- OpenRent displayed a page the browser did not expect (e.g. maintenance page).

### How to fix it
1. This often resolves itself on the next scheduled run.
2. Click **Restart Worker** to trigger a fresh run sooner.
3. Check if OpenRent is accessible — if their website is down for maintenance, wait and retry later.

### When to contact an administrator
- Every run ends with the browser closing early and no work is completed.

### Related issues
- Browser Crashed
- Connection Timeout

---

## Login Page Not Loading

### What this means
The automated browser reached the OpenRent login page but the page never fully loaded. The account could not proceed with logging in.

### Common causes
- The proxy is too slow and the page timed out before loading.
- OpenRent is experiencing issues with their website.
- The proxy is blocked by OpenRent (the IP is on a blocklist).

### How to fix it
1. Test the proxy assigned to this account — go to **Proxies** and click **Test Proxy**.
2. If the proxy shows "Down" or "Degraded," fix the proxy first.
3. Try reassigning the account to a different proxy temporarily.
4. Restart the worker and see if the login page loads with the new proxy.
5. Try opening OpenRent's website yourself — if it is slow for you too, the issue may be on OpenRent's end.

### When to contact an administrator
- Multiple proxies all fail to load the login page for OpenRent.
- OpenRent is accessible from your browser but not through the platform.

### Related issues
- Proxy Down
- Account Cannot Log In
- Connection Timeout

---

## OpenRent Page Not Opening

### What this means
After logging in, the automated browser could not open the specific OpenRent pages it needs (such as the inbox or a listing page). The account is logged in but cannot do its work.

### Common causes
- OpenRent changed the address or layout of a page.
- The proxy is blocking certain pages or being rate-limited by OpenRent.
- OpenRent is showing an error or "site under maintenance" message.

### How to fix it
1. Wait 30 minutes and restart the worker — temporary OpenRent issues usually resolve quickly.
2. Test the proxy to ensure it is working.
3. If this has been happening for more than 2 hours, check if OpenRent's website is generally accessible.

### When to contact an administrator
- This has been happening for more than 6 hours.
- OpenRent has changed its layout and the platform needs to be updated to match.

### Related issues
- Browser Crashed
- Login Page Not Loading

---

## Automation Stopped Midway

### What this means
The worker started a run, sent some messages, and then stopped before completing all the planned work. Some conversations got replies, others did not.

### Common causes
- The daily message limit was reached partway through the run.
- An error occurred on one conversation that caused the run to stop.
- A proxy or browser issue interrupted the run.
- The account's cooldown started mid-run.

### How to fix it
1. Check **Messages Sent Today** — if the limit is reached, this is expected and correct.
2. Look at the account status — if it shows "Error," restart the worker.
3. The remaining conversations will be processed on the next run automatically.
4. If you need faster processing, click **Restart Worker** to begin the next run sooner.

### When to contact an administrator
- The account stops after exactly 1–2 messages every run and never completes a full batch.

### Related issues
- Daily Message Limit Reached
- Browser Crashed
- Account Stuck in Processing State

---

# Section 6: Platform Issues

---

## Dashboard Not Loading

### What this means
When you open Land Royal in your browser, the page either stays blank, shows an error, or spins without loading. You cannot access any part of the platform.

### Common causes
- Your internet connection is interrupted.
- The Land Royal platform is temporarily offline for maintenance.
- Your browser has old data (cache) that is conflicting with the latest version of the dashboard.
- You are trying to access the platform from a blocked network (e.g. some work or school networks).

### How to fix it
1. Check your internet connection — try opening a different website to confirm you are online.
2. Try opening the dashboard in a different browser (e.g. Chrome if you normally use Safari).
3. Try opening the dashboard in an "incognito" or "private" window.
4. Clear your browser's cache: in most browsers, press **Ctrl + Shift + Delete** (Windows) or **Cmd + Shift + Delete** (Mac) and clear cached data.
5. Wait 10 minutes and try again — if the platform is under maintenance, it will come back on its own.

### When to contact an administrator
- The dashboard has been unreachable for more than 30 minutes.
- Other operators are also unable to access it (confirming it is not your connection).

### Related issues
- Statistics Not Updating
- Changes Not Saving

---

## Statistics Not Updating

### What this means
The numbers on the dashboard (total messages sent, phone numbers captured, active accounts, etc.) are not changing even though work is clearly happening. The figures look frozen or outdated.

### Common causes
- The statistics page has not been refreshed — numbers update automatically but there can be a delay.
- The browser is showing a cached (old) version of the page.
- A background process that calculates statistics has fallen behind.

### How to fix it
1. Refresh the page (press **F5** or click the refresh button in your browser).
2. Wait 5 minutes — statistics are usually updated every few minutes, not in real time.
3. If the numbers have not changed in more than 1 hour, try logging out and back in.
4. Clear your browser cache and reload the page.

### When to contact an administrator
- Statistics have not updated for more than 6 hours despite active accounts.
- The statistics are clearly wrong (e.g. showing zero messages when the Leads page shows many conversations).

### Related issues
- Reports Showing Incorrect Numbers
- Dashboard Not Loading

---

## Reports Showing Incorrect Numbers

### What this means
The summary statistics or report figures do not match what you see elsewhere in the platform. For example, the report says 5 phone numbers were collected today but the Leads page shows 12.

### Common causes
- Reports may have a slight delay compared to live data.
- Filters applied to a report are excluding some records (e.g. date range filter is too narrow).
- A calculation method change may have affected historical numbers.

### How to fix it
1. Check all active filters on the report — make sure date ranges, accounts, and status filters are set to show what you expect.
2. Compare the same metric in multiple places (e.g. Leads page count vs. report count).
3. Reset all filters to "All" and recheck the totals.
4. If the discrepancy persists, note the specific numbers and report them.

### When to contact an administrator
- The discrepancy is significant (more than 10% difference between pages).
- Incorrect statistics are affecting operational decisions.

### Related issues
- Statistics Not Updating

---

## Search Profile Not Working

### What this means
A search profile has been set up with location, price range, and bedroom requirements, but it is not producing any search results or the results are completely wrong (wrong area, wrong price range).

### Common causes
- The location name was entered incorrectly.
- The price range is set to £0 or an invalid value.
- The profile is not linked to any active account.
- The profile is set to "Inactive."

### How to fix it
1. Go to **Search Profiles** and open the affected profile.
2. Check every field:
   - **Location**: must be a recognisable UK town, city, or postcode area.
   - **Price range**: ensure Min and Max are realistic values (e.g. £700–£1,400).
   - **Bedrooms**: confirm the minimum and maximum are set (e.g. 1–3).
   - **Active**: the toggle must be switched on.
3. Check that this profile is linked to at least one active account.
4. Save and restart the associated account worker.

### When to contact an administrator
- The profile appears correct but still produces no results after 24 hours.

### Related issues
- No Listings Found
- Area Search Returning No Results

---

## Changes Not Saving

### What this means
You edit something in the dashboard (account settings, search profile, proxy details) and click **Save**, but when you return to that page the changes are gone.

### Common causes
- A validation error prevented the save — an error message may have appeared briefly.
- Your session has timed out and you are no longer authenticated.
- A browser extension or security tool is blocking the save request.
- Poor internet connection caused the save to fail silently.

### How to fix it
1. Try making the change again — this time, watch carefully for any red error messages after clicking **Save**.
2. If an error appears, read it — it usually tells you which field has a problem (e.g. "Invalid price range").
3. Log out and log back in, then try saving again.
4. Try in a different browser or incognito mode.
5. Check your internet connection — if it is unstable, the save request may not be reaching the platform.

### When to contact an administrator
- Changes consistently fail to save even after trying multiple times across different browsers.

### Related issues
- Dashboard Not Loading

---

## Sync Issue Detected

### What this means
The platform has detected that something is out of sync — for example, an account's data on Land Royal does not match what is on OpenRent, or a conversation was updated on OpenRent but not reflected in Land Royal.

### Common causes
- A run was interrupted before it could update the local data.
- OpenRent updated a conversation from their end (e.g. a landlord edited a message, or OpenRent marked a listing as let agreed).
- A network issue prevented the platform from reading the latest state from OpenRent.

### How to fix it
1. Restart the worker for the affected account — this forces a fresh sync with OpenRent.
2. After the run completes, check if the data is now updated.
3. If a specific conversation seems out of sync, open it in **Leads** and check the latest messages. The next run will re-read it.

### When to contact an administrator
- The sync issue persists across multiple runs for the same account.
- Data appears genuinely corrupted or missing (not just delayed).

### Related issues
- Conversation History Missing
- Statistics Not Updating

---

# Section 7: Data Issues

---

## Phone Number Missing

### What this means
A conversation in the Leads page shows no phone number in the **Phone** column, even though you expected one to have been captured.

### Common causes
- The landlord has not yet shared their phone number.
- The landlord shared a number but in a format the platform could not read (e.g. written out as words or split across two messages).
- The phone number was shared but the account has not yet run since the message arrived.
- The conversation was marked complete before the number was extracted.

### How to fix it
1. Go to **Leads** and open the conversation.
2. Read through the thread manually — look for any message from the landlord containing digits.
3. If you find the number, restart the account worker — the next run will attempt to extract it again.
4. If the landlord shared the number in a very unusual format, copy it manually from the conversation.
5. If no number has been shared yet, the AI will continue working toward asking for one naturally.

### When to contact an administrator
- Many conversations have numbers visible in the text but they are not being extracted automatically.

### Related issues
- Phone Number Not Extracted
- Conversation Stuck

---

## Landlord Name Missing

### What this means
A lead in the Leads page shows no landlord name, or it shows a placeholder like "Unknown." This can make it harder to keep track of conversations.

### Common causes
- The landlord did not sign their messages.
- The name was not present on the OpenRent listing page at the time the lead was created.
- The metadata collection step was skipped due to a partial run.

### How to fix it
1. Go to **Leads** and open the conversation.
2. Check the conversation thread — the landlord may have mentioned their name during the exchange.
3. Restart the worker — on the next run, it will try to re-read the listing metadata including the landlord's display name.
4. If the name is still missing after a run, it simply was not available on the listing — this is not a problem and does not affect the conversation.

### When to contact an administrator
- Landlord names are missing on a very large number of new leads (suggests a metadata collection problem).

### Related issues
- Property Details Incomplete

---

## Property Details Incomplete

### What this means
A lead is missing key information such as the number of bedrooms, rent amount, address, or property link. The card in Leads shows blank fields.

### Common causes
- The listing was found but the metadata collection run was incomplete.
- The listing was removed from OpenRent before full details could be collected.
- The search profile found the listing through a keyword search that provided limited data.

### How to fix it
1. Go to **Leads** and open the affected lead.
2. Check the **Property Link** field — if there is a link, click it to view the original OpenRent listing. Some details may still be live there.
3. Restart the account worker — on the next run it will attempt to re-read the listing.
4. If the listing has been taken down from OpenRent, the details cannot be recovered — this is expected.

### When to contact an administrator
- A large batch of new leads all have missing details simultaneously.

### Related issues
- Landlord Name Missing

---

## Duplicate Conversations

### What this means
The same landlord conversation appears twice in the Leads page — two separate entries for the same thread.

### Common causes
- The same listing was picked up by two different accounts.
- The listing was contacted, removed, re-listed with a new ID, and contacted again.
- A data sync issue created a second record for the same conversation.

### How to fix it
1. Go to **Leads** and search for the thread ID or landlord name.
2. Open both entries and compare the conversation history — one may be the original, one the duplicate.
3. Mark the duplicate (usually the one with less or no conversation history) as **Resolved** to hide it from active leads.
4. Continue working with the original conversation only.

### When to contact an administrator
- Duplicate conversations are appearing regularly (more than a few per week).
- Both duplicates have conversation history and you are unsure which is the real one.

### Related issues
- Duplicate Listings
- Duplicate Messages Detected

---

## Conversation History Missing

### What this means
A conversation in Leads shows the status and metadata but no actual messages. The thread appears empty even though you know messages have been exchanged.

### Common causes
- The messages were not yet loaded during the last run.
- The conversation was too long and only the most recent messages were fetched.
- OpenRent changed the way messages are displayed and the platform could not read them.

### How to fix it
1. Go to **Leads** and open the conversation.
2. Click the **Thread ID** link to open the original conversation on OpenRent directly (this shows all messages regardless of what Land Royal captured).
3. Restart the account worker to trigger a fresh message fetch.
4. Wait for the next run to complete and check again.

### When to contact an administrator
- Conversation history is missing across many leads at the same time.
- A specific important conversation has no history after multiple run cycles.

### Related issues
- Sync Issue Detected
- Conversation Stuck

---

# Section 8: Performance

---

## Low Reply Rate

### What this means
The percentage of landlords who are replying to your initial messages is lower than expected. A good reply rate is typically 20–40% — if you are seeing below 10%, something may need adjusting.

### Common causes
- The initial message template is not compelling or sounds too automated.
- The listings being contacted are too old (landlords may have already found a tenant).
- The persona used in messages does not match the property type (e.g. too professional for a small bedsit).
- Pricing or location mismatch — the AI is contacting properties that are not a realistic fit.

### How to fix it
1. Go to **Leads** and filter by **Active Only** to see conversations with recent landlord activity.
2. Read through several conversations to understand how landlords are responding (or not responding).
3. Check the search profiles — are the properties being contacted realistic matches?
4. Look at the initial messages being sent — do they sound natural and human?
5. If many leads are receiving no reply at all: widen the search area to include more listings, improving the chances of finding responsive landlords.
6. Consider targeting newer listings (recently posted) rather than ones that have been up for weeks.

### When to contact an administrator
- Reply rates have dropped significantly compared to a previous period for the same area.
- The initial message content may need to be updated.

### Related issues
- No Messages Sent Today
- Low Listing Count

---

## Low Message Count

### What this means
The total number of messages sent across all accounts is lower than what your capacity should allow. If you have 10 accounts with a limit of 20 messages each, you should be sending up to 200 messages per day.

### Common causes
- Several accounts have errors or are inactive.
- Search profiles are finding very few listings.
- The daily message limit is set too low.
- Many accounts are in a cooldown period and have not yet run today.

### How to fix it
1. Go to **Accounts** and check how many accounts are active and healthy (green status).
2. For any accounts showing errors, follow the relevant fix (see **Accounts** section).
3. Check **Messages Sent Today** for each account — identify which ones are underperforming.
4. Review search profiles for underperforming accounts — they may need wider search areas.
5. Check that **Outreach Enabled** is on for every account.

### When to contact an administrator
- All accounts appear healthy but message counts are consistently low.
- You want to increase capacity (add more accounts).

### Related issues
- No Messages Sent Today
- Low Listing Count
- Understanding Account Capacity

---

## Low Listing Count

### What this means
The platform is finding fewer available listings than expected. This reduces how many initial messages can be sent.

### Common causes
- The rental market in your target area has slowed down (common in winter or after a surge).
- All listings in the area have already been contacted.
- Search profiles are filtering too aggressively.
- Multiple accounts are all targeting the same area, sharing the same pool of listings.

### How to fix it
1. Review all search profiles — are multiple accounts searching the same area?
2. Spread accounts across different areas or towns to avoid overlap.
3. Widen each search profile's price range and location radius.
4. Check OpenRent directly — search for your area and count how many listings appear. This is the maximum possible listings available.

### When to contact an administrator
- After expanding all search profiles, listing counts are still very low.
- You need to scale to new areas and need guidance on how to set up new profiles.

### Related issues
- No Listings Found
- How Many Accounts Are Needed for an Area

---

## High Account Failure Rate

### What this means
A significant proportion of your accounts are showing errors, login failures, or are stuck. If more than 20–30% of your accounts are failing, this is a high failure rate.

### Common causes
- A wave of proxy failures (if all proxies are from the same provider and that provider is down).
- OpenRent changed its login process, causing multiple accounts to fail simultaneously.
- Accounts have aged or accumulated too many failures and need refreshing.
- Too many accounts running simultaneously is overloading the platform.

### How to fix it
1. Go to **Accounts** and sort by status — group all error accounts together.
2. Check if they share the same proxy — if so, fix the proxy first.
3. For each failed account, attempt a restart.
4. If accounts are all failing for the same reason (same error message), contact an administrator — this may be a platform-wide issue.
5. For accounts that have been in a "Permanently Failed" state, they may need to be replaced with fresh accounts.

### When to contact an administrator
- More than 5 accounts are failing simultaneously.
- All failures started at the same time (suggests an external trigger like an OpenRent change).

### Related issues
- Account Cannot Log In
- Proxy Down
- High Proxy Failure Rate

---

## High Proxy Failure Rate

### What this means
More than half your proxies are showing "Down" or "Degraded" at the same time. This is unusual and suggests either a problem with your proxy provider or a connectivity issue affecting the platform.

### Common causes
- The proxy provider is having an outage.
- Your proxy subscription has expired.
- All proxies are from the same provider who changed their connection method.
- The platform's outgoing IP range has been blocked by proxy providers.

### How to fix it
1. Go to **Proxies** and test all proxies — note which ones pass and which fail.
2. Check your proxy provider's status page or contact them to report the outage.
3. For any accounts whose proxy is down, temporarily pause the account (disable it) to prevent error loops.
4. Once the proxy provider restores service, re-enable accounts and restart workers.

### When to contact an administrator
- All proxies are down and you cannot run any accounts.
- You need to switch proxy providers and need help migrating accounts.

### Related issues
- Proxy Down
- High Account Failure Rate

---

# Section 9: Operations & Scaling

---

## How Many Accounts Are Needed for an Area

### What this means
Understanding how to size your operation for a given city or search area.

### Guidance
- **Small town** (fewer than 50 active listings on OpenRent at any time): 1–2 accounts is usually enough.
- **Medium city** (50–200 active listings): 3–5 accounts recommended, covering different price ranges.
- **Large city** (200+ active listings, e.g. Manchester, Leeds, Birmingham): 5–10 accounts, ideally with different personas and search profiles targeting different parts of the city.
- **London**: Each London borough can be treated like a separate medium city. Aim for 2–3 accounts per borough you target.
- Avoid pointing more than 3–4 accounts at exactly the same price range in the same area — they will compete for the same listings.
- Spread search profiles so accounts complement each other rather than duplicate each other.

### When to contact an administrator
- You are scaling to a new city and need advice on the optimal setup.
- You want to calculate a specific target before committing to new accounts.

### Related issues
- Understanding Account Capacity
- How Long It Will Take to Contact All Listings

---

## How Many SIMs Are Needed

### What this means
Some accounts use a real mobile phone number (SIM card) for verified WhatsApp or phone coordination. Understanding how many SIMs you need relative to accounts.

### Guidance
- **One SIM per account** is the safest approach — each account has its own unique UK mobile number.
- If SIMs are limited, you can share a SIM across 2 accounts in different areas, but this creates risk — if one account sends the number to a landlord and the other does too, the landlord may notice they are the same number.
- UK SIM cards for automation should be:
  - Active UK numbers (not VoIP)
  - Able to receive SMS for verification
  - On a pay-as-you-go plan to keep costs low (£1–£5/month per SIM)
- Virtual UK numbers (VoIP services like Skype or Google Voice UK numbers) are generally not recommended — landlords may recognise them as non-standard.
- For operations running 10+ accounts, bulk SIM purchasing from a UK MVNO (a company that resells SIM plans) is cost-effective.

### When to contact an administrator
- You need more SIMs and want guidance on sourcing them.
- A SIM is being blocked or landlords cannot call/text back on the number.

### Related issues
- How Many Accounts Are Needed for an Area

---

## How Long It Will Take to Contact All Listings

### What this means
Estimating the time required to contact every available listing in a target area.

### Guidance
Use this calculation:

1. **Find the total listing count**: Go to OpenRent and search your target area — count the total number of listings shown.
2. **Divide by your daily message capacity**:
   - Example: 150 listings ÷ 30 messages/day (3 accounts × 10 messages each) = **5 days to contact all listings**
3. **Allow for attrition**: Not every listing will receive a message on the first attempt (some will be skipped, some are too old). Add 20–30% to your estimate.
4. **Account for market refresh**: New listings appear every day. A healthy area generates 10–30 new listings per week. Once all existing listings are contacted, the platform will automatically pick up new ones.

**Rule of thumb**: For a medium city, 3–5 accounts can cover all new weekly listings within 1–2 days. For a large city, 8–10 accounts are needed to keep up with daily new listings.

### When to contact an administrator
- You need a precise estimate for a client or stakeholder report.
- The area has far more listings than expected and you need to scale up quickly.

### Related issues
- How Many Accounts Are Needed for an Area
- Understanding Daily Messaging Limits

---

## Understanding Account Capacity

### What this means
Each account has limits on how much it can do per day, and understanding these limits helps you plan your operation correctly.

### Guidance
- **Daily message limit**: Set in Settings. A safe range is **10–25 messages per account per day**. Going above 30 per day significantly increases the risk of OpenRent flagging the account.
- **Reply handling**: Each account checks for landlord replies every 20–40 minutes during operating hours. The platform handles replies automatically — you do not need to monitor this manually.
- **Cooldown**: After each run, accounts rest for 20–40 minutes before running again. This is normal and intentional.
- **Operating hours**: The platform runs accounts during standard hours. Accounts do not send messages in the middle of the night, which looks more human.
- **Viewing conversations**: An account can handle many simultaneous ongoing conversations without performance issues.

### When to contact an administrator
- You want to increase the daily limit above the current maximum.
- You need to understand how the platform prioritises which conversations to reply to first.

### Related issues
- Daily Message Limit Reached
- How Many Accounts Are Needed for an Area

---

## Understanding Daily Messaging Limits

### What this means
Why there is a daily cap and how it works.

### Guidance
- The daily message limit exists to mimic natural human behaviour. A real person does not send 200 messages to landlords in one day.
- OpenRent can detect and flag accounts that send messages at an unusually high rate. This can lead to the account being suspended.
- **Recommended daily limits by risk level**:
  - **Low risk**: 10–15 messages per account per day
  - **Medium risk**: 16–25 messages per account per day
  - **Higher risk**: 26–35 messages (not recommended for long-running accounts)
- The limit resets at **midnight UTC** (1am UK time in summer, midnight in winter).
- The limit only applies to **initial outreach messages** — AI replies to landlord messages do not count toward this limit.
- If you need more total messages per day, **add more accounts** rather than increasing individual account limits.

### When to contact an administrator
- You want to change the global default daily message limit.
- An account exceeded its limit in an unexpected way.

### Related issues
- Daily Message Limit Reached
- Understanding Account Capacity

---

# Section 10: UK Rental FAQs

These questions are about UK rental law and terminology. Land Royal operators are often asked these questions by landlords or when reviewing conversations.

---

## What Is a Guarantor

### What this means
A guarantor is a third person — usually a parent, relative, or employer — who agrees to pay the rent if the tenant cannot. The guarantor does not live in the property but is legally responsible if rent is missed.

### Key facts
- Landlords often ask for a guarantor when the tenant is a student, has a low income, or has no rental history in the UK.
- A guarantor typically needs to earn at least **30–36 times the monthly rent** as annual income (e.g. for £1,000/month rent, the guarantor should earn £30,000–£36,000 per year).
- A guarantor usually needs to be a UK resident.
- The guarantor must sign a legal document called a **Deed of Guarantee**.
- Some landlords accept a larger upfront deposit instead of a guarantor.

### In the context of Land Royal conversations
- If a landlord asks whether the tenant has a guarantor, the AI will respond based on the persona configured for that account. Most personas are configured as employed professionals who should not need a guarantor.

---

## What Is Council Tax

### What this means
Council tax is a local tax charged by UK councils (local governments) to fund services like rubbish collection, street lighting, and local schools. It is paid by whoever lives in the property, not by the landlord.

### Key facts
- Council tax is charged on most residential properties in England, Scotland, and Wales. Northern Ireland uses a different system called "rates."
- Properties are placed in **bands A to H** based on their estimated value in 1991. Band A is the cheapest, Band H the most expensive.
- A **single occupant** gets a 25% discount.
- Students are **fully exempt** from council tax — student households pay nothing.
- Some properties are fully exempt (e.g. properties where all occupants are students, or care homes).
- Monthly council tax amounts range from approximately **£80–£350/month** depending on the band and council.
- Landlords of **Houses in Multiple Occupation (HMOs)** are responsible for paying council tax if they rent individual rooms, not whole properties.
- When a tenant asks about council tax in a conversation, they are asking who pays it — the answer for a standard tenancy is: the **tenant pays it**.

---

## What Is an HMO

### What this means
HMO stands for **House in Multiple Occupation**. This is a property rented to 3 or more people who are not from the same family and who share facilities like a kitchen or bathroom.

### Key facts
- A typical HMO is a house with individual bedrooms rented to separate people (e.g. a 5-bedroom house with 5 separate tenants, each paying their own rent).
- HMOs require special licences from the local council. A landlord renting an HMO without a licence can face large fines.
- **Large HMOs** (5+ occupants, 3+ storeys) require a **mandatory HMO licence** from the council.
- Smaller HMOs may need an **additional licence** depending on the local council's rules.
- HMO tenants usually have their own tenancy agreement for their individual room, not the whole property.
- Council tax on an HMO is usually paid by the **landlord**, not the individual tenants.
- Landlords charging for rooms in an HMO must ensure fire safety standards (fire doors, smoke alarms, etc.) meet specific requirements.

---

## What Is a Holding Deposit

### What this means
A holding deposit is a small amount of money paid by a prospective tenant to "hold" a property while the landlord carries out reference and credit checks. It shows serious intent to rent.

### Key facts
- Under the **Tenant Fees Act 2019** (England), a holding deposit is capped at **one week's rent**.
  - Example: if rent is £1,000/month, the maximum holding deposit is £1,000 × 12 ÷ 52 = **£230.77**.
- The holding deposit is usually deducted from the first month's rent or the security deposit when the tenancy starts.
- If the **tenant withdraws** from the tenancy, the landlord may keep the holding deposit.
- If the **landlord withdraws** (without good reason), the holding deposit must be returned to the tenant.
- If the tenant **fails referencing** due to false information they provided, the landlord can keep the deposit.
- Holding deposits are different from the security/damage deposit.

---

## What Is a Tenancy Agreement

### What this means
A tenancy agreement (also called a "lease") is a legal contract between a landlord and a tenant. It sets out the rules of the tenancy: how much rent is paid, when it is paid, how long the tenancy lasts, and the responsibilities of both parties.

### Key facts
- The most common type in England is an **Assured Shorthold Tenancy (AST)**.
- Most tenancy agreements are for a **fixed term of 6 or 12 months** — during this time, neither the landlord nor the tenant can normally end the tenancy early without agreement.
- After the fixed term ends, the tenancy usually becomes a **rolling (periodic) tenancy** — continuing month-to-month until either party gives notice.
- Notice periods are typically **1–2 months**, depending on the tenancy agreement and local law.
- In **Scotland**, the standard is a **Private Residential Tenancy (PRT)**, which has no fixed end date. Notice must be given to end it.
- In **Wales**, similar rules to England apply under the **Renting Homes (Wales) Act 2016**.
- The tenancy agreement must comply with UK law — any clause that is unfair or illegal is unenforceable.
- Tenants should always read the full agreement before signing and keep a copy.

---

## What Is a Right to Rent Check

### What this means
A Right to Rent check is a legal requirement in England. Landlords must verify that any tenant they rent to has the legal right to live in the UK. Failing to do this can result in significant fines for the landlord.

### Key facts
- Right to Rent checks apply in **England only** — they are not required in Scotland, Wales, or Northern Ireland.
- Landlords (or their letting agents) must see original documents proving the tenant's right to be in the UK.
- Accepted documents include: **UK passport, EU Settlement Scheme status, Biometric Residence Permit, visa with right to remain**, and many others.
- The landlord must check the documents before the tenancy starts — usually during the referencing stage.
- If a tenant has a time-limited right to stay in the UK (e.g. a visa), the landlord must **re-check** when that visa expires.
- Landlords who rent to someone without the right to be in the UK can face fines of up to **£20,000 per tenant** (and potentially up to £3,000 per occupant under updated 2024 rules).
- The check process can now be done digitally through the **Home Office online service** for many non-UK nationals.

---

# Glossary

This glossary translates technical and rental-specific terms into plain English.

---

**Account**
One OpenRent account (email address + password) managed by Land Royal. Each account acts like a separate person looking for a rental property.

**Active**
A setting or status meaning something is switched on and working. An active account is running; an active search profile is being used.

**AI (Artificial Intelligence)**
The computer programme inside Land Royal that reads landlord messages and writes replies automatically. You do not need to understand how it works — it handles conversations on its own.

**AI Enabled**
A setting on each account that allows the AI to send replies. If this is turned off, the account will receive messages but not respond to them.

**AST (Assured Shorthold Tenancy)**
The most common type of rental contract in England. It gives the tenant the right to live in the property for an agreed period.

**Automation**
When the platform performs tasks automatically without a human doing them manually — such as sending messages, checking for replies, and extracting phone numbers.

**Browser (Automated)**
A computer programme that opens web pages like a human would — clicking buttons, filling in forms — without a real person sitting at a computer. Land Royal uses this to interact with OpenRent.

**Captcha**
A security puzzle that websites show to check whether the user is a human or a computer programme. When OpenRent shows a captcha, the automated browser may not be able to pass it, causing a login failure.

**Cooldown**
A waiting period between account runs. After an account completes a run, it waits 20–40 minutes before running again. This makes activity look more natural.

**Council Tax**
A local UK tax paid by the person living in the property, based on the property's value band. See the full entry in UK Rental FAQs.

**Daily Message Limit**
The maximum number of initial outreach messages an account is allowed to send in a single day. This limit resets at midnight.

**Dashboard**
The main web page where you manage all accounts, search profiles, proxies, and leads. It is your control centre for the entire platform.

**Deed of Guarantee**
A legal document signed by a guarantor, making them legally responsible for rent if the tenant fails to pay.

**Disabled**
A status meaning something has been turned off in Land Royal. A disabled account will not run until it is turned back on.

**Duplicate**
When the same thing (conversation, listing, message) appears more than once. Duplicates are usually unintentional.

**Escalation**
When a problem cannot be fixed by an operator and needs to be passed to an administrator or technical team.

**Extracted Phone**
A phone number that the platform has automatically read from a landlord's message and saved to the Leads page.

**Filter**
A setting that narrows down what you see — for example, filtering leads to show only those with a phone number, or filtering accounts to show only those with errors.

**Guarantor**
A person who agrees to pay the rent if the tenant cannot. See the full entry in UK Rental FAQs.

**Heartbeat**
A signal sent by a running account to show it is still active. If the heartbeat goes silent for more than 30 minutes, the account is likely stuck.

**HMO (House in Multiple Occupation)**
A property rented to multiple unrelated tenants who share facilities. Requires a licence. See the full entry in UK Rental FAQs.

**Holding Deposit**
A small payment made by a prospective tenant to reserve a property during the referencing period. Capped at one week's rent in England. See the full entry in UK Rental FAQs.

**Idle**
A status meaning an account is not currently running but is healthy and will run again at its next scheduled time.

**Initial Message**
The first message sent to a landlord when a new listing is found. This introduces the "tenant" and asks about viewing the property.

**Lead**
A landlord who has received an initial message. All leads are tracked on the Leads page.

**Leads Page**
The section of the dashboard that shows all conversations — who has replied, what stage the conversation is at, and whether a phone number has been captured.

**Listing**
A property advertised for rent on OpenRent.

**Listing ID**
A unique number that identifies a specific property listing on OpenRent.

**Outreach Enabled**
A setting that allows an account to send initial messages to new listings. If turned off, the account will not contact any new landlords.

**Persona**
The fictional tenant identity used in conversations — name, job, partner's name, income level. This makes conversations sound like they come from a real person.

**Phone Number (Captured)**
The landlord's phone number that has been extracted from the conversation and saved to the Lead record.

**Proxy**
A service that gives an account a different internet address, making it look like it is browsing from a different location. This helps make multiple accounts look like separate people.

**Proxy Status**
The current health of a proxy: OK (working), Degraded (slow), Down (not working), or Unknown.

**Queue**
A waiting line. When messages are "queued," they are lined up to be sent in order.

**Reply Disabled**
A status indicating that the landlord's OpenRent listing no longer accepts messages — often because the property has been let or the landlord has turned off replies.

**Right to Rent**
A legal check landlords in England must carry out to confirm tenants are allowed to live in the UK. See the full entry in UK Rental FAQs.

**Rolling Tenancy**
A tenancy that continues month-to-month after the initial fixed term ends, with no set end date.

**Run**
One complete cycle of an account checking for new listings, sending initial messages, and responding to landlord replies. Each run takes 5–30 minutes.

**Search Profile**
A set of settings (location, price range, bedrooms, etc.) that tells the platform what kind of properties to look for on OpenRent.

**Session**
A saved login that allows Land Royal to access an OpenRent account without re-entering the password every time. Sessions expire if not used for a long time.

**SIM Card**
A physical card that goes into a mobile phone and gives it a phone number. Used to provide accounts with real UK mobile numbers for landlord contact.

**Stage**
The current phase of a conversation. Common stages include: New Lead, Viewing Discussion, Viewing Booked, Contact Requested, and Closed.

**Static Proxy**
A proxy that always uses the same internet address. Suitable for one account per proxy.

**Status Badge**
A coloured label in the dashboard showing the current state of an account, conversation, or proxy (e.g. green for Active, red for Error).

**Tenancy Agreement**
A legal contract between landlord and tenant setting out the terms of the rental. See the full entry in UK Rental FAQs.

**Thread ID**
A unique identifier for a specific landlord conversation. Used to find specific conversations quickly.

**Tunnel**
The connection route between Land Royal and a proxy service. A tunnel error means this connection broke partway through.

**Verification**
A security step where OpenRent asks an account to confirm its identity — usually via email or phone code.

**Viewing**
A visit to a property by a prospective tenant to see if they want to rent it. Arranging viewings is one of the AI's primary goals in conversations.

**Viewing Booked**
A conversation stage indicating that a specific viewing time has been agreed between the AI persona and the landlord.

**Worker**
The background process that runs each account — logging in, finding listings, sending messages, and reading replies. Each account has its own worker.

**Worker Status**
The current state of an account's worker: Running, Idle, Completed, Error, Paused, or Stopped.

---

*This guide is maintained for Land Royal operators. For issues not covered here, contact your administrator with a description of the problem, the account email affected, and the approximate time the issue started.*
