import { createFileRoute, Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { ExternalLink, Copy, MoreHorizontal, MessageSquare, CheckCircle2 } from "lucide-react";
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
  DropdownMenuContent,
  DropdownMenuItem,
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
      { title: "Leads — RentPilot" },
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
  const [status, setStatus] = useState<LeadStatus | "all">("all");
  const [account, setAccount] = useState("all");
  const [profile, setProfile] = useState("all");
  const [hasPhone, setHasPhone] = useState(false);
  const [aiFailed, setAiFailed] = useState(false);
  const [activeOnly, setActiveOnly] = useState(false);
  const [viewingsOnly, setViewingsOnly] = useState(false);
  const [q, setQ] = useState("");
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
    queryKey: ["leads", status],
    queryFn: () => getLeads(status),
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

  const filtered = useMemo(
    () =>
      leads.filter((l) => {
        if (status !== "all" && l.status !== status) return false;
        if (account !== "all" && l.accountId !== account) return false;
        if (profile !== "all" && l.searchProfileId !== profile) return false;
        if (hasPhone && !l.phoneNumber) return false;
        if (aiFailed && l.status !== "AI_FAILED") return false;
        if (activeOnly && !["INITIAL_MESSAGE_SENT", "NEW_REPLY", "AI_REPLIED"].includes(l.status))
          return false;
        if (viewingsOnly && !l.viewingConfirmed) return false;
        if (q) {
          const t = q.toLowerCase();
          if (
            !l.threadId.toLowerCase().includes(t) &&
            !l.area.toLowerCase().includes(t) &&
            !l.propertyTitle.toLowerCase().includes(t)
          )
            return false;
        }
        return true;
      }),
    [leads, status, account, profile, hasPhone, aiFailed, activeOnly, viewingsOnly, q],
  );

  const accountEmail = (id: string) => accounts.find((a) => a.id === id)?.email ?? id;
  const profileLocation = (id: string) => searchProfiles.find((s) => s.id === id)?.location ?? id;

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
            placeholder="Search thread, location, property…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="h-9 w-64"
          />
          <Select value={status} onValueChange={(v) => setStatus(v as LeadStatus | "all")}>
            <SelectTrigger className="h-9 w-44">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {Object.entries(STATUS_META).map(([k, v]) => (
                <SelectItem key={k} value={k}>
                  {v.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={account} onValueChange={setAccount}>
            <SelectTrigger className="h-9 w-52">
              <SelectValue placeholder="Account" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All accounts</SelectItem>
              {accounts.map((a) => (
                <SelectItem key={a.id} value={a.id}>
                  {a.email}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={profile} onValueChange={setProfile}>
            <SelectTrigger className="h-9 w-52">
              <SelectValue placeholder="Profile" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All profiles</SelectItem>
              {searchProfiles.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.location}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <ToggleChip label="Has phone" checked={hasPhone} onChange={setHasPhone} />
          <ToggleChip label="AI failed" checked={aiFailed} onChange={setAiFailed} />
          <ToggleChip label="Active only" checked={activeOnly} onChange={setActiveOnly} />
          <ToggleChip label="Viewings" checked={viewingsOnly} onChange={setViewingsOnly} />
        </div>
      </div>

      <div className="rounded-lg border bg-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Status</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead>Thread</TableHead>
              <TableHead>Property</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>Budget</TableHead>
              <TableHead>Beds</TableHead>
              <TableHead>Account</TableHead>
              <TableHead>Profile</TableHead>
              <TableHead>Phone</TableHead>
              <TableHead>Viewing</TableHead>
              <TableHead>Last update</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((l) => (
              <TableRow key={l.id} className="cursor-pointer">
                <TableCell>
                  <StatusBadge status={l.status} />
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {l.conversationStage.replaceAll("_", " ").toLowerCase()}
                </TableCell>
                <TableCell className="font-medium">
                  <Link
                    to="/leads/$threadId"
                    params={{ threadId: l.id }}
                    className="hover:underline"
                  >
                    {l.threadId}
                  </Link>
                </TableCell>
                <TableCell className="max-w-[220px] truncate">{l.propertyTitle}</TableCell>
                <TableCell className="text-muted-foreground">{l.area}</TableCell>
                <TableCell className="tabular-nums">
                  {l.priceMin && l.priceMax
                    ? `${fmtMoney(l.priceMin)} – ${fmtMoney(l.priceMax)}`
                    : l.rent
                      ? fmtMoney(l.rent)
                      : "—"}
                </TableCell>
                <TableCell className="tabular-nums">
                  {l.bedroomsMin && l.bedroomsMax
                    ? `${l.bedroomsMin}–${l.bedroomsMax}`
                    : l.bedrooms || "—"}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {accountEmail(l.accountId)}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {profileLocation(l.searchProfileId)}
                </TableCell>
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
                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                  {l.viewingDatetime ? fmtRelative(l.viewingDatetime) : "—"}
                  {l.viewingCancelled ? (
                    <div className="text-destructive">cancelled</div>
                  ) : l.cancelRequired && l.viewingConfirmed ? (
                    <div>cancel queued</div>
                  ) : null}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                  {fmtRelative(l.lastUpdatedAt)}
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
    </>
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
