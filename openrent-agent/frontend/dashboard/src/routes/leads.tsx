import { createFileRoute, Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useState, useMemo, useEffect } from "react";
import {
  ExternalLink,
  Copy,
  MoreHorizontal,
  MessageSquare,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { completeLead, getAccounts, getLeads, getSearchProfiles } from "@/lib/api";
import { fmtMoney, fmtRelative } from "@/lib/format";
import { STATUS_META } from "@/lib/status";
import type { LeadStatus } from "@/lib/types";
import { toast } from "sonner";

export const Route = createFileRoute("/leads")({
  head: () => ({
    meta: [
      { title: "Leads — Land Royal" },
      { name: "description", content: "All landlord conversations and AI outreach." },
    ],
  }),
  component: LeadsPage,
});

function LeadsPage() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  if (pathname !== "/leads") {
    return <Outlet />;
  }

  return <LeadsList />;
}

function LeadsList() {
  const [statuses, setStatuses] = useState<LeadStatus[]>([]);
  const [accountIds, setAccountIds] = useState<string[]>([]);
  const [profileIds, setProfileIds] = useState<string[]>([]);
  const [hasPhone, setHasPhone] = useState(true);
  const [aiFailed, setAiFailed] = useState(false);
  const [activeOnly, setActiveOnly] = useState(false);
  const [viewingsOnly, setViewingsOnly] = useState(false);
  const [lastUpdated, setLastUpdated] = useState("all");
  const [q, setQ] = useState("");
  const [currentPage, setCurrentPage] = useState(0);
  const PAGE_SIZE = 10;
  const queryClient = useQueryClient();
  const completeMutation = useMutation({
    mutationFn: completeLead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leads"] });
      toast.success("Conversation marked complete");
    },
    onError: () => toast.error("Could not update conversation"),
  });

  const {
    data: leads = [],
    isLoading: leadsLoading,
    error: leadsError,
  } = useQuery({
    queryKey: ["leads"],
    queryFn: () => getLeads(),
    refetchInterval: 10000,
  });

  const { data: accounts = [] } = useQuery({
    queryKey: ["accounts"],
    queryFn: getAccounts,
  });

  const { data: searchProfiles = [] } = useQuery({
    queryKey: ["search-profiles"],
    queryFn: getSearchProfiles,
  });

  useEffect(() => {
    setCurrentPage(0);
  }, [
    statuses,
    accountIds,
    profileIds,
    hasPhone,
    aiFailed,
    activeOnly,
    viewingsOnly,
    lastUpdated,
    q,
  ]);

  const filtered = useMemo(
    () =>
      leads.filter((l) => {
        if (statuses.length > 0 && !statuses.includes(l.status)) return false;
        if (accountIds.length > 0 && !accountIds.includes(l.accountId)) return false;
        if (profileIds.length > 0 && !profileIds.includes(l.searchProfileId)) return false;
        if (hasPhone && !l.phoneNumber) return false;
        if (aiFailed && l.status !== "AI_FAILED") return false;
        if (activeOnly && !["INITIAL_MESSAGE_SENT", "NEW_REPLY", "AI_REPLIED"].includes(l.status))
          return false;
        if (viewingsOnly && !l.viewingConfirmed) return false;
        if (lastUpdated !== "all") {
          const ms = { "1h": 3600000, "24h": 86400000, "7d": 604800000, "30d": 2592000000 }[lastUpdated];
          if (ms && Date.now() - new Date(l.lastUpdatedAt).getTime() > ms) return false;
        }
        if (q) {
          const t = q.toLowerCase();
          if (
            !l.threadId.toLowerCase().includes(t) &&
            !l.area.toLowerCase().includes(t) &&
            !l.propertyTitle.toLowerCase().includes(t) &&
            !l.landlordName.toLowerCase().includes(t) &&
            !l.listingId?.toLowerCase().includes(t) &&
            !l.phoneNumber?.toLowerCase().includes(t)
          )
            return false;
        }
        return true;
      }),
    [
      leads,
      statuses,
      accountIds,
      profileIds,
      hasPhone,
      aiFailed,
      activeOnly,
      viewingsOnly,
      lastUpdated,
      q,
    ],
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);

  const accountEmail = (id: string) => accounts.find((a) => a.id === id)?.email ?? id;

  const copyPhone = (p?: string) => {
    if (p) {
      navigator.clipboard.writeText(p);
      toast.success("Phone copied");
    }
  };

  if (leadsLoading) {
    return (
      <PageHeader title="Leads" description="Loading conversations from OpenRent automation..." />
    );
  }

  if (leadsError) {
    return (
      <PageHeader
        title="Leads"
        description="Could not load leads. Check that the FastAPI server is running on port 8000."
      />
    );
  }

  return (
    <>
      <PageHeader
        title="Leads"
        description={`${filtered.length} of ${leads.length} conversations`}
      />

      <div className="sticky top-14 z-20 -mx-4 md:-mx-6 px-4 md:px-6 py-3 mb-4 bg-background/90 backdrop-blur border-b">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            placeholder="Search thread, listing, landlord, address, phone..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="h-9 w-64"
          />
          <MultiSelectFilter
            allLabel="All statuses"
            countLabel="statuses"
            options={Object.entries(STATUS_META).map(([value, meta]) => ({
              value,
              label: meta.label,
            }))}
            selected={statuses}
            onChange={(values) => setStatuses(values as LeadStatus[])}
            className="w-44"
          />
          <MultiSelectFilter
            allLabel="All accounts"
            countLabel="accounts"
            options={accounts.map((a) => ({ value: a.id, label: a.email }))}
            selected={accountIds}
            onChange={setAccountIds}
            className="w-52"
          />
          <MultiSelectFilter
            allLabel="All profiles"
            countLabel="profiles"
            options={searchProfiles.map((s) => ({ value: s.id, label: s.location }))}
            selected={profileIds}
            onChange={setProfileIds}
            className="w-52"
          />
          <ToggleChip label="Has phone" checked={hasPhone} onChange={setHasPhone} />
          <ToggleChip label="AI failed" checked={aiFailed} onChange={setAiFailed} />
          <ToggleChip label="Active only" checked={activeOnly} onChange={setActiveOnly} />
          <ToggleChip label="Viewings" checked={viewingsOnly} onChange={setViewingsOnly} />
          <Select value={lastUpdated} onValueChange={setLastUpdated}>
            <SelectTrigger className="h-9 w-48">
              <SelectValue placeholder="Last updated" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Updated: Any time</SelectItem>
              <SelectItem value="1h">Updated: Last 1 hour</SelectItem>
              <SelectItem value="24h">Updated: Last 24 hours</SelectItem>
              <SelectItem value="7d">Updated: Last 7 days</SelectItem>
              <SelectItem value="30d">Updated: Last 30 days</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="w-full overflow-x-auto rounded-lg border bg-card">
        <Table className="min-w-max">
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Status</TableHead>
              <TableHead>Landlord</TableHead>
              <TableHead>Phone</TableHead>
              <TableHead>Address</TableHead>
              <TableHead>Beds</TableHead>
              <TableHead>Baths</TableHead>
              <TableHead>Rent</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>Listing ID</TableHead>
              <TableHead>Thread ID</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead>Account</TableHead>
              <TableHead>Last update</TableHead>
              <TableHead>Cancel</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {paginated.map((l) => (
              <TableRow key={l.id} className="cursor-pointer">
                <TableCell>
                  <StatusBadge status={l.status} />
                </TableCell>
                <TableCell className="max-w-[180px] truncate">{l.landlordName}</TableCell>
                <TableCell className="tabular-nums text-sm">
                  {l.phoneNumber ? (
                    <button
                      onClick={() => copyPhone(l.phoneNumber)}
                      className="inline-flex items-center gap-1 hover:text-foreground text-success"
                    >
                      {l.phoneNumber} <Copy className="size-3" />
                    </button>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="max-w-[260px] truncate">
                  {l.propertyAddress || l.propertyTitle}
                </TableCell>
                <TableCell className="tabular-nums">{l.bedrooms || "—"}</TableCell>
                <TableCell className="tabular-nums">{l.bathrooms || "—"}</TableCell>
                <TableCell className="tabular-nums">
                  {l.rent ? fmtMoney(l.rent) : "—"}
                </TableCell>
                <TableCell className="text-muted-foreground">{l.area}</TableCell>
                <TableCell className="font-medium">{l.listingId || "—"}</TableCell>
                <TableCell className="font-medium">
                  <Link
                    to="/leads/$threadId"
                    params={{ threadId: l.id }}
                    className="hover:underline"
                  >
                    {l.threadId}
                  </Link>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {l.conversationStage.replaceAll("_", " ").toLowerCase()}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {accountEmail(l.accountId)}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                  {fmtRelative(l.lastUpdatedAt)}
                </TableCell>
                <TableCell>
                  <CancelStatusBadge lead={l} />
                </TableCell>
                <TableCell>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="size-8">
                        <MoreHorizontal className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem asChild>
                        <Link to="/leads/$threadId" params={{ threadId: l.id }}>
                          <MessageSquare className="size-4" /> Open thread
                        </Link>
                      </DropdownMenuItem>
                      <DropdownMenuItem asChild>
                        <a href={l.propertyLink || "#"} target="_blank" rel="noreferrer">
                          <ExternalLink className="size-4" /> Open property
                        </a>
                      </DropdownMenuItem>
                      {l.phoneNumber && (
                        <DropdownMenuItem onClick={() => copyPhone(l.phoneNumber)}>
                          <Copy className="size-4" /> Copy phone
                        </DropdownMenuItem>
                      )}
                      <DropdownMenuItem onClick={() => completeMutation.mutate(l.threadId)}>
                        <CheckCircle2 className="size-4" /> Mark resolved
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {filtered.length > PAGE_SIZE && (
        <div className="flex items-center justify-between px-1 py-3">
          <span className="text-sm text-muted-foreground">
            {currentPage * PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PAGE_SIZE, filtered.length)} of {filtered.length}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage((p) => p - 1)}
              disabled={currentPage === 0}
            >
              <ChevronLeft className="size-4 mr-1" /> Previous
            </Button>
            <span className="text-sm text-muted-foreground px-2">
              {currentPage + 1} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage((p) => p + 1)}
              disabled={currentPage + 1 >= totalPages}
            >
              Next <ChevronRight className="size-4 ml-1" />
            </Button>
          </div>
        </div>
      )}
    </>
  );
}

function CancelStatusBadge({ lead }: { lead: import("@/lib/types").Lead }) {
  if (lead.viewingCancelled) {
    return (
      <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300">
        Cancelled
      </span>
    );
  }
  if (lead.viewingConfirmed && lead.cancelRequired) {
    return (
      <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-700 dark:bg-yellow-950 dark:text-yellow-300">
        Viewing booked — cancel queued
      </span>
    );
  }
  return null;
}

function MultiSelectFilter({
  allLabel,
  countLabel,
  options,
  selected,
  onChange,
  className,
}: {
  allLabel: string;
  countLabel: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (values: string[]) => void;
  className?: string;
}) {
  const selectedLabel =
    selected.length === 0
      ? allLabel
      : selected.length === 1
        ? options.find((option) => option.value === selected[0])?.label ?? `1 ${countLabel}`
        : `${selected.length} ${countLabel}`;

  const toggle = (value: string) => {
    onChange(
      selected.includes(value)
        ? selected.filter((selectedValue) => selectedValue !== value)
        : [...selected, value],
    );
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          className={`h-9 justify-between px-3 font-normal ${className ?? ""}`}
        >
          <span className="truncate">{selectedLabel}</span>
          <ChevronDown className="ml-2 size-4 shrink-0 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-80 w-64 overflow-y-auto">
        <DropdownMenuLabel>{allLabel}</DropdownMenuLabel>
        <DropdownMenuCheckboxItem
          checked={selected.length === 0}
          onCheckedChange={() => onChange([])}
          onSelect={(event) => event.preventDefault()}
        >
          {allLabel}
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        {options.map((option) => (
          <DropdownMenuCheckboxItem
            key={option.value}
            checked={selected.includes(option.value)}
            onCheckedChange={() => toggle(option.value)}
            onSelect={(event) => event.preventDefault()}
          >
            {option.label}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ToggleChip({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 rounded-md border bg-card px-3 h-9 text-sm cursor-pointer">
      <Switch checked={checked} onCheckedChange={onChange} />
      <Label className="cursor-pointer">{label}</Label>
    </label>
  );
}
