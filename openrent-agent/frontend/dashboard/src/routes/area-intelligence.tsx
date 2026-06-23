import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { BarChart3, Boxes, CircleGauge, MapPinned, Phone, Users } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { StatCard } from "@/components/stat-card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getAreaIntelligence, type AreaIntelligenceMetric } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";

export const Route = createFileRoute("/area-intelligence")({
  head: () => ({
    meta: [
      { title: "Area Intelligence - Land Royal" },
      { name: "description", content: "Measured area supply, conversion, and account capacity." },
    ],
  }),
  component: AreaIntelligencePage,
});

type AreaStatus = AreaIntelligenceMetric["status"];
type FilterValue = "all" | AreaStatus;

const FILTERS: Array<{ label: string; value: FilterValue }> = [
  { label: "All", value: "all" },
  { label: "Expand", value: "expand" },
  { label: "Maintain", value: "maintain" },
  { label: "Pause", value: "pause" },
  { label: "Insufficient", value: "insufficient_data" },
];

const STATUS_LABEL: Record<AreaStatus, string> = {
  expand: "Expand",
  maintain: "Maintain",
  pause: "Pause",
  insufficient_data: "Insufficient data",
};

const STATUS_CLASS: Record<AreaStatus, string> = {
  expand: "border-success/30 bg-success/15 text-success",
  maintain: "border-info/30 bg-info/15 text-info",
  pause: "border-destructive/40 bg-destructive/15 text-destructive",
  insufficient_data: "border-border bg-muted text-muted-foreground",
};

function AreaIntelligencePage() {
  const [filter, setFilter] = useState<FilterValue>("all");
  const {
    data: areas = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["area-intelligence"],
    queryFn: getAreaIntelligence,
    refetchInterval: 60000,
  });

  const filtered = useMemo(
    () => areas.filter((area) => filter === "all" || area.status === filter),
    [areas, filter],
  );

  const totals = useMemo(() => {
    return areas.reduce(
      (acc, area) => {
        acc.usable += area.usable_inventory;
        acc.new7d += area.new_listings_7d;
        acc.supported += area.estimated_supported_accounts;
        acc.active += area.active_accounts;
        acc.phones += area.phones;
        acc.conversations += area.conversations;
        if (area.status === "expand") acc.expand += 1;
        return acc;
      },
      {
        usable: 0,
        new7d: 0,
        supported: 0,
        active: 0,
        phones: 0,
        conversations: 0,
        expand: 0,
      },
    );
  }, [areas]);

  const phoneRate = totals.conversations
    ? Math.round((totals.phones / totals.conversations) * 100)
    : 0;

  if (isLoading) {
    return <PageHeader title="Area Intelligence" description="Loading measured area data..." />;
  }

  if (error) {
    return (
      <PageHeader
        title="Area Intelligence"
        description="Could not load area intelligence data from the API."
      />
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Area Intelligence"
        description="Measured area supply, conversion, and account capacity from existing OpenRent data."
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatCard label="Areas" value={areas.length} icon={MapPinned} />
        <StatCard
          label="Usable Inventory"
          value={totals.usable}
          icon={Boxes}
          tone={totals.usable > 0 ? "success" : "default"}
        />
        <StatCard label="New 7 Days" value={totals.new7d} icon={BarChart3} />
        <StatCard
          label="Supported Accounts"
          value={`${totals.active}/${totals.supported}`}
          icon={Users}
          tone={totals.supported > totals.active ? "warning" : "default"}
        />
        <StatCard label="Phone Rate" value={`${phoneRate}%`} icon={Phone} />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Tabs value={filter} onValueChange={(value) => setFilter(value as FilterValue)}>
          <TabsList className="flex h-auto flex-wrap justify-start">
            {FILTERS.map((item) => (
              <TabsTrigger key={item.value} value={item.value}>
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="text-sm text-muted-foreground">
          Showing {filtered.length} of {areas.length} area(s)
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead className="min-w-[220px]">Area</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Accounts</TableHead>
              <TableHead className="text-right">Usable</TableHead>
              <TableHead className="text-right">New 24h</TableHead>
              <TableHead className="text-right">New 7d</TableHead>
              <TableHead className="text-right">Private</TableHead>
              <TableHead className="text-right">Agent</TableHead>
              <TableHead className="text-right">Reply</TableHead>
              <TableHead className="text-right">Phone</TableHead>
              <TableHead className="text-right">Supported</TableHead>
              <TableHead className="min-w-[280px]">Evidence</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={12} className="py-10 text-center text-muted-foreground">
                  No areas match this filter.
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((area) => (
                <TableRow key={area.location}>
                  <TableCell>
                    <div className="font-medium">{area.location}</div>
                    <div className="text-xs text-muted-foreground">
                      {area.total_listings} total listings, {area.processing_failures} failure(s)
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge className={cn("whitespace-nowrap", STATUS_CLASS[area.status])}>
                      {STATUS_LABEL[area.status]}
                    </Badge>
                  </TableCell>
                  <NumberCell value={area.active_accounts} muted />
                  <NumberCell value={area.usable_inventory} />
                  <NumberCell value={area.new_listings_24h} muted />
                  <NumberCell value={area.new_listings_7d} />
                  <NumberCell value={area.private_landlord_listings} muted />
                  <NumberCell value={area.agent_listings} muted />
                  <PercentCell value={area.reply_rate_pct} />
                  <PercentCell value={area.phone_capture_rate_pct} />
                  <TableCell className="text-right">
                    <div className="font-medium tabular-nums">
                      {area.estimated_supported_accounts}
                    </div>
                    <div
                      className={cn(
                        "text-xs tabular-nums",
                        area.current_account_gap > 0
                          ? "text-warning"
                          : area.current_account_gap < 0
                          ? "text-destructive"
                          : "text-muted-foreground",
                      )}
                    >
                      gap {formatSigned(area.current_account_gap)}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {area.evidence}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-start gap-2 rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
        <CircleGauge className="mt-0.5 size-4 shrink-0" />
        <p>
          Status and capacity are calculated from measured listings and conversations. This page
          does not use AI-generated metrics.
        </p>
      </div>
    </div>
  );
}

function NumberCell({ value, muted = false }: { value: number; muted?: boolean }) {
  return (
    <TableCell className={cn("text-right tabular-nums", muted && "text-muted-foreground")}>
      {value}
    </TableCell>
  );
}

function PercentCell({ value }: { value: number }) {
  return (
    <TableCell className="text-right tabular-nums">
      <span
        className={cn(
          value >= 20 ? "text-success" : value > 0 ? "text-warning" : "text-muted-foreground",
        )}
      >
        {value}%
      </span>
    </TableCell>
  );
}

function formatSigned(value: number) {
  if (value > 0) return `+${value}`;
  return String(value);
}
