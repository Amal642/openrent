import { createFileRoute } from "@tanstack/react-router";
import { Trash2, AlertTriangle, Phone, HardDrive, RotateCcw } from "lucide-react";
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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { getDeletedAccounts, hardDeleteAccount, restoreAccount, softDeleteAccount } from "@/lib/api";
import type { DeletedAccount } from "@/lib/types";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

export const Route = createFileRoute("/deleted-accounts")({
  head: () => ({
    meta: [{ title: "Deleted Accounts — Land Royal" }],
  }),
  component: DeletedAccountsPage,
});

function DeletedAccountsPage() {
  const queryClient = useQueryClient();

  const { data: accounts = [], isLoading } = useQuery<DeletedAccount[]>({
    queryKey: ["deleted-accounts"],
    queryFn: getDeletedAccounts,
    refetchInterval: 30000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["deleted-accounts"] });
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
  };

  const hardDeleteMutation = useMutation({
    mutationFn: (id: string) => hardDeleteAccount(id),
    onSuccess: () => { invalidate(); toast.success("Account and all data permanently deleted"); },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Hard delete failed"),
  });

  const softDeleteMutation = useMutation({
    mutationFn: (id: string) => softDeleteAccount(id),
    onSuccess: () => { invalidate(); toast.success("Account removed — phone leads preserved"); },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Soft delete failed"),
  });

  const restoreMutation = useMutation({
    mutationFn: (id: string) => restoreAccount(id),
    onSuccess: () => { invalidate(); toast.success("Account restored and set to active"); },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Restore failed"),
  });

  if (isLoading) return <PageHeader title="Deleted Accounts" description="Loading..." />;

  return (
    <>
      <PageHeader
        title="Deleted Accounts"
        description={
          accounts.length
            ? `${accounts.length} soft-deleted account(s). Choose Hard Delete to erase all data, or Soft Delete to keep phone leads.`
            : "No deleted accounts."
        }
      />

      {accounts.length === 0 ? (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground">
          <Trash2 className="mx-auto mb-3 size-8" />
          <p className="font-medium">No deleted accounts</p>
          <p className="mt-1 text-sm">
            Accounts you delete from the Accounts page will appear here before permanent removal.
          </p>
        </div>
      ) : (
        <>
          <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <AlertTriangle className="mr-2 inline size-4" />
            <strong>Hard Delete</strong> removes the account and every associated record permanently.{" "}
            <strong>Soft Delete</strong> removes the account credentials but keeps conversations where a phone number was captured.
          </div>
          <div className="rounded-lg border bg-card overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40">
                  <TableHead>Email</TableHead>
                  <TableHead>Proxy</TableHead>
                  <TableHead>Messages Sent</TableHead>
                  <TableHead>Phones Captured</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Deleted</TableHead>
                  <TableHead className="text-right min-w-[280px]">Actions</TableHead>
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
                      {account.messagesSent ?? "—"}
                    </TableCell>
                    <TableCell>
                      {account.phonesCaptured != null ? (
                        <span className={account.phonesCaptured > 0 ? "flex items-center gap-1 font-medium text-green-600" : "tabular-nums"}>
                          {account.phonesCaptured > 0 && <Phone className="size-3" />}
                          {account.phonesCaptured}
                        </span>
                      ) : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                      {account.createdAt ? fmtDateTime(account.createdAt) : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                      {account.deletedAt ? fmtRelative(account.deletedAt) : "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-green-600 border-green-300 hover:bg-green-50"
                          onClick={() => restoreMutation.mutate(account.id)}
                          disabled={restoreMutation.isPending}
                          title="Restore account — bring it back to active"
                        >
                          <RotateCcw className="size-4" />
                          Restore
                        </Button>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="outline"
                              size="sm"
                              className="text-amber-600 border-amber-300 hover:bg-amber-50"
                              disabled={softDeleteMutation.isPending}
                            >
                              <Phone className="size-4" />
                              Soft Delete
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Soft Delete — keep phone leads?</AlertDialogTitle>
                              <AlertDialogDescription>
                                This removes <strong>{account.email}</strong> and all conversations
                                that did <em>not</em> capture a phone number.
                                {(account.phonesCaptured ?? 0) > 0 ? (
                                  <> <strong>{account.phonesCaptured} conversation(s) with phone numbers</strong> and
                                  their messages will be kept.</>
                                ) : (
                                  <> No phone numbers were captured, so this will behave the same as Hard Delete.</>
                                )}
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction
                                className="bg-amber-600 hover:bg-amber-700"
                                onClick={() => softDeleteMutation.mutate(account.id)}
                              >
                                Soft Delete
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>

                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="outline"
                              size="sm"
                              className="text-destructive border-destructive/30 hover:bg-destructive/10"
                              disabled={hardDeleteMutation.isPending}
                            >
                              <HardDrive className="size-4" />
                              Hard Delete
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Permanently delete everything?</AlertDialogTitle>
                              <AlertDialogDescription>
                                This will permanently delete <strong>{account.email}</strong> and
                                ALL associated data — conversations, messages, phone numbers, leads.
                                {(account.phonesCaptured ?? 0) > 0 && (
                                  <span className="mt-1 block font-semibold text-destructive">
                                    Warning: {account.phonesCaptured} captured phone number(s) will be lost.
                                  </span>
                                )}
                                This cannot be undone.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction
                                className="bg-destructive hover:bg-destructive/90"
                                onClick={() => hardDeleteMutation.mutate(account.id)}
                              >
                                Delete permanently
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </>
  );
}
