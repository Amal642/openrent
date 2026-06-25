import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getWhatsAppContacts } from "@/api/openrent";
import type { WhatsAppContact, WhatsAppContactStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/whatsapp")({
  head: () => ({
    meta: [{ title: "WhatsApp Acquisitions — Land Royal" }],
  }),
  component: WhatsAppPage,
});

// ── Status badge config ───────────────────────────────────────────────────────

const STATUS_META: Record<
  WhatsAppContactStatus,
  { label: string; cls: string }
> = {
  NEW_CONTACT: {
    label: "New",
    cls: "border-info/30 bg-info/15 text-info",
  },
  AWAITING_NAME: {
    label: "Awaiting name",
    cls: "border-warning/40 bg-warning/15 text-warning",
  },
  AWAITING_PROPERTY: {
    label: "Awaiting property",
    cls: "border-warning/40 bg-warning/15 text-warning",
  },
  PHONE_ACQUIRED: {
    label: "Phone acquired",
    cls: "border-success/30 bg-success/15 text-success",
  },
};

function StatusBadge({ status }: { status: WhatsAppContactStatus }) {
  const meta = STATUS_META[status] ?? {
    label: status,
    cls: "border-border bg-muted text-muted-foreground",
  };
  return (
    <Badge variant="outline" className={cn("text-xs font-medium", meta.cls)}>
      {meta.label}
    </Badge>
  );
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtPhone(phone: string): string {
  if (phone.startsWith("44") && phone.length >= 12) {
    return `+44 ${phone.slice(2, 6)} ${phone.slice(6, 9)} ${phone.slice(9)}`;
  }
  return `+${phone}`;
}

function fmtRelative(iso?: string): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Page ─────────────────────────────────────────────────────────────────────

function WhatsAppPage() {
  const { data: contacts = [], isLoading, error } = useQuery({
    queryKey: ["whatsapp-contacts"],
    queryFn: () => getWhatsAppContacts(),
    refetchInterval: 30_000,
  });

  const acquired = contacts.filter((c) => c.status === "PHONE_ACQUIRED").length;
  const pending = contacts.filter((c) => c.status !== "PHONE_ACQUIRED").length;

  return (
    <>
      <PageHeader
        title="WhatsApp Acquisitions"
        description="Landlords who texted our WhatsApp number — tracked and matched to existing listings."
      />

      {/* Summary strip */}
      <div className="flex gap-4 mb-4">
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
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {error && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-destructive py-8">
                  Failed to load contacts.
                </TableCell>
              </TableRow>
            )}
            {!isLoading && !error && contacts.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  No WhatsApp contacts yet. Landlords who text your number will appear here.
                </TableCell>
              </TableRow>
            )}
            {contacts.map((contact) => (
              <ContactRow key={contact.id} contact={contact} />
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}

function ContactRow({ contact }: { contact: WhatsAppContact }) {
  return (
    <TableRow>
      <TableCell className="font-mono text-sm">
        {fmtPhone(contact.phone_number)}
      </TableCell>
      <TableCell className="font-medium">
        {contact.name ?? <span className="text-muted-foreground italic">Unknown</span>}
      </TableCell>
      <TableCell className="text-sm text-muted-foreground max-w-[240px] truncate">
        {contact.property_address ?? (
          <span className="italic">No match yet</span>
        )}
      </TableCell>
      <TableCell>
        <StatusBadge status={contact.status} />
      </TableCell>
      <TableCell className="text-sm">
        {contact.confidence != null ? (
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
    </TableRow>
  );
}
