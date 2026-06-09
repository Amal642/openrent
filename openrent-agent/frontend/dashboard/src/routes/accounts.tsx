import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import {
  KeyRound,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  Power,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { DotBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Progress } from "@/components/ui/progress";
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
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  controlAccountWorker,
  createAccount,
  deleteAccount,
  getAccounts,
  getProxies,
  invalidateAccountSession,
  refreshAccountSession,
  testAccountProxy,
  updateAccount,
} from "@/lib/api";
import type { Proxy } from "@/lib/types";
import type { Account, ProxyStatus, SessionStatus, WorkerStatus } from "@/lib/types";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { toast } from "sonner";

export const Route = createFileRoute("/accounts")({
  head: () => ({
    meta: [
      { title: "Accounts - Land Royal" },
      { name: "description", content: "Manage OpenRent worker accounts." },
    ],
  }),
  component: AccountsPage,
});

const sessionTone: Record<SessionStatus, "success" | "warning" | "destructive" | "info"> = {
  active: "success",
  logging_in: "info",
  expired: "warning",
  login_failed: "destructive",
  captcha_suspected: "destructive",
  error: "destructive",
};
const workerTone: Record<WorkerStatus, "success" | "warning" | "destructive" | "muted"> = {
  queued: "warning",
  running: "success",
  stopping: "warning",
  idle: "muted",
  completed: "success",
  stopped: "muted",
  retrying: "warning",
  proxy_error: "destructive",
  login_error: "destructive",
  paused: "warning",
  error: "destructive",
};
const proxyTone: Record<ProxyStatus, "success" | "warning" | "destructive" | "muted"> = {
  ok: "success",
  degraded: "warning",
  down: "destructive",
  not_configured: "muted",
  unknown: "warning",
};

const CONVERSATION_STYLES = [
  { value: "friendly_viewing", label: "Friendly viewing first" },
  { value: "direct_number_request", label: "Direct professional number request" },
  { value: "video_call_request", label: "Relocation video call request" },
  { value: "warm_casual", label: "Warm casual couple" },
  { value: "professional_polite", label: "Professional polite" },
  { value: "busy_professional", label: "Busy professional" },
  { value: "landlord_number_boundary", label: "Landlord number with boundaries" },
];

const PHONE_STRATEGIES = [
  { value: "delayed", label: "Delayed" },
  { value: "immediate", label: "Immediate" },
  { value: "viewing_first", label: "Viewing first" },
  { value: "adaptive", label: "Adaptive" },
];

function fmtSchedule(value?: string, fallback = "-") {
  return value ? fmtDateTime(value) : fallback;
}

function AccountsPage() {
  const {
    data: list = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["accounts"],
    queryFn: getAccounts,
    refetchInterval: 15000,
  });

  const [query, setQuery] = useState("");
  const [lastRunFrom, setLastRunFrom] = useState("");
  const [lastRunTo, setLastRunTo] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Account | null>(null);
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
    queryClient.invalidateQueries({ queryKey: ["workers"] });
    queryClient.invalidateQueries({ queryKey: ["worker-status"] });
  };

  const workerMutation = useMutation({
    mutationFn: controlAccountWorker,
    onSuccess: (_data, variables) => {
      invalidate();
      toast.success(`Worker ${variables.action} requested`);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Worker action failed"),
  });

  const saveMutation = useMutation({
    mutationFn: (account: Partial<Account> & { password?: string; id?: string }) =>
      account.id
        ? updateAccount(account as Partial<Account> & { id: string })
        : createAccount(account),
    onSuccess: () => {
      invalidate();
      toast.success("Account saved");
      setOpen(false);
      setEditing(null);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Could not save account"),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAccount,
    onSuccess: () => {
      invalidate();
      toast.success("Account deleted");
      setDeleteTarget(null);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Could not delete account"),
  });

  const proxyMutation = useMutation({
    mutationFn: testAccountProxy,
    onSuccess: (result) => {
      invalidate();
      toast[result.ok ? "success" : "error"](
        result.ok
          ? `Proxy healthy${result.latency ? ` in ${result.latency}s` : ""}`
          : result.detail || result.error || "Proxy connection failed",
      );
    },
  });

  const sessionMutation = useMutation({
    mutationFn: ({ id, mode }: { id: string; mode: "refresh" | "invalidate" }) =>
      mode === "refresh" ? refreshAccountSession(id) : invalidateAccountSession(id),
    onSuccess: (_result, variables) => {
      invalidate();
      toast.success(
        variables.mode === "refresh" ? "Session refresh queued" : "Session invalidated",
      );
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Session action failed"),
  });

  const filtered = list.filter((a) => {
    if (!a.email.toLowerCase().includes(query.toLowerCase())) return false;
    const lastRun = a.lastRunAt || a.workerLastCompletedAt;
    if (lastRunFrom && lastRun && new Date(lastRun) < new Date(lastRunFrom)) return false;
    if (lastRunTo && lastRun && new Date(lastRun) > new Date(lastRunTo + "T23:59:59")) return false;
    return true;
  });
  const save = (data: Partial<Account> & { password?: string }) => {
    saveMutation.mutate({ ...editing, ...data });
  };

  if (isLoading) {
    return <PageHeader title="Accounts" description="Loading accounts from the backend..." />;
  }

  if (error) {
    return (
      <PageHeader
        title="Accounts"
        description="Could not load accounts. Check VITE_API_BASE_URL and the FastAPI service."
      />
    );
  }

  return (
    <>
      <PageHeader
        title="Accounts"
        description="OpenRent accounts, proxies, Playwright sessions, and worker lifecycle."
        actions={
          <>
            <Input
              placeholder="Search email..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-9 w-full sm:w-56"
            />
            <Input
              type="date"
              title="Last run from"
              value={lastRunFrom}
              onChange={(e) => setLastRunFrom(e.target.value)}
              className="h-9 w-36"
            />
            <Input
              type="date"
              title="Last run to"
              value={lastRunTo}
              onChange={(e) => setLastRunTo(e.target.value)}
              className="h-9 w-36"
            />
            <Button
              onClick={() => {
                setEditing(null);
                setOpen(true);
              }}
              size="sm"
            >
              <Plus className="size-4" /> Add Account
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.open("https://signup.live.com", "_blank", "noopener,noreferrer")}
            >
              <Plus className="size-4" /> Create Outlook Account
            </Button>
          </>
        }
      />

      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Email</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Daily usage</TableHead>
              <TableHead>Last Run</TableHead>
              <TableHead>Next Run</TableHead>
              <TableHead>Assigned Proxy</TableHead>
              <TableHead>Persona</TableHead>
              <TableHead>Lifecycle</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((a) => {
              const pct = a.dailyMessageLimit
                ? (a.messagesSentToday / a.dailyMessageLimit) * 100
                : 0;
              return (
                <TableRow key={a.id}>
                  <TableCell className="font-medium">
                    <div>{a.email}</div>
                    <div className="text-xs text-muted-foreground">
                      {a.sessionFile && a.sessionFile !== "session.json" ? a.sessionFile : `sessions/account_${a.id}.json`}
                    </div>
                  </TableCell>
                  <TableCell>
                    <DotBadge tone={sessionTone[a.sessionStatus]} label={a.sessionStatus} />
                    <div className="mt-1 text-xs text-muted-foreground">
                      {a.sessionLastChecked ? fmtRelative(a.sessionLastChecked) : "not checked"}
                    </div>
                    {a.sessionAuthFailures || a.sessionCaptchaTriggers ? (
                      <div className="mt-1 text-xs text-destructive">
                        {a.sessionAuthFailures} auth / {a.sessionCaptchaTriggers} captcha
                      </div>
                    ) : null}
                    <DotBadge tone={workerTone[a.workerStatus]} label={a.workerStatus} />
                    {a.currentWorkerPhase ? (
                      <div className="mt-1 text-xs text-muted-foreground">
                        {a.currentWorkerPhase}
                      </div>
                    ) : null}
                    {a.retryCount ? (
                      <div className="mt-1 text-xs text-warning">
                        retry {a.retryCount}/{a.retryLimit}
                        {a.retryNextAt ? ` · ${fmtRelative(a.retryNextAt)}` : ""}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell className="min-w-[140px]">
                    <div className="flex items-center gap-2">
                      <Progress value={pct} className="h-1.5 w-24" />
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {a.messagesSentToday}/{a.dailyMessageLimit}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {fmtSchedule(a.lastRunAt || a.workerLastCompletedAt)}
                    {a.workerLastHeartbeat ? <div>{fmtRelative(a.workerLastHeartbeat)}</div> : null}
                    {a.workerJobId ? (
                      <div className="max-w-[120px] truncate">job {a.workerJobId}</div>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {fmtSchedule(a.nextRunAt, "Ready")}
                  </TableCell>
                  <TableCell>
                    <DotBadge tone={proxyTone[a.proxyStatus]} label={a.proxyStatus} />
                    <div className="mt-1 max-w-[180px] truncate text-xs text-muted-foreground">
                      {a.proxyName || "No proxy assigned"}
                    </div>
                    {a.proxyIp || a.proxyLatency ? (
                      <div className="mt-1 max-w-[180px] truncate text-xs text-muted-foreground">
                        {[a.proxyIp, a.proxyLatency ? `${a.proxyLatency}s` : undefined]
                          .filter(Boolean)
                          .join(" / ")}
                      </div>
                    ) : null}
                    {a.proxyLastError ? (
                      <div className="mt-1 max-w-[180px] truncate text-xs text-destructive">
                        {a.proxyLastError}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-xs">
                    <div className="font-medium">
                      {a.personaName || "-"}{" "}
                      {a.personaPartnerName ? `& ${a.personaPartnerName}` : ""}
                    </div>
                    <div className="text-muted-foreground">
                      {[a.personaJob, a.personaPartnerJob, a.homeCity]
                        .filter(Boolean)
                        .join(" / ") || "-"}
                    </div>
                    <div className="text-muted-foreground">
                      {[a.mobileNumber, a.conversationStyle, a.phoneFetchingType]
                        .filter(Boolean)
                        .join(" / ") || "-"}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={a.active}
                      onCheckedChange={(active) =>
                        workerMutation.mutate({
                          accountId: a.id,
                          action: active ? "resume" : "pause",
                        })
                      }
                      aria-label={`${a.email} active state`}
                    />
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="size-8">
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() =>
                            workerMutation.mutate({ accountId: a.id, action: "start" })
                          }
                        >
                          <Play className="size-4" /> Start worker
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => workerMutation.mutate({ accountId: a.id, action: "stop" })}
                        >
                          <Power className="size-4" /> Stop worker
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() =>
                            workerMutation.mutate({ accountId: a.id, action: "pause" })
                          }
                        >
                          <Pause className="size-4" /> Pause account
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() =>
                            workerMutation.mutate({ accountId: a.id, action: "resume" })
                          }
                        >
                          <RefreshCw className="size-4" /> Resume account
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => proxyMutation.mutate(a.id)}>
                          <ShieldCheck className="size-4" /> Test proxy
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => sessionMutation.mutate({ id: a.id, mode: "refresh" })}
                        >
                          <RefreshCw className="size-4" /> Refresh session
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => sessionMutation.mutate({ id: a.id, mode: "invalidate" })}
                        >
                          <KeyRound className="size-4" /> Invalidate session
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onClick={() => {
                            setEditing(a);
                            setOpen(true);
                          }}
                        >
                          Edit account
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive"
                          onClick={() => setDeleteTarget(a)}
                        >
                          <Trash2 className="size-4" /> Delete account
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <AccountDialog
        open={open}
        onOpenChange={setOpen}
        editing={editing}
        onSave={save}
        saving={saveMutation.isPending}
      />
      <AlertDialog open={!!deleteTarget} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete account?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the account and its related search profiles, listings, conversations, and
              messages.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function AccountDialog({
  open,
  onOpenChange,
  editing,
  onSave,
  saving,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  editing: Account | null;
  onSave: (data: Partial<Account> & { password?: string }) => void;
  saving: boolean;
}) {
  const { data: proxies = [] } = useQuery<Proxy[]>({
    queryKey: ["proxies"],
    queryFn: getProxies,
  });
  const [data, setData] = useState<Partial<Account> & { password?: string }>({});

  useEffect(() => {
    if (open) {
      setData({
        email: editing?.email ?? "",
        dailyMessageLimit: editing?.dailyMessageLimit ?? 5,
        mobileNumber: editing?.mobileNumber ?? "",
        phoneFetchingType: editing?.phoneFetchingType ?? "",
        conversationStyle: editing?.conversationStyle ?? "",
        messageStrategy: editing?.messageStrategy ?? "",
        escalationBehavior: editing?.escalationBehavior ?? "",
        conversationGoal: editing?.conversationGoal ?? "",
        sessionFile: editing?.sessionFile ?? "",
        initialMessage: editing?.initialMessage ?? "",
        proxyId: editing?.proxyId ?? "",
        active: editing?.active ?? true,
        password: "",
      });
    }
  }, [open, editing]);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit account" : "Add account"}</DialogTitle>
          <DialogDescription>
            Configure credentials, proxy assignment, Playwright session file, and automation limits.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2 sm:grid-cols-2">
          <Field label="Email">
            <Input
              value={data.email ?? ""}
              onChange={(e) => setData({ ...data, email: e.target.value })}
            />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              value={data.password ?? ""}
              onChange={(e) => setData({ ...data, password: e.target.value })}
              placeholder={editing ? "Leave blank to keep existing" : "OpenRent password"}
            />
          </Field>
          <Field label="Daily message limit">
            <Input
              type="number"
              value={data.dailyMessageLimit ?? 5}
              onChange={(e) => setData({ ...data, dailyMessageLimit: Number(e.target.value) })}
            />
          </Field>
          <Field label="Session file">
            <Input
              value={data.sessionFile ?? ""}
              onChange={(e) => setData({ ...data, sessionFile: e.target.value })}
              placeholder="Auto-generated (sessions/account_<id>.json)"
            />
          </Field>
          <Field label="Proxy">
            <Select
              value={data.proxyId ?? ""}
              onValueChange={(v) => setData({ ...data, proxyId: v === "__none__" ? "" : v })}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="No proxy" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">No proxy</SelectItem>
                {proxies.filter((p) => p.isActive).map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name} — {p.host}:{p.port}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Mobile number">
            <Input
              value={data.mobileNumber ?? ""}
              onChange={(e) => setData({ ...data, mobileNumber: e.target.value })}
            />
          </Field>

          <Field label="Phone strategy">
            <Select
              value={data.phoneFetchingType ?? ""}
              onValueChange={(v) => setData({ ...data, phoneFetchingType: v })}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select strategy" />
              </SelectTrigger>
              <SelectContent>
                {PHONE_STRATEGIES.map((s) => (
                  <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field label="Conversation style">
            <Select
              value={data.conversationStyle ?? ""}
              onValueChange={(v) => setData({ ...data, conversationStyle: v })}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select style" />
              </SelectTrigger>
              <SelectContent>
                {CONVERSATION_STYLES.map((s) => (
                  <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field label="Message strategy">
            <Select
              value={data.messageStrategy ?? ""}
              onValueChange={(v) => setData({ ...data, messageStrategy: v })}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select strategy" />
              </SelectTrigger>
              <SelectContent>
                {CONVERSATION_STYLES.map((s) => (
                  <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field label="Escalation behavior">
            <Input
              value={data.escalationBehavior ?? ""}
              onChange={(e) => setData({ ...data, escalationBehavior: e.target.value })}
            />
          </Field>
          <div className="space-y-1.5 sm:col-span-2">
            <Label>Initial message</Label>
            <Input
              value={data.initialMessage ?? ""}
              onChange={(e) => setData({ ...data, initialMessage: e.target.value })}
            />
          </div>

        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              const payload = { ...data };
              if (!payload.password) delete payload.password;
              if (!payload.proxyPassword && editing) delete payload.proxyPassword;
              onSave(payload);
            }}
            disabled={saving || !data.email}
          >
            {saving ? "Saving..." : editing ? "Save" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
