import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { MapPin, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
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
  createLocation,
  deleteLocation,
  getLocations,
  toggleLocation,
  updateLocation,
} from "@/lib/api";
import type { Location } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

export const Route = createFileRoute("/locations")({
  head: () => ({
    meta: [{ title: "Locations — Land Royal" }],
  }),
  component: LocationsPage,
});

function LocationsPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Location | null>(null);

  const { data: locations = [], isLoading } = useQuery({
    queryKey: ["locations"],
    queryFn: () => getLocations(),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["locations"] });

  const createMutation = useMutation({
    mutationFn: createLocation,
    onSuccess: () => { invalidate(); toast.success("Location created"); },
    onError: () => toast.error("Could not create location"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { name: string; termValue: string; active: boolean } }) =>
      updateLocation(id, data),
    onSuccess: () => { invalidate(); toast.success("Location updated"); },
    onError: () => toast.error("Could not update location"),
  });

  const toggleMutation = useMutation({
    mutationFn: (id: number) => toggleLocation(id),
    onSuccess: () => invalidate(),
    onError: () => toast.error("Could not toggle location"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteLocation(id),
    onSuccess: () => { invalidate(); toast.success("Location deleted"); },
    onError: () => toast.error("Could not delete location"),
  });

  const save = (data: { name: string; termValue: string; active: boolean }) => {
    if (editing) {
      updateMutation.mutate({ id: editing.id, data });
    } else {
      createMutation.mutate(data);
    }
    setOpen(false);
    setEditing(null);
  };

  if (isLoading) return <PageHeader title="Locations" description="Loading..." />;

  return (
    <>
      <PageHeader
        title="Locations"
        description="Manage OpenRent search locations used by Search Profiles."
        actions={
          <Button
            size="sm"
            onClick={() => { setEditing(null); setOpen(true); }}
          >
            <Plus className="size-4" /> Add Location
          </Button>
        }
      />

      <div className="rounded-lg border bg-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Name</TableHead>
              <TableHead>OpenRent Term</TableHead>
              <TableHead>Active</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {locations.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                  No locations yet. Add one to use in Search Profiles.
                </TableCell>
              </TableRow>
            )}
            {locations.map((loc) => (
              <TableRow key={loc.id}>
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    <MapPin className="size-4 text-muted-foreground" />
                    {loc.name}
                  </div>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground font-mono">
                  {loc.termValue}
                </TableCell>
                <TableCell>
                  <Switch
                    checked={loc.active}
                    onCheckedChange={() => toggleMutation.mutate(loc.id)}
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
                        onClick={() => { setEditing(loc); setOpen(true); }}
                      >
                        <Pencil className="size-4" /> Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        className="text-destructive"
                        onClick={() => deleteMutation.mutate(loc.id)}
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

      <LocationDialog
        open={open}
        onOpenChange={setOpen}
        editing={editing}
        onSave={save}
      />
    </>
  );
}

function LocationDialog({
  open,
  onOpenChange,
  editing,
  onSave,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  editing: Location | null;
  onSave: (data: { name: string; termValue: string; active: boolean }) => void;
}) {
  const [name, setName] = useState("");
  const [termValue, setTermValue] = useState("");
  const [active, setActive] = useState(true);

  useEffect(() => {
    if (open) {
      setName(editing?.name ?? "");
      setTermValue(editing?.termValue ?? "");
      setActive(editing?.active ?? true);
    }
  }, [open, editing]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? "Edit location" : "Add location"}</DialogTitle>
          <DialogDescription>
            Locations are used as search terms on OpenRent.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input
              placeholder="e.g. Manchester"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>OpenRent term value</Label>
            <Input
              placeholder="e.g. Manchester"
              value={termValue}
              onChange={(e) => setTermValue(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Exact value submitted to OpenRent's location search field.
            </p>
          </div>
          <div className="flex items-center justify-between rounded-md border p-3">
            <div className="text-sm font-medium">Active</div>
            <Switch checked={active} onCheckedChange={setActive} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={() => onSave({ name, termValue, active })}
            disabled={!name.trim() || !termValue.trim()}
          >
            {editing ? "Save" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
