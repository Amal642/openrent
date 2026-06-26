import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  createManualWhatsAppContact,
  editWhatsAppContact,
  getWhatsAppContacts,
} from "@/api/openrent";
import type { WhatsAppContact, WhatsAppContactStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/whatsapp")({
  head: () => ({
    meta: [{ title: "WhatsApp Acquisitions — Land Royal" }],
  }),
  component: WhatsAppPage,
});

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_META: Record<WhatsAppContactStatus, { label: string; cls: string }> = {
  NEW_CONTACT: { label: "New", cls: "border-info/30 bg-info/15 text-info" },
  AWAITING_NAME: { label: "Awaiting name", cls: "border-warning/40 bg-warning/15 text-warning" },
  AWAITING_PROPERTY: { label: "Awaiting property", cls: "border-warning/40 bg-warning/15 text-warning" },
  PHONE_ACQUIRED: { label: "Phone acquired", cls: "border-success/30 bg-success/15 text-success" },
};

function StatusBadge({ status }: { status: WhatsAppContactStatus }) {
  const meta = STATUS_META[status] ?? { label: status, cls: "border-border bg-muted text-muted-foreground" };
  return (
    <Badge variant="outline" className={cn("text-xs font-medium", meta.cls)}>
      {meta.label}
    </Badge>
  );
}

// ── Formatting ────────────────────────────────────────────────────────────────

function fmtPhone(phone: string): string {
  if (phone.startsWith("lid:")) return `${phone.slice(4)} (unresolved)`;
  if (phone.startsWith("44") && phone.length >= 12)
    return `+44 ${phone.slice(2, 6)} ${phone.slice(6, 9)} ${phone.slice(9)}`;
  return `+${phone}`;
}

function fmtRelative(iso?: string): string {
  if (!iso) return "—";
  const utc = iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z";
  const diff = Date.now() - new Date(utc).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Contact form modal ────────────────────────────────────────────────────────

interface ContactFormProps {
  open: boolean;
  onClose: () => void;
  title: string;
  initial?: { phone?: string; name?: string; property_address?: string };
  contactId?: number;
}

function ContactFormModal({ open, onClose, title, initial = {}, contactId }: ContactFormProps) {
  const queryClient = useQueryClient();
  const [phone, setPhone] = useState(initial.phone ?? "");
  const [name, setName] = useState(initial.name ?? "");
  const [property, setProperty] = useState(initial.property_address ?? "");
  const [error, setError] = useState<string | null>(null);

  const isEdit = contactId != null;

  const createMutation = useMutation({
    mutationFn: () =>
      createManualWhatsAppContact({
        phone,
        name: name.trim() || undefined,
        property_address: property.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["whatsapp-contacts"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  const editMutation = useMutation({
    mutationFn: () =>
      editWhatsAppContact(contactId!, {
        phone: phone.trim() || undefined,
        name: name.trim() || undefined,
        property_address: property.trim() || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["whatsapp-contacts"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  const isPending = createMutation.isPending || editMutation.isPending;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!isEdit && !phone.trim()) {
      setError("Phone number is required");
      return;
    }
    if (isEdit) editMutation.mutate();
    else createMutation.mutate();
  }

  function handleOpenChange(v: boolean) {
    if (!v) {
      setPhone(initial.phone ?? "");
      setName(initial.name ?? "");
      setProperty(initial.property_address ?? "");
      setError(null);
      onClose();
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 pt-2">
          <div className="space-y-1.5">
            <Label htmlFor="wa-phone">Phone number</Label>
            <Input
              id="wa-phone"
              placeholder="447911123456"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              disabled={isPending}
            />
            <p className="text-xs text-muted-foreground">
              Digits only, include country code (e.g. 447911123456)
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wa-name">Name</Label>
            <Input
              id="wa-name"
              placeholder="Brian Smith"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isPending}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wa-property">Matched property</Label>
            <Input
              id="wa-property"
              placeholder="12 High Street, London, SW1A 1AA"
              value={property}
              onChange={(e) => setProperty(e.target.value)}
              disabled={isPending}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? "Saving…" : isEdit ? "Save changes" : "Add contact"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

function WhatsAppPage() {
  const { data: contacts = [], isLoading, error } = useQuery({
    queryKey: ["whatsapp-contacts"],
    queryFn: () => getWhatsAppContacts(),
    refetchInterval: 30_000,
  });

  const [addOpen, setAddOpen] = useState(false);
  const [editContact, setEditContact] = useState<WhatsAppContact | null>(null);

  const acquired = contacts.filter((c) => c.status === "PHONE_ACQUIRED").length;
  const pending = contacts.filter((c) => c.status !== "PHONE_ACQUIRED").length;

  return (
    <>
      <PageHeader
        title="WhatsApp Acquisitions"
        description="Landlords who texted our WhatsApp number — tracked and matched to existing listings."
      />

      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-4">
          <div className="rounded-lg border bg-card px-4 py-3 flex flex-col gap-0.5 min-w-[120px]">
            <span className="text-xs text-muted-foreground">Total contacts</span>
            <span className="text-2xl font-semibold">{contacts.length}</span>
          </div>
          <div className="rounded-lg border bg-card px-4 py-3 flex flex-col gap-0.5 min-w-[120px]">
            <span className="text-xs text-muted-foreground">Phones acquired</span>
            <span className="text-2xl font-semibold text-success">{acquired}</span>
          </div>
          <div className="rounded-lg border bg-card px-4 py-3 flex flex-col gap-0.5 min-w-[120px]">
            <span className="text-xs text-muted-foreground">In progress</span>
            <span className="text-2xl font-semibold text-warning">{pending}</span>
          </div>
        </div>
        <Button onClick={() => setAddOpen(true)}>+ Add contact</Button>
      </div>

      <div className="rounded-lg border bg-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Phone</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Matched Property</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Confidence</TableHead>
              <TableHead>Received</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {error && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-destructive py-8">
                  Failed to load contacts.
                </TableCell>
              </TableRow>
            )}
            {!isLoading && !error && contacts.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  No WhatsApp contacts yet. Landlords who text your number will appear here.
                </TableCell>
              </TableRow>
            )}
            {contacts.map((contact) => (
              <ContactRow
                key={contact.id}
                contact={contact}
                onEdit={() => setEditContact(contact)}
              />
            ))}
          </TableBody>
        </Table>
      </div>

      <ContactFormModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add contact manually"
      />

      {editContact && (
        <ContactFormModal
          open
          onClose={() => setEditContact(null)}
          contactId={editContact.id}
          title="Edit contact"
          initial={{
            phone: editContact.phone_number.startsWith("lid:") ? "" : editContact.phone_number,
            name: editContact.name ?? "",
            property_address: editContact.property_address ?? "",
          }}
        />
      )}
    </>
  );
}

function ContactRow({
  contact,
  onEdit,
}: {
  contact: WhatsAppContact;
  onEdit: () => void;
}) {
  const isUnresolved = contact.phone_number.startsWith("lid:");

  return (
    <TableRow>
      <TableCell className="font-mono text-sm">
        {isUnresolved ? (
          <span className="text-muted-foreground italic">{fmtPhone(contact.phone_number)}</span>
        ) : (
          fmtPhone(contact.phone_number)
        )}
      </TableCell>
      <TableCell className="font-medium">
        {contact.name ?? <span className="text-muted-foreground italic">Unknown</span>}
      </TableCell>
      <TableCell className="text-sm text-muted-foreground max-w-[240px] truncate">
        {contact.property_address ?? <span className="italic">No match yet</span>}
      </TableCell>
      <TableCell>
        <StatusBadge status={contact.status} />
      </TableCell>
      <TableCell className="text-sm">
        {contact.is_manual ? (
          <span className="text-xs text-muted-foreground italic">Manually Entered</span>
        ) : contact.confidence != null ? (
          <span
            className={cn(
              "font-medium",
              contact.confidence >= 85
                ? "text-success"
                : contact.confidence >= 65
                  ? "text-warning"
                  : "text-muted-foreground",
            )}
          >
            {contact.confidence.toFixed(0)}%
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {fmtRelative(contact.last_received_at)}
      </TableCell>
      <TableCell>
        {isUnresolved && (
          <Button variant="ghost" size="sm" onClick={onEdit} className="h-7 px-2 text-xs">
            Edit
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}
