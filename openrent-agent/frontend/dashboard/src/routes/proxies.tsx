import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { MoreHorizontal, Plus, Pencil, Trash2, PowerOff } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
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
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createProxy, deleteProxy, getProxies, updateProxy } from "@/lib/api";
import type { Proxy } from "@/lib/types";
import { toast } from "sonner";

export const Route = createFileRoute("/proxies")({
  head: () => ({
    meta: [
      { title: "Proxies - RentPilot" },
      { name: "description", content: "Manage shared proxy pool." },
    ],
  }),
  component: ProxiesPage,
});

function ProxiesPage() {
  const queryClient = useQueryClient();
  const { data: proxies = [], isLoading, error } = useQuery({
    queryKey: ["proxies"],
    queryFn: getProxies,
    refetchInterval: 30_000,
  });

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Proxy | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Proxy | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["proxies"] });

  const saveMutation = useMutation({
    mutationFn: async (data: ProxyFormData) => {
      if (data.id) {
        return updateProxy(data.id, data);
      }
      return createProxy(data);
    },
    onSuccess: () => {
      invalidate();
      toast.success("Proxy saved");
      setOpen(false);
      setEditing(null);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Could not save proxy"),
  });

  const toggleMutation = useMutation({
    mutationFn: (proxy: Proxy) =>
      updateProxy(proxy.id, { isActive: !proxy.isActive }),
    onSuccess: () => {
      invalidate();
      toast.success("Proxy updated");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteProxy(id),
    onSuccess: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      toast.success("Proxy deleted");
      setDeleteTarget(null);
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : "Could not delete proxy";
      toast.error(msg);
    },
  });

  if (isLoading) return <PageHeader title="Proxies" description="Loading proxies..." />;
  if (error) return <PageHeader title="Proxies" description="Could not load proxies." />;

  return (
    <>
      <PageHeader
        title="Proxies"
        description="Shared proxy pool. Assign proxies to accounts instead of entering credentials per account."
        actions={
          <Button
            size="sm"
            onClick={() => {
              setEditing(null);
              setOpen(true);
            }}
          >
            <Plus className="size-4" /> Add Proxy
          </Button>
        }
      />

      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Name</TableHead>
              <TableHead>Host</TableHead>
              <TableHead>Port</TableHead>
              <TableHead>Username</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Accounts</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {proxies.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-sm text-muted-foreground py-8">
                  No proxies yet. Add one to get started.
                </TableCell>
              </TableRow>
            )}
            {proxies.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">{p.name}</TableCell>
                <TableCell className="font-mono text-sm">{p.host}</TableCell>
                <TableCell className="tabular-nums">{p.port || "—"}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {p.username || "—"}
                </TableCell>
                <TableCell>
                  <Switch
                    checked={p.isActive}
                    onCheckedChange={() => toggleMutation.mutate(p)}
                    aria-label={`${p.name} active`}
                  />
                </TableCell>
                <TableCell className="tabular-nums text-muted-foreground">
                  {p.accountCount}
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
                        onClick={() => {
                          setEditing(p);
                          setOpen(true);
                        }}
                      >
                        <Pencil className="size-4" /> Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => toggleMutation.mutate(p)}>
                        <PowerOff className="size-4" />
                        {p.isActive ? "Disable" : "Enable"}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        className="text-destructive"
                        onClick={() => setDeleteTarget(p)}
                      >
                        <Trash2 className="size-4" /> Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ProxyDialog
        open={open}
        onOpenChange={setOpen}
        editing={editing}
        onSave={(data) => saveMutation.mutate(data)}
        saving={saveMutation.isPending}
      />

      <AlertDialog open={!!deleteTarget} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete proxy?</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTarget && deleteTarget.accountCount > 0 ? (
                <>
                  <span className="font-semibold text-destructive">
                    This proxy is assigned to {deleteTarget.accountCount} account
                    {deleteTarget.accountCount !== 1 ? "s" : ""}.
                  </span>{" "}
                  Reassign those accounts to a different proxy before deleting.
                </>
              ) : (
                "This will permanently remove the proxy."
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={!!deleteTarget && deleteTarget.accountCount > 0}
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

interface ProxyFormData {
  id?: string;
  name?: string;
  host: string;
  port: number;
  username?: string;
  password?: string;
  isActive: boolean;
}

function ProxyDialog({
  open,
  onOpenChange,
  editing,
  onSave,
  saving,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  editing: Proxy | null;
  onSave: (data: ProxyFormData) => void;
  saving: boolean;
}) {
  const blank: ProxyFormData = { host: "", port: 0, isActive: true };
  const [data, setData] = useState<ProxyFormData>(blank);

  useEffect(() => {
    if (open) {
      setData(
        editing
          ? {
              id: editing.id,
              name: editing.name,
              host: editing.host,
              port: editing.port,
              username: editing.username ?? "",
              password: "",
              isActive: editing.isActive,
            }
          : blank,
      );
    }
  }, [open, editing]);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit proxy" : "Add proxy"}</DialogTitle>
          <DialogDescription>
            Proxy credentials are stored centrally and assigned to accounts.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2">
          <Field label="Name">
            <Input
              value={data.name ?? ""}
              onChange={(e) => setData({ ...data, name: e.target.value })}
              placeholder="Auto-generated if left blank"
            />
          </Field>
          <Field label="Host">
            <Input
              value={data.host}
              onChange={(e) => setData({ ...data, host: e.target.value })}
              placeholder="gate.decodo.com"
            />
          </Field>
          <Field label="Port">
            <Input
              type="number"
              value={data.port || ""}
              onChange={(e) => setData({ ...data, port: Number(e.target.value) })}
              placeholder="10001"
            />
          </Field>
          <Field label="Username">
            <Input
              value={data.username ?? ""}
              onChange={(e) => setData({ ...data, username: e.target.value })}
            />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              value={data.password ?? ""}
              onChange={(e) => setData({ ...data, password: e.target.value })}
              placeholder={editing ? "Leave blank to keep existing" : ""}
            />
          </Field>
          <div className="flex items-center justify-between rounded-md border px-3 py-2.5">
            <Label className="text-sm">Active</Label>
            <Switch
              checked={data.isActive}
              onCheckedChange={(v) => setData({ ...data, isActive: v })}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => onSave(data)}
            disabled={saving || !data.host}
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
