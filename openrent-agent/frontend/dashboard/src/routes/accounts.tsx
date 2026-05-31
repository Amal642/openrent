import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  controlAccountWorker,
  createAccount,
  deleteAccount,
  getAccounts,
  invalidateAccountSession,
  refreshAccountSession,
  testAccountProxy,
  updateAccount,
} from "@/lib/api";
import type { Account, ProxyStatus, SessionStatus, WorkerStatus } from "@/lib/types";
import { fmtRelative } from "@/lib/format";
import { toast } from "sonner";

export const Route = createFileRoute("/accounts")({
  head: () => ({
    meta: [
      { title: "Accounts - RentPilot" },
      { name: "description", content: "Manage OpenRent worker accounts." },
    ],
  }),
  component: AccountsPage,
});

const sessionTone: Record<SessionStatus, "success" | "warning" | "destructive" | "info"> = {
  active: "success",
  logging_in: "info",
  expired: "warning",
  error: "destructive",
};
const workerTone: Record<WorkerStatus, "success" | "warning" | "destructive" | "muted"> = {
  running: "success",
  idle: "muted",
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
      account.id ? updateAccount(account as Partial<Account> & { id: string }) : createAccount(account),
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
        result.ok ? "Proxy connection succeeded" : result.detail || "Proxy connection failed",
      );
    },
  });

  const sessionMutation = useMutation({
    mutationFn: ({ id, mode }: { id: string; mode: "refresh" | "invalidate" }) =>
      mode === "refresh" ? refreshAccountSession(id) : invalidateAccountSession(id),
    onSuccess: (_result, variables) => {
      invalidate();
      toast.success(variables.mode === "refresh" ? "Session refresh queued" : "Session invalidated");
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Session action failed"),
  });

  const filtered = list.filter((a) => a.email.toLowerCase().includes(query.toLowerCase()));
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
              className="h-9 w-56"
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
          </>
        }
      />

      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Email</TableHead>
              <TableHead>Session</TableHead>
              <TableHead>Worker</TableHead>
              <TableHead>Daily usage</TableHead>
              <TableHead>Proxy</TableHead>
              <TableHead>Persona</TableHead>
              <TableHead>Lifecycle</TableHead>
              <TableHead>Last login</TableHead>
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
                    <div className="text-xs text-muted-foreground">{a.sessionFile || "session.json"}</div>
                  </TableCell>
                  <TableCell>
                    <DotBadge tone={sessionTone[a.sessionStatus]} label={a.sessionStatus} />
                  </TableCell>
                  <TableCell>
                    <DotBadge tone={workerTone[a.workerStatus]} label={a.workerStatus} />
                    {a.currentWorkerPhase ? (
                      <div className="mt-1 text-xs text-muted-foreground">{a.currentWorkerPhase}</div>
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
                  <TableCell>
                    <DotBadge tone={proxyTone[a.proxyStatus]} label={a.proxyStatus} />
                    <div className="mt-1 max-w-[180px] truncate text-xs text-muted-foreground">
                      {a.proxyServer || "No proxy assigned"}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">
                    <div className="font-medium">
                      {a.personaName || "-"} {a.personaPartnerName ? `& ${a.personaPartnerName}` : ""}
                    </div>
                    <div className="text-muted-foreground">
                      {[a.personaJob, a.personaPartnerJob, a.homeCity].filter(Boolean).join(" / ") || "-"}
                    </div>
                    <div className="text-muted-foreground">
                      {[a.mobileNumber, a.conversationStyle, a.phoneFetchingType].filter(Boolean).join(" / ") || "-"}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={a.active}
                      onCheckedChange={(active) =>
                        workerMutation.mutate({ accountId: a.id, action: active ? "resume" : "pause" })
                      }
                      aria-label={`${a.email} active state`}
                    />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {fmtRelative(a.lastLoginAt)}
                    {a.workerLastHeartbeat ? <div>{fmtRelative(a.workerLastHeartbeat)}</div> : null}
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="size-8">
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => workerMutation.mutate({ accountId: a.id, action: "start" })}>
                          <Play className="size-4" /> Start worker
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => workerMutation.mutate({ accountId: a.id, action: "stop" })}>
                          <Power className="size-4" /> Stop worker
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => workerMutation.mutate({ accountId: a.id, action: "pause" })}>
                          <Pause className="size-4" /> Pause account
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => workerMutation.mutate({ accountId: a.id, action: "resume" })}>
                          <RefreshCw className="size-4" /> Resume account
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => proxyMutation.mutate(a.id)}>
                          <ShieldCheck className="size-4" /> Test proxy
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => sessionMutation.mutate({ id: a.id, mode: "refresh" })}>
                          <RefreshCw className="size-4" /> Refresh session
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => sessionMutation.mutate({ id: a.id, mode: "invalidate" })}>
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
                        <DropdownMenuItem className="text-destructive" onClick={() => setDeleteTarget(a)}>
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
              This removes the account and its related search profiles, listings, conversations, and messages.
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
  const [data, setData] = useState<Partial<Account> & { password?: string }>({});
  const reset = () =>
    setData({
      email: editing?.email ?? "",
      dailyMessageLimit: editing?.dailyMessageLimit ?? 8,
      mobileNumber: editing?.mobileNumber ?? "",
      phoneFetchingType: editing?.phoneFetchingType ?? "",
      conversationStyle: editing?.conversationStyle ?? "",
      messageStrategy: editing?.messageStrategy ?? "",
      escalationBehavior: editing?.escalationBehavior ?? "",
      conversationGoal: editing?.conversationGoal ?? "",
      sessionFile: editing?.sessionFile ?? "session.json",
      initialMessage: editing?.initialMessage ?? "",
      proxyServer: editing?.proxyServer ?? "",
      proxyUsername: editing?.proxyUsername ?? "",
      proxyPassword: "",
      active: editing?.active ?? true,
      password: "",
    });

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (v) reset();
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit account" : "Add account"}</DialogTitle>
          <DialogDescription>
            Configure credentials, proxy assignment, Playwright session file, and automation limits.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2 sm:grid-cols-2">
          <Field label="Email">
            <Input value={data.email ?? ""} onChange={(e) => setData({ ...data, email: e.target.value })} />
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
              value={data.dailyMessageLimit ?? 8}
              onChange={(e) => setData({ ...data, dailyMessageLimit: Number(e.target.value) })}
            />
          </Field>
          <Field label="Session file">
            <Input
              value={data.sessionFile ?? ""}
              onChange={(e) => setData({ ...data, sessionFile: e.target.value })}
            />
          </Field>
          <Field label="Proxy server">
            <Input
              value={data.proxyServer ?? ""}
              onChange={(e) => setData({ ...data, proxyServer: e.target.value })}
              placeholder="http://host:port"
            />
          </Field>
          <Field label="Proxy username">
            <Input
              value={data.proxyUsername ?? ""}
              onChange={(e) => setData({ ...data, proxyUsername: e.target.value })}
            />
          </Field>
          <Field label="Proxy password">
            <Input
              type="password"
              value={data.proxyPassword ?? ""}
              onChange={(e) => setData({ ...data, proxyPassword: e.target.value })}
              placeholder={editing ? "Leave blank to keep existing" : ""}
            />
          </Field>
          <Field label="Mobile number">
            <Input
              value={data.mobileNumber ?? ""}
              onChange={(e) => setData({ ...data, mobileNumber: e.target.value })}
            />
          </Field>
          <Field label="Phone strategy">
            <Input
              value={data.phoneFetchingType ?? ""}
              onChange={(e) => setData({ ...data, phoneFetchingType: e.target.value })}
              placeholder="delayed"
            />
          </Field>
          <Field label="Conversation style">
            <Input
              value={data.conversationStyle ?? ""}
              onChange={(e) => setData({ ...data, conversationStyle: e.target.value })}
              placeholder="friendly_viewing"
            />
          </Field>
          <Field label="Message strategy">
            <Input
              value={data.messageStrategy ?? ""}
              onChange={(e) => setData({ ...data, messageStrategy: e.target.value })}
            />
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
