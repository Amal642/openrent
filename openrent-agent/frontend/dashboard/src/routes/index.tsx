import { useMemo, useState, type ReactElement } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  MessageCircle,
  Phone,
  Send,
  Server,
  Sparkles,
  Users,
  WifiOff,
  Zap,
} from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  AreaChart,
  Area,
} from "recharts";
import { StatCard } from "@/components/stat-card";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { getAccounts, getCapacity, getFailedAccountsCount, getLeads, getMetrics } from "@/lib/api";
import { fmtMoney, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Dashboard - Land Royal" },
      { name: "description", content: "Operational overview of OpenRent automation." },
    ],
  }),
  component: Dashboard,
});

const ranges = [
  { label: "7 days", days: 7 },
  { label: "14 days", days: 14 },
  { label: "30 days", days: 30 },
];

const statusFilters = [
  { label: "All", value: "all" },
  { label: "Needs attention", value: "attention" },
  { label: "Active", value: "active" },
  { label: "With phones", value: "phones" },
  { label: "Inactive", value: "inactive" },
];

function Dashboard() {
  const [rangeDays, setRangeDays] = useState(14);
  const [statusFilter, setStatusFilter] = useState("all");

  const {
    data: leads = [],
    isLoading: leadsLoading,
    error: leadsError,
  } = useQuery({
    queryKey: ["leads"],
    queryFn: () => getLeads(),
    refetchInterval: 10000,
  });

  const { data: accounts = [], isLoading: accountsLoading } = useQuery({
    queryKey: ["accounts"],
    queryFn: getAccounts,
    refetchInterval: 15000,
  });

  const { data: metrics } = useQuery({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    refetchInterval: 10000,
  });

  const { data: capacity } = useQuery({
    queryKey: ["capacity"],
    queryFn: getCapacity,
    refetchInterval: 10000,
  });

  const { data: failedCount = 0 } = useQuery({
    queryKey: ["failed-accounts-count"],
    queryFn: getFailedAccountsCount,
    refetchInterval: 60000,
  });

  const chartData = useMemo(() => (metrics?.series ?? []).slice(-rangeDays), [metrics, rangeDays]);
  const leadsInRange = chartData.reduce((sum, item) => sum + item.leads, 0);
  const totalRepliesReceived = leads.filter((l) => l.lastLandlordMessage).length;
  const phones = metrics?.total_phones ?? leads.filter((l) => l.phoneNumber).length;
  const active = leads.filter((l) =>
    ["INITIAL_MESSAGE_SENT", "NEW_REPLY", "AI_REPLIED"].includes(l.status),
  ).length;
  const failed = leads.filter((l) => l.status === "AI_FAILED").length;
  const skipped = leads.filter((l) => l.status === "AGENT_SKIPPED").length;
  const aiAttempts = leads.filter((l) => l.lastAiReply).length;
  const successRate = aiAttempts ? Math.round(((aiAttempts - failed) / aiAttempts) * 100) : 0;
  const replyRate = leads.length ? Math.round((totalRepliesReceived / leads.length) * 100) : 0;
  const accountsActive =
    metrics?.active_accounts ?? accounts.filter((a) => a.workerStatus !== "paused").length;
  const phonesToday = metrics?.phones_today ?? 0;
  const phoneTarget = metrics?.daily_phone_target ?? accounts.length * 3;
  const phoneProgress = Math.min(100, Math.round((phonesToday / Math.max(phoneTarget, 1)) * 100));

  const recent = useMemo(() => {
    return [...leads]
      .filter((lead) => {
        if (statusFilter === "attention") return lead.status === "AI_FAILED";
        if (statusFilter === "active") {
          return ["INITIAL_MESSAGE_SENT", "NEW_REPLY", "AI_REPLIED"].includes(lead.status);
        }
        if (statusFilter === "phones") return Boolean(lead.phoneNumber);
        if (statusFilter === "inactive") return lead.status === "INACTIVE_NO_REPLY";
        return true;
      })
      .sort((a, b) => b.lastUpdatedAt.localeCompare(a.lastUpdatedAt))
      .slice(0, 8);
  }, [leads, statusFilter]);

  if (leadsLoading || accountsLoading) {
    return (
      <EmptyState
        title="Getting your workspace ready"
        description="Loading accounts, conversations, and today's progress."
      />
    );
  }

  if (leadsError) {
    return (
      <EmptyState
        title="Dashboard data is not connected"
        description="Start the FastAPI API on port 8000, then refresh this page."
      />
    );
  }

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-lg border bg-card shadow-sm">
        <div className="grid gap-6 p-5 md:grid-cols-[1.4fr_1fr] md:p-6">
          <div className="space-y-5">
            <div>
              <div className="mb-2 inline-flex items-center gap-2 rounded-md bg-accent px-3 py-1 text-xs font-medium text-accent-foreground">
                <Sparkles className="size-3.5" />
                Friendly operations view
              </div>
              <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
                Today's outreach at a glance
              </h1>
              <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
                Track what is moving, what needs a reply, and whether the phone target is on pace.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <MiniMetric
                label="Reply rate"
                value={`${replyRate}%`}
                helper={`${totalRepliesReceived} replies`}
              />
              <MiniMetric
                label="Phone progress"
                value={`${phonesToday}/${phoneTarget}`}
                helper="today's target"
              />
              <MiniMetric
                label="Active accounts"
                value={`${accountsActive}/${accounts.length}`}
                helper="workers ready"
              />
            </div>
          </div>

          <div className="rounded-lg border bg-secondary/50 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold">Phone target</h2>
                <p className="text-sm text-muted-foreground">
                  A simple view of today's collection goal.
                </p>
              </div>
              <div className="flex size-10 items-center justify-center rounded-md bg-success/10 text-success">
                <Phone className="size-5" />
              </div>
            </div>
            <div className="mt-5">
              <div className="mb-2 flex items-end justify-between">
                <span className="text-3xl font-semibold tabular-nums">{phoneProgress}%</span>
                <span className="text-sm text-muted-foreground">{phonesToday} collected</span>
              </div>
              <div className="h-3 overflow-hidden rounded-full bg-background">
                <div
                  className="h-full rounded-full bg-success"
                  style={{ width: `${phoneProgress}%` }}
                />
              </div>
            </div>
            <Button asChild className="mt-5 w-full">
              <Link to="/leads">
                Review phone leads
                <ArrowRight className="size-4" />
              </Link>
            </Button>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <StatCard
          label="Landlords contacted"
          value={leadsInRange}
          icon={Send}
          delta={`last ${rangeDays} days`}
        />
        <StatCard
          label="Phone numbers"
          value={phones}
          icon={Phone}
          tone="success"
          delta="collected so far"
        />
        <StatCard label="Active chats" value={active} icon={Activity} delta="still moving" />
        <StatCard
          label="Needs attention"
          value={failed}
          icon={AlertTriangle}
          tone={failed ? "destructive" : "success"}
        />
        <StatCard label="AI success" value={`${successRate}%`} icon={CheckCircle2} tone="success" />
        <Link to="/failed-accounts" className="block">
          <StatCard
            label="Failed Accounts"
            value={failedCount}
            icon={AlertTriangle}
            tone={failedCount ? "destructive" : "success"}
            delta={failedCount ? "Click to review" : "All accounts healthy"}
          />
        </Link>
      </div>

      {failedCount > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          <AlertTriangle className="size-4 shrink-0" />
          <span className="font-medium">
            ⚠ {failedCount} Failed Account{failedCount !== 1 ? "s" : ""}
          </span>
          <span className="text-destructive/80">— sent messages for 2 days with no landlord replies.</span>
          <Button asChild variant="destructive" size="sm" className="ml-auto">
            <Link to="/failed-accounts">Review</Link>
          </Button>
        </div>
      )}

      <section className="rounded-lg border bg-card shadow-sm p-4">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="font-semibold">Worker capacity</h2>
            <p className="text-sm text-muted-foreground">
              Live view of parallel slots, proxy health, and queue depth.
            </p>
          </div>
          <div className="flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Zap className="size-4" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <CapacityTile
            label="Accounts Running"
            value={capacity?.accounts_running ?? 0}
            icon={Activity}
            tone={capacity?.accounts_running ? "success" : "muted"}
          />
          <CapacityTile
            label="Accounts Queued"
            value={capacity?.accounts_queued ?? 0}
            icon={Clock3}
            tone={capacity?.accounts_queued ? "warning" : "muted"}
          />
          <CapacityTile
            label="Healthy Proxies"
            value={capacity?.healthy_proxies ?? 0}
            icon={Server}
            tone={capacity?.healthy_proxies ? "success" : "muted"}
          />
          <CapacityTile
            label="Failed Proxies"
            value={capacity?.failed_proxies ?? 0}
            icon={WifiOff}
            tone={capacity?.failed_proxies ? "destructive" : "muted"}
          />
          <CapacityTile
            label="Slots Available"
            value={capacity?.worker_capacity ?? 0}
            icon={Zap}
            tone={
              capacity === undefined
                ? "muted"
                : capacity.worker_capacity === 0
                  ? "warning"
                  : "success"
            }
            suffix={capacity ? `/ ${capacity.max_parallel_workers}` : undefined}
          />
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.6fr_1fr]">
        <div className="rounded-lg border bg-card p-4 shadow-sm">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-semibold">Conversation momentum</h2>
              <p className="text-sm text-muted-foreground">
                Leads, replies, phones, and issues over time.
              </p>
            </div>
            <SegmentedControl
              options={ranges.map((range) => range.label)}
              active={`${rangeDays} days`}
              onChange={(label) =>
                setRangeDays(ranges.find((range) => range.label === label)?.days ?? 14)
              }
            />
          </div>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="leadsGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="var(--primary)" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="date" stroke="var(--muted-foreground)" fontSize={11} />
                <YAxis stroke="var(--muted-foreground)" fontSize={11} />
                <Tooltip
                  contentStyle={{
                    background: "var(--popover)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    fontSize: 12,
                    boxShadow: "0 10px 30px rgb(15 23 42 / 0.12)",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="leads"
                  name="Leads"
                  stroke="var(--primary)"
                  fill="url(#leadsGradient)"
                  strokeWidth={2.5}
                />
                <Line
                  type="monotone"
                  dataKey="replies"
                  name="Replies"
                  stroke="var(--warning)"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="phones"
                  name="Phones"
                  stroke="var(--success)"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="failures"
                  name="Issues"
                  stroke="var(--destructive)"
                  strokeWidth={2}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border bg-card p-4 shadow-sm">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold">Needs attention</h2>
              <p className="text-sm text-muted-foreground">A calmer list of what to check first.</p>
            </div>
            <div className="flex size-9 items-center justify-center rounded-md bg-warning/15 text-warning">
              <Clock3 className="size-4" />
            </div>
          </div>
          <div className="space-y-3">
            <AttentionItem
              icon={AlertTriangle}
              label="Failed conversations"
              value={failed}
              helper={failed ? "Open these first" : "No failed conversations"}
              tone={failed ? "destructive" : "success"}
            />
            <AttentionItem
              icon={MessageCircle}
              label="Replies received"
              value={totalRepliesReceived}
              helper="Check if any need a manual touch"
              tone="info"
            />
            <AttentionItem
              icon={Users}
              label="Skipped listings"
              value={skipped}
              helper="Useful for quality review"
              tone="muted"
            />
          </div>
        </div>
      </section>

      <section className="rounded-lg border bg-card shadow-sm">
        <div className="flex flex-col gap-3 border-b p-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="font-semibold">Recent activity</h2>
            <p className="text-sm text-muted-foreground">
              Latest landlord conversations, filtered for quick review.
            </p>
          </div>
          <SegmentedControl
            options={statusFilters.map((filter) => filter.label)}
            active={statusFilters.find((filter) => filter.value === statusFilter)?.label ?? "All"}
            onChange={(label) =>
              setStatusFilter(
                statusFilters.find((filter) => filter.label === label)?.value ?? "all",
              )
            }
          />
        </div>
        <ul className="divide-y">
          {recent.map((lead) => (
            <li
              key={lead.id}
              className="group grid gap-3 p-4 text-sm transition hover:bg-secondary/50 md:grid-cols-[1fr_auto] md:items-center"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{lead.landlordName}</span>
                  <StatusBadge status={lead.status} />
                </div>
                <div className="mt-1 truncate text-xs text-muted-foreground">
                  {lead.area} /{" "}
                  {lead.priceMin && lead.priceMax
                    ? `${fmtMoney(lead.priceMin)} - ${fmtMoney(lead.priceMax)}`
                    : lead.rent
                      ? fmtMoney(lead.rent)
                      : "rent unknown"}
                </div>
              </div>
              <div className="flex items-center justify-between gap-3 md:justify-end">
                <span className="text-xs text-muted-foreground">
                  {fmtRelative(lead.lastUpdatedAt)}
                </span>
                <Button asChild variant="outline" size="sm">
                  <Link to="/leads/$threadId" params={{ threadId: lead.threadId }}>
                    Open
                  </Link>
                </Button>
              </div>
            </li>
          ))}
          {recent.length === 0 && (
            <li className="p-8 text-center text-sm text-muted-foreground">
              Nothing matches this filter right now.
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-lg border bg-card p-8 text-center shadow-sm">
      <div className="mx-auto mb-4 flex size-11 items-center justify-center rounded-md bg-primary/10 text-primary">
        <Sparkles className="size-5" />
      </div>
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

function MiniMetric({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div className="rounded-lg border bg-background/70 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-muted-foreground">{helper}</div>
    </div>
  );
}

function SegmentedControl({
  options,
  active,
  onChange,
}: {
  options: string[];
  active: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="inline-flex rounded-md border bg-background p-1">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          className={cn(
            "h-8 rounded-sm px-3 text-xs font-medium transition",
            active === option
              ? "bg-primary text-primary-foreground shadow-sm"
              : "text-muted-foreground hover:bg-secondary hover:text-foreground",
          )}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function AttentionItem({
  icon: Icon,
  label,
  value,
  helper,
  tone,
}: {
  icon: typeof AlertTriangle;
  label: string;
  value: number;
  helper: string;
  tone: "destructive" | "success" | "info" | "muted";
}) {
  const classes = {
    destructive: "bg-destructive/10 text-destructive",
    success: "bg-success/10 text-success",
    info: "bg-info/10 text-info",
    muted: "bg-muted text-muted-foreground",
  }[tone];

  return (
    <div className="flex items-center gap-3 rounded-lg border bg-background/70 p-3">
      <div className={cn("flex size-9 items-center justify-center rounded-md", classes)}>
        <Icon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">{helper}</div>
      </div>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function CapacityTile({
  label,
  value,
  icon: Icon,
  tone,
  suffix,
}: {
  label: string;
  value: number;
  icon: typeof Activity;
  tone: "success" | "warning" | "destructive" | "muted";
  suffix?: string;
}) {
  const iconClasses = {
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    destructive: "bg-destructive/10 text-destructive",
    muted: "bg-muted text-muted-foreground",
  }[tone];

  return (
    <div className="flex items-center gap-3 rounded-lg border bg-background/70 p-3">
      <div className={cn("flex size-9 shrink-0 items-center justify-center rounded-md", iconClasses)}>
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <div className="truncate text-xs text-muted-foreground">{label}</div>
        <div className="mt-0.5 text-xl font-semibold tabular-nums">
          {value}
          {suffix && (
            <span className="ml-1 text-sm font-normal text-muted-foreground">{suffix}</span>
          )}
        </div>
      </div>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: ReactElement }) {
  return (
    <div className="rounded-lg border bg-card p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
