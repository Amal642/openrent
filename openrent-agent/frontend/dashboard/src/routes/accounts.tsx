import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { MoreHorizontal, Plus, RefreshCw } from "lucide-react";
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
import { Label } from "@/components/ui/label";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createAccount, getAccounts, runAccountWorker, updateAccount } from "@/lib/api";
import type { Account, ProxyStatus, SessionStatus, WorkerStatus } from "@/lib/types";
import { fmtRelative } from "@/lib/format";
import { toast } from "sonner";

export const Route = createFileRoute("/accounts")({
  head: () => ({
    meta: [
      { title: "Accounts — RentPilot" },
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
const proxyTone: Record<ProxyStatus, "success" | "warning" | "destructive"> = {
  ok: "success",
  degraded: "warning",
  down: "destructive",
};

function AccountsPage() {
  const {
    data: list = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["accounts"],
    queryFn: getAccounts,
  });

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const queryClient = useQueryClient();
  const runMutation = useMutation({
    mutationFn: runAccountWorker,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      toast.success("Worker run queued");
    },
    onError: () => toast.error("Could not queue worker run"),
  });
  const saveMutation = useMutation({
    mutationFn: (account: Partial<Account> & { password?: string; sessionFile?: string; id?: string }) =>
      account.id
        ? updateAccount(account as Account & { password?: string; sessionFile?: string })
        : createAccount(account),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      toast.success("Account saved");
    },
    onError: () => toast.error("Could not save account"),
  });

  const filtered = list.filter((a) => a.email.toLowerCase().includes(query.toLowerCase()));
  const save = (data: Partial<Account> & { password?: string; sessionFile?: string }) => {
    saveMutation.mutate({ ...editing, ...data });
    setOpen(false);
    setEditing(null);
  };

  if (isLoading) {
    return (
      <PageHeader title="Accounts" description="Loading accounts from OpenRent automation..." />
    );
  }

  if (error) {
    return (
      <PageHeader
        title="Accounts"
        description="Could not load accounts. Check that the FastAPI server is running on port 8000."
      />
    );
  }

  return (
    <>
      <PageHeader
        title="Accounts"
        description="OpenRent worker accounts, session health, and outreach controls."
        actions={
          <>
            <Input
              placeholder="Search email…"
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

      <div className="rounded-lg border bg-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Email</TableHead>
              <TableHead>Session</TableHead>
              <TableHead>Worker</TableHead>
              <TableHead>Daily usage</TableHead>
              <TableHead>Persona</TableHead>
              <TableHead>Phase</TableHead>
              <TableHead>Proxy</TableHead>
              <TableHead>AI</TableHead>
              <TableHead>Outreach</TableHead>
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
                  <TableCell className="font-medium">{a.email}</TableCell>
                  <TableCell>
                    <DotBadge tone={sessionTone[a.sessionStatus]} label={a.sessionStatus} />
                  </TableCell>
                  <TableCell>
                    <DotBadge tone={workerTone[a.workerStatus]} label={a.workerStatus} />
                  </TableCell>
                  <TableCell className="min-w-[140px]">
                    <div className="flex items-center gap-2">
                      <Progress value={pct} className="h-1.5 w-24" />
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {a.messagesSentToday}/{a.dailyMessageLimit}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">
                    <div className="font-medium">
                      {a.personaName || "—"} {a.personaPartnerName ? `& ${a.personaPartnerName}` : ""}
                    </div>
                    <div className="text-muted-foreground">
                      {[a.personaJob, a.personaPartnerJob, a.homeCity].filter(Boolean).join(" · ") || "—"}
                    </div>
                    <div className="text-muted-foreground">
                      {[a.mobileNumber, a.conversationStyle, a.phoneFetchingType].filter(Boolean).join(" · ") || "—"}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {a.currentWorkerPhase || "idle"}
                    {a.workerLastHeartbeat ? (
                      <div>{fmtRelative(a.workerLastHeartbeat)}</div>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <DotBadge tone={proxyTone[a.proxyStatus]} label={a.proxyStatus} />
                  </TableCell>
                  <TableCell>
                    <Switch checked={a.aiEnabled} disabled />
                  </TableCell>
                  <TableCell>
                    <Switch checked={a.outreachEnabled} disabled />
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {fmtRelative(a.lastLoginAt)}
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
                          onClick={() => runMutation.mutate(a.id)}
                        >
                          <RefreshCw className="size-4" /> Run worker once
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

      <AccountDialog open={open} onOpenChange={setOpen} editing={editing} onSave={save} />
    </>
  );
}

function AccountDialog({
  open,
  onOpenChange,
  editing,
  onSave,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  editing: Account | null;
  onSave: (data: Partial<Account>) => void;
}) {
  const [email, setEmail] = useState(editing?.email ?? "");
  const [limit, setLimit] = useState(editing?.dailyMessageLimit ?? 50);
  const [mobileNumber, setMobileNumber] = useState(editing?.mobileNumber ?? "");
  const [phoneFetchingType, setPhoneFetchingType] = useState(editing?.phoneFetchingType ?? "");
  const [conversationStyle, setConversationStyle] = useState(editing?.conversationStyle ?? "");
  const [password, setPassword] = useState("");
  const [sessionFile, setSessionFile] = useState("session.json");
  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (v) {
          setEmail(editing?.email ?? "");
          setLimit(editing?.dailyMessageLimit ?? 50);
          setMobileNumber(editing?.mobileNumber ?? "");
          setPhoneFetchingType(editing?.phoneFetchingType ?? "");
          setConversationStyle(editing?.conversationStyle ?? "");
          setPassword("");
          setSessionFile("session.json");
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? "Edit account" : "Add account"}</DialogTitle>
          <DialogDescription>
            Configure OpenRent worker account credentials and limits.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label>Email</Label>
            <Input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="ops@yourcompany.io"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Daily message limit</Label>
            <Input type="number" value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
          </div>
          <div className="space-y-1.5">
            <Label>Mobile number</Label>
            <Input
              value={mobileNumber}
              onChange={(e) => setMobileNumber(e.target.value)}
              placeholder="Use the account's assigned seed mobile"
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Phone strategy</Label>
              <Input
                value={phoneFetchingType}
                onChange={(e) => setPhoneFetchingType(e.target.value)}
                placeholder="delayed"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Conversation style</Label>
              <Input
                value={conversationStyle}
                onChange={(e) => setConversationStyle(e.target.value)}
                placeholder="friendly_viewing"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Password</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={editing ? "Leave blank to keep existing password" : "OpenRent password"}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Session file</Label>
            <Input value={sessionFile} onChange={(e) => setSessionFile(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() =>
              onSave({
                email,
                dailyMessageLimit: limit,
                mobileNumber: mobileNumber || undefined,
                phoneFetchingType: phoneFetchingType || undefined,
                conversationStyle: conversationStyle || undefined,
                ...(password ? { password } : {}),
                sessionFile,
              })
            }
          >
            {editing ? "Save" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
