import { createFileRoute } from "@tanstack/react-router";
import { AlertTriangle, Power, RefreshCw, XCircle } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  clearFailedAccount,
  disableFailedAccount,
  getFailedAccounts,
  retryFailedAccount,
} from "@/lib/api";
import type { FailedAccount } from "@/lib/types";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

export const Route = createFileRoute("/failed-accounts")({
  head: () => ({
    meta: [{ title: "Failed Accounts — Land Royal" }],
  }),
  component: FailedAccountsPage,
});

function FailedAccountsPage() {
  const queryClient = useQueryClient();

  const { data: accounts = [], isLoading } = useQuery<FailedAccount[]>({
    queryKey: ["failed-accounts"],
    queryFn: getFailedAccounts,
    refetchInterval: 30000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["failed-accounts"] });
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
  };

  const retryMutation = useMutation({
    mutationFn: (id: string) => retryFailedAccount(id),
    onSuccess: () => { invalidate(); toast.success("Account queued for retry"); },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Retry failed"),
  });

  const clearMutation = useMutation({
    mutationFn: (id: string) => clearFailedAccount(id),
    onSuccess: () => { invalidate(); toast.success("Failed status cleared"); },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Could not clear status"),
  });

  const disableMutation = useMutation({
    mutationFn: (id: string) => disableFailedAccount(id),
    onSuccess: () => { invalidate(); toast.success("Account disabled"); },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Could not disable account"),
  });

  if (isLoading) return <PageHeader title="Failed Accounts" description="Loading..." />;

  return (
    <>
      <PageHeader
        title="Failed Accounts"
        description={
          accounts.length
            ? `${accounts.length} account(s) marked as failed — 2 days of outreach with no landlord replies.`
            : "No failed accounts. All accounts are performing normally."
        }
      />

      {accounts.length === 0 ? (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground">
          <AlertTriangle className="mx-auto mb-3 size-8 text-success" />
          <p className="font-medium">No failed accounts</p>
          <p className="mt-1 text-sm">
            Accounts are marked as failed when they send messages for 2 consecutive days without
            receiving any landlord replies.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border bg-card overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40">
                <TableHead>Email</TableHead>
                <TableHead>Proxy</TableHead>
                <TableHead>Messages Sent</TableHead>
                <TableHead>Replies Received</TableHead>
                <TableHead>Failure Reason</TableHead>
                <TableHead>Failed At</TableHead>
                <TableHead>Last Run</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {accounts.map((account) => (
                <TableRow key={account.id}>
                  <TableCell className="font-medium">{account.email}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {account.proxyName || account.proxyServer || "—"}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {account.messagesSet ?? "—"}
                  </TableCell>
                  <TableCell className="tabular-nums text-destructive font-medium">
                    {account.repliesReceived ?? "—"}
                  </TableCell>
                  <TableCell className="max-w-xs text-xs text-muted-foreground">
                    {account.failureReason || "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    {account.failedAt ? fmtDateTime(account.failedAt) : "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    {account.lastRunAt ? fmtRelative(account.lastRunAt) : "—"}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => retryMutation.mutate(account.id)}
                        disabled={retryMutation.isPending}
                        title="Retry account"
                      >
                        <RefreshCw className="size-4" />
                        Retry
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => clearMutation.mutate(account.id)}
                        disabled={clearMutation.isPending}
                        title="Remove failed status"
                      >
                        <XCircle className="size-4" />
                        Clear
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="text-destructive"
                        onClick={() => disableMutation.mutate(account.id)}
                        disabled={disableMutation.isPending}
                        title="Disable account"
                      >
                        <Power className="size-4" />
                        Disable
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}
