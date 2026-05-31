
# OpenRent Automation — Admin Dashboard (Frontend)

A frontend-only operations dashboard built with TanStack Start, React, Tailwind v4, and shadcn/ui. All data is mocked in `src/lib/mock-data.ts` so the UI is fully interactive without a backend. Backend wiring (Lovable Cloud) can be added later.

## Design Direction

- SaaS operations console aesthetic — think Linear / Vercel / Resend admin.
- Dark mode default, light mode supported via existing `.dark` token system in `src/styles.css`.
- Information-dense: compact table rows, small type, tabular numerals, subtle borders.
- Status-driven color system using semantic tokens (success / warning / destructive / info / muted).
- Sidebar + top bar shell. Sticky filter bars on table pages. Slide-over sheets for detail/edit.

## Route & File Structure

```
src/routes/
  __root.tsx                  → shell: SidebarProvider + AppSidebar + Topbar + Outlet
  index.tsx                   → Dashboard overview (cards + charts)
  accounts.tsx                → Accounts CRUD
  search-profiles.tsx         → Search profiles CRUD
  leads.tsx                   → Leads/conversations table + filters
  leads.$threadId.tsx         → Conversation detail (chat view)
  logs.tsx                    → Operational logs
  settings.tsx                → Global settings

src/components/
  app-sidebar.tsx             → Sidebar nav (Dashboard, Accounts, Search Profiles,
                                Leads, Logs, Settings) + collapse
  topbar.tsx                  → Global search, theme toggle, user menu
  stat-card.tsx               → KPI card (label, value, delta, icon)
  status-badge.tsx            → Colored badge for all lead/account statuses
  data-table.tsx              → Reusable dense table (sticky header, row actions,
                                pagination, column visibility)
  filter-bar.tsx              → Sticky filter bar (status, account, profile,
                                date range, has-phone, ai-failed, active-only)
  empty-state.tsx
  confirm-dialog.tsx
  charts/
    line-chart.tsx            → Recharts wrapper using semantic tokens
    bar-chart.tsx
  dialogs/
    account-form-dialog.tsx
    search-profile-form-dialog.tsx
  conversation/
    message-bubble.tsx
    timeline.tsx
    manual-reply-box.tsx

src/lib/
  mock-data.ts                → accounts, profiles, leads, messages, logs, metrics
  status.ts                   → status → label/color mapping
  format.ts                   → date, currency, relative time

src/styles.css                → add status tokens (success, warning, info)
```

## Page Specs

### 1. Dashboard (`/`)
- Top row: 8 KPI cards (Total Listings Contacted, Total Replies, Total Phones Acquired, Active Conversations, Failed Conversations, AI Reply Success Rate, Agent Listings Skipped, Accounts Active).
- 2×2 chart grid (Recharts): Leads/day, Replies/day, Phones acquired/day, AI failures/day (line/area).
- Right rail (lg+): "Recent activity" list (latest 8 status changes).

### 2. Accounts (`/accounts`)
- Dense table: Email, Session Status, Worker Status, Daily Limit, Sent Today (progress bar), Proxy, AI toggle, Outreach toggle, Last Login, row menu.
- Toolbar: search + "Add Account".
- Row actions: Edit, Pause/Resume, Force Re-login, Delete (confirm).
- Add/Edit via shadcn Dialog with form (react-hook-form + zod).

### 3. Search Profiles (`/search-profiles`)
- Grouped table by account (or account filter at top).
- Cols: Account, Area, Price Min/Max, Beds Min/Max, Pets, Active switch, actions.
- Add/Edit dialog.

### 4. Leads (`/leads`)
- Sticky FilterBar: Status (multi), Account, Profile, Date range, Has Phone, AI Failed, Active Only, free-text search.
- Wide table with horizontal scroll: all columns from spec; status badge column; phone copy button; external link icons for Property and Thread.
- Row click → navigate to `/leads/$threadId`.
- Bulk actions: Mark Resolved, Disable AI.
- Pagination + column visibility toggle.

### 5. Conversation Detail (`/leads/$threadId`)
- Two-column layout (lg): left = chat thread (message bubbles, landlord vs AI vs operator), right = sidebar with property card, lead metadata, extracted phone, status, event timeline.
- Bottom: Manual reply composer with "Send", "Regenerate AI Reply".
- Header actions: Mark Complete, Mark Invalid, Disable AI, Open Property.

### 6. Logs (`/logs`)
- Tabs: All / Worker / Errors / AI failures / Login / Retries / Agent skips.
- Virtualized-feel table (level, timestamp, account, message, context). Filter by level + search. Row expand for stack/context JSON.

### 7. Settings (`/settings`)
- Card sections: AI Auto Send (switch), Global Delays (number inputs), Retry Limits, OpenAI Model (select: gpt-4o, gpt-4o-mini, gpt-4.1, etc.), Worker Concurrency (slider), Default Daily Limits.
- Save button per section, toast on save.

## Status Color System
Add to `src/styles.css` (oklch):
- `--success`, `--warning`, `--info`, plus `-foreground` variants for both themes.
StatusBadge maps:
- INITIAL_MESSAGE_SENT → info
- NEW_REPLY → warning (pulse)
- AI_REPLIED → success
- PHONE_ACQUIRED → success (solid)
- AI_FAILED → destructive
- REPLY_DISABLED, AGENT_SKIPPED, SKIPPED → muted
- DUPLICATE_LEAD → outline muted

## Technical Notes
- shadcn components used: sidebar, table, dialog, sheet, dropdown-menu, select, input, switch, button, badge, tabs, popover (date range), calendar, tooltip, sonner, card, progress, separator, skeleton.
- Charts via `recharts` (already common with shadcn `chart.tsx`).
- All data from `src/lib/mock-data.ts`; mutations update local state via `useState` + a tiny in-memory store (`src/lib/store.ts` using zustand-free pattern with React context) so CRUD feels real.
- Each route defines its own `head()` with title + description.
- Responsive: sidebar collapses to icon rail < lg; tables scroll horizontally on mobile; conversation view stacks.
- Dark mode: default `dark` class on `<html>` via root shell; theme toggle in topbar persists to `localStorage`.

## Out of Scope (this round)
- Real backend, auth, Lovable Cloud, OpenRent scraping, OpenAI calls, websockets. Easy to layer in later — server functions can replace the mock store without UI changes.

## Confirm Before Building
1. Frontend-only with rich mock data now, wire backend later — OK?
2. Default to dark mode with a light toggle — OK?
3. Skip auth screens for now (dashboard loads directly) — OK?
