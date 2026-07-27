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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  createLocation,
  deleteLocation,
  getLocations,
  toggleLocation,
  updateLocation,
  type LocationInput,
} from "@/lib/api";
import type { Location } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

type LocationForm = Required<Omit<LocationInput, "active">> & { active: boolean };

const EMPTY_FORM: LocationForm = {
  name: "",
  termValue: "",
  active: true,
  region: "South",
  radiusKm: 5,
  priceMin: 1000,
  priceMax: 4000,
  bedroomsMin: 0,
  bedroomsMax: 4,
  allocatable: false,
};

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
    mutationFn: ({ id, data }: { id: number; data: LocationForm }) =>
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

  const save = (data: LocationForm) => {
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
              <TableHead className="w-12">#</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>OpenRent Term</TableHead>
              <TableHead>Region</TableHead>
              <TableHead className="text-right">Radius</TableHead>
              <TableHead>Allocatable</TableHead>
              <TableHead>Active</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {locations.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                  No locations yet. Add one to use in Search Profiles.
                </TableCell>
              </TableRow>
            )}
            {locations.map((loc, i) => (
              <TableRow key={loc.id}>
                <TableCell className="text-sm tabular-nums text-muted-foreground">
                  {i + 1}
                </TableCell>
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
                  <Badge variant="outline">{loc.region}</Badge>
                </TableCell>
                <TableCell className="text-right tabular-nums text-sm">
                  {loc.radiusKm} km
                </TableCell>
                <TableCell>
                  {loc.allocatable ? (
                    <Badge className="border-success/30 bg-success/15 text-success">Yes</Badge>
                  ) : (
                    <Badge variant="outline" className="text-muted-foreground">No</Badge>
                  )}
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
  onSave: (data: LocationForm) => void;
}) {
  const [form, setForm] = useState<LocationForm>(EMPTY_FORM);
  const set = <K extends keyof LocationForm>(key: K, value: LocationForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  useEffect(() => {
    if (!open) return;
    setForm(
      editing
        ? {
            name: editing.name,
            termValue: editing.termValue,
            active: editing.active,
            region: editing.region,
            radiusKm: editing.radiusKm,
            priceMin: editing.priceMin,
            priceMax: editing.priceMax,
            bedroomsMin: editing.bedroomsMin,
            bedroomsMax: editing.bedroomsMax,
            allocatable: editing.allocatable,
          }
        : EMPTY_FORM,
    );
  }, [open, editing]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? "Edit location" : "Add location"}</DialogTitle>
          <DialogDescription>
            Locations are OpenRent search terms and also drive Area Intelligence
            and SIM allocation.
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3 py-2">
          <div className="col-span-2 space-y-1.5">
            <Label>Name</Label>
            <Input
              placeholder="e.g. Camden"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
            />
          </div>
          <div className="col-span-2 space-y-1.5">
            <Label>OpenRent term value</Label>
            <Input
              placeholder="e.g. Camden, London"
              value={form.termValue}
              onChange={(e) => set("termValue", e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Exact value submitted to OpenRent's location search. Also the key
              used to map listings to this area.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Region</Label>
            <Select
              value={form.region}
              onValueChange={(v) => set("region", v as "South" | "North")}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="South">South</SelectItem>
                <SelectItem value="North">North</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Search radius (km)</Label>
            <Input
              type="number"
              value={form.radiusKm}
              onChange={(e) => set("radiusKm", Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Price min</Label>
            <Input
              type="number"
              value={form.priceMin}
              onChange={(e) => set("priceMin", Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Price max</Label>
            <Input
              type="number"
              value={form.priceMax}
              onChange={(e) => set("priceMax", Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Bedrooms min</Label>
            <Input
              type="number"
              value={form.bedroomsMin}
              onChange={(e) => set("bedroomsMin", Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Bedrooms max</Label>
            <Input
              type="number"
              value={form.bedroomsMax}
              onChange={(e) => set("bedroomsMax", Number(e.target.value))}
            />
          </div>
          <div className="col-span-2 flex items-center justify-between rounded-md border p-3">
            <div>
              <div className="text-sm font-medium">Allocatable</div>
              <div className="text-xs text-muted-foreground">
                Allow the SIM allocator to assign accounts here (drives spend).
              </div>
            </div>
            <Switch
              checked={form.allocatable}
              onCheckedChange={(v) => set("allocatable", v)}
            />
          </div>
          <div className="col-span-2 flex items-center justify-between rounded-md border p-3">
            <div className="text-sm font-medium">Active</div>
            <Switch checked={form.active} onCheckedChange={(v) => set("active", v)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={() => onSave(form)}
            disabled={!form.name.trim() || !form.termValue.trim()}
          >
            {editing ? "Save" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
