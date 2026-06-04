import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Plus, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { PageHeader } from "../components/page-header";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Switch } from "../components/ui/switch";
import { Label } from "../components/ui/label";
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
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  createSearchProfile,
  deleteSearchProfile,
  getAccounts,
  getSearchProfiles,
  updateSearchProfile,
} from "../lib/api";
import type { Account, SearchProfile } from "../lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { fmtMoney } from "../lib/format";

export const Route = createFileRoute("/search-profiles")({
  head: () => ({
    meta: [
      { title: "Search Profiles — RentPilot" },
      { name: "description", content: "Per-account property discovery profiles." },
    ],
  }),
  component: SearchProfilesPage,
});

function SearchProfilesPage() {
  const [accountFilter, setAccountFilter] = useState<string>("all");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<SearchProfile | null>(null);
  const queryClient = useQueryClient();
  const { data: accounts = [] } = useQuery({
    queryKey: ["accounts"],
    queryFn: getAccounts,
  });
  const {
    data: profiles = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["search-profiles"],
    queryFn: getSearchProfiles,
  });

  const invalidateProfiles = () => {
    queryClient.invalidateQueries({ queryKey: ["search-profiles"] });
    queryClient.invalidateQueries({ queryKey: ["leads"] });
  };

  const createMutation = useMutation({
    mutationFn: createSearchProfile,
    onSuccess: () => {
      invalidateProfiles();
      toast.success("Profile added");
    },
    onError: () => toast.error("Could not add profile"),
  });

  const updateMutation = useMutation({
    mutationFn: updateSearchProfile,
    onSuccess: () => {
      invalidateProfiles();
      toast.success("Profile updated");
    },
    onError: () => toast.error("Could not update profile"),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteSearchProfile,
    onSuccess: () => {
      invalidateProfiles();
      toast.success("Profile deactivated");
    },
    onError: () => toast.error("Could not deactivate profile"),
  });

  const filtered =
    accountFilter === "all" ? profiles : profiles.filter((s) => s.accountId === accountFilter);
  const accountEmail = (id: string) => accounts.find((a) => a.id === id)?.email ?? id;

  const save = (data: Partial<SearchProfile>) => {
    const profile = {
      ...editing,
      ...data,
      accountId: data.accountId || editing?.accountId || accounts[0]?.id || "",
      location: data.location || editing?.location || "Unspecified",
      priceMin: data.priceMin ?? editing?.priceMin ?? 0,
      priceMax: data.priceMax ?? editing?.priceMax ?? 0,
      area: data.area ?? editing?.area ?? 0,
      bedroomsMin: data.bedroomsMin ?? editing?.bedroomsMin ?? 0,
      bedroomsMax: data.bedroomsMax ?? editing?.bedroomsMax ?? 0,
      petsAllowed: data.petsAllowed ?? editing?.petsAllowed ?? false,
      active: data.active ?? editing?.active ?? true,
    };

    if (editing) {
      updateMutation.mutate({ ...profile, id: editing.id });
    } else {
      createMutation.mutate(profile);
    }

    setOpen(false);
    setEditing(null);
  };

  if (isLoading) {
    return (
      <PageHeader
        title="Search Profiles"
        description="Loading profiles from OpenRent automation..."
      />
    );
  }

  if (error) {
    return (
      <PageHeader
        title="Search Profiles"
        description="Could not load search profiles. Check that the FastAPI server is running on port 8000."
      />
    );
  }

  return (
    <>
      <PageHeader
        title="Search Profiles"
        description="Define what each account searches for on OpenRent."
        actions={
          <>
            <Select value={accountFilter} onValueChange={setAccountFilter}>
              <SelectTrigger className="h-9 w-56">
                <SelectValue />
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
            <Button
              size="sm"
              onClick={() => {
                setEditing(null);
                setOpen(true);
              }}
            >
              <Plus className="size-4" /> Add Profile
            </Button>
          </>
        }
      />

      <div className="rounded-lg border bg-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Account</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>Radius</TableHead>
              <TableHead>Price range</TableHead>
              <TableHead>Bedrooms</TableHead>
              <TableHead>Pets</TableHead>
              <TableHead>Active</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="text-sm text-muted-foreground">
                  {accountEmail(s.accountId)}
                </TableCell>
                <TableCell className="font-medium">{s.location}</TableCell>
                <TableCell className="tabular-nums">{s.area || "-"} mi</TableCell>
                <TableCell className="tabular-nums">
                  {fmtMoney(s.priceMin)} – {fmtMoney(s.priceMax)}
                </TableCell>
                <TableCell className="tabular-nums">
                  {s.bedroomsMin}–{s.bedroomsMax}
                </TableCell>
                <TableCell>{s.petsAllowed ? "Yes" : "No"}</TableCell>
                <TableCell>
                  <Switch
                    checked={s.active}
                    onCheckedChange={(v) => updateMutation.mutate({ ...s, active: v })}
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
                        onClick={() => {
                          setEditing(s);
                          setOpen(true);
                        }}
                      >
                        <Pencil className="size-4" /> Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        className="text-destructive"
                        onClick={() => deleteMutation.mutate(s.id)}
                      >
                        <Trash2 className="size-4" /> Deactivate
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ProfileDialog
        open={open}
        onOpenChange={setOpen}
        editing={editing}
        accounts={accounts}
        onSave={save}
      />
    </>
  );
}

function ProfileDialog({
  open,
  onOpenChange,
  editing,
  accounts,
  onSave,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  editing: SearchProfile | null;
  accounts: Account[];
  onSave: (data: Partial<SearchProfile>) => void;
}) {
  const [data, setData] = useState<Partial<SearchProfile>>(editing ?? {});
  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (v) setData(editing ?? {});
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? "Edit profile" : "Add profile"}</DialogTitle>
          <DialogDescription>Search criteria for property discovery.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3 py-2">
          <div className="col-span-2 space-y-1.5">
            <Label>Account</Label>
            <Select
              value={data.accountId}
              onValueChange={(v) => setData({ ...data, accountId: v })}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select account" />
              </SelectTrigger>
              <SelectContent>
                {accounts.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.email}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="col-span-2 space-y-1.5">
            <Label>City</Label>
            <Select
              value={data.location ?? ""}
              onValueChange={(v) => setData({ ...data, location: v })}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select city" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Manchester">Manchester</SelectItem>
                <SelectItem value="Greater Manchester">Greater Manchester</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Search radius</Label>
            <Input
              type="number"
              value={data.area ?? ""}
              onChange={(e) => setData({ ...data, area: Number(e.target.value) })}
              placeholder="Miles"
            />
          </div>
          <div className="space-y-1.5">
            <Label>Price min</Label>
            <Input
              type="number"
              value={data.priceMin ?? ""}
              onChange={(e) => setData({ ...data, priceMin: Number(e.target.value) })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Price max</Label>
            <Input
              type="number"
              value={data.priceMax ?? ""}
              onChange={(e) => setData({ ...data, priceMax: Number(e.target.value) })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Bedrooms min</Label>
            <Input
              type="number"
              value={data.bedroomsMin ?? ""}
              onChange={(e) => setData({ ...data, bedroomsMin: Number(e.target.value) })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Bedrooms max</Label>
            <Input
              type="number"
              value={data.bedroomsMax ?? ""}
              onChange={(e) => setData({ ...data, bedroomsMax: Number(e.target.value) })}
            />
          </div>
          <div className="col-span-2 flex items-center justify-between rounded-md border p-3">
            <div>
              <div className="text-sm font-medium">Pets allowed</div>
              <div className="text-xs text-muted-foreground">
                Only show listings that allow pets
              </div>
            </div>
            <Switch
              checked={!!data.petsAllowed}
              onCheckedChange={(v) => setData({ ...data, petsAllowed: v })}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => onSave(data)}>{editing ? "Save" : "Create"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
