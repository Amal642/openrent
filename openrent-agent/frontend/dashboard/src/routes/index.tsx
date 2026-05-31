import { createFileRoute } from "@tanstack/react-router";
import {
  Send,
  MessageCircle,
  Phone,
  Activity,
  AlertTriangle,
  Sparkles,
  SkipForward,
  Users,
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
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { getAccounts, getLeads, getMetrics } from "@/lib/api";
import { fmtMoney, fmtRelative } from "@/lib/format";
import { useQuery } from "@tanstack/react-query";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Dashboard — RentPilot" },
      { name: "description", content: "Operational overview of OpenRent automation." },
    ],
  }),
  component: Dashboard,
});

function Dashboard() {
  const {
    data: leads = [],
    isLoading: leadsLoading,
    error: leadsError,
  } = useQuery({
    queryKey: ["leads"],
    queryFn: () => getLeads(),
  });

  const { data: accounts = [], isLoading: accountsLoading } = useQuery({
    queryKey: ["accounts"],
    queryFn: getAccounts,
  });

  const { data: metrics } = useQuery({
    queryKey: ["metrics"],
    queryFn: getMetrics,
  });

  const data = metrics?.series ?? [];
  const totalContacted = leads.length;
  const totalReplies = leads.filter((l) => l.lastLandlordMessage).length;
  const phones = metrics?.total_phones ?? leads.filter((l) => l.phoneNumber).length;
  const active = leads.filter((l) =>
    ["INITIAL_MESSAGE_SENT", "NEW_REPLY", "AI_REPLIED"].includes(l.status),
  ).length;
  const failed = leads.filter((l) => l.status === "AI_FAILED").length;
  const skipped = leads.filter((l) => l.status === "AGENT_SKIPPED").length;
  const aiAttempts = leads.filter((l) => l.lastAiReply).length;
  const successRate = aiAttempts ? Math.round(((aiAttempts - failed) / aiAttempts) * 100) : 0;
  const accountsActive =
    metrics?.active_accounts ?? accounts.filter((a) => a.workerStatus !== "paused").length;

  const recent = [...leads]
    .sort((a, b) => b.lastUpdatedAt.localeCompare(a.lastUpdatedAt))
    .slice(0, 8);

  if (leadsLoading || accountsLoading) {
    return <PageHeader title="Dashboard" description="Loading live automation data..." />;
  }

  if (leadsError) {
    return (
      <PageHeader
        title="Dashboard"
        description="Could not load backend data. Start the FastAPI API on port 8000 and refresh."
      />
    );
  }

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Live operational view across all accounts and workers."
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Listings contacted"
          value={totalContacted}
          icon={Send}
          delta="last 14 days"
        />
        <StatCard
          label="Replies"
          value={totalReplies}
          icon={MessageCircle}
          delta={`${totalContacted ? Math.round((totalReplies / totalContacted) * 100) : 0}% reply rate`}
        />
        <StatCard label="Phones acquired" value={phones} icon={Phone} tone="success" />
        <StatCard
          label="Phones today"
          value={`${metrics?.phones_today ?? 0}/${metrics?.daily_phone_target ?? 3}`}
          icon={Phone}
          tone={(metrics?.phones_today ?? 0) >= (metrics?.daily_phone_target ?? 3) ? "success" : "warning"}
        />
        <StatCard label="Active conversations" value={active} icon={Activity} />
        <StatCard
          label="Failed conversations"
          value={failed}
          icon={AlertTriangle}
          tone="destructive"
        />
        <StatCard
          label="AI reply success"
          value={`${successRate}%`}
          icon={Sparkles}
          tone="success"
        />
        <StatCard label="Agent listings skipped" value={skipped} icon={SkipForward} />
        <StatCard
          label="Accounts active"
          value={`${accountsActive}/${accounts.length}`}
          icon={Users}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-6">
        <div className="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-4">
          <ChartCard title="Leads per day">
            <AreaChart data={data}>
              <defs>
                <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--info)" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="var(--info)" stopOpacity={0} />
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
                }}
              />
              <Area
                type="monotone"
                dataKey="leads"
                stroke="var(--info)"
                fill="url(#g1)"
                strokeWidth={2}
              />
            </AreaChart>
          </ChartCard>
          <ChartCard title="Replies per day">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" stroke="var(--muted-foreground)" fontSize={11} />
              <YAxis stroke="var(--muted-foreground)" fontSize={11} />
              <Tooltip
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Line
                type="monotone"
                dataKey="replies"
                stroke="var(--warning)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ChartCard>
          <ChartCard title="Phones acquired per day">
            <AreaChart data={data}>
              <defs>
                <linearGradient id="g2" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--success)" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="var(--success)" stopOpacity={0} />
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
                }}
              />
              <Area
                type="monotone"
                dataKey="phones"
                stroke="var(--success)"
                fill="url(#g2)"
                strokeWidth={2}
              />
            </AreaChart>
          </ChartCard>
          <ChartCard title="AI failures per day">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" stroke="var(--muted-foreground)" fontSize={11} />
              <YAxis stroke="var(--muted-foreground)" fontSize={11} />
              <Tooltip
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Line
                type="monotone"
                dataKey="failures"
                stroke="var(--destructive)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ChartCard>
        </div>

        <div className="rounded-lg border bg-card">
          <div className="px-4 py-3 border-b">
            <h3 className="text-sm font-semibold">Recent activity</h3>
          </div>
          <ul className="divide-y">
            {recent.map((l) => (
              <li key={l.id} className="px-4 py-3 text-sm flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="truncate font-medium">{l.landlordName}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {l.area} ·{" "}
                    {l.priceMin && l.priceMax
                      ? `${fmtMoney(l.priceMin)} – ${fmtMoney(l.priceMax)}`
                      : l.rent
                        ? fmtMoney(l.rent)
                        : "rent unknown"}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <StatusBadge status={l.status} />
                  <span className="text-[10px] text-muted-foreground">
                    {fmtRelative(l.lastUpdatedAt)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactElement }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <h3 className="text-sm font-semibold mb-3">{title}</h3>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
