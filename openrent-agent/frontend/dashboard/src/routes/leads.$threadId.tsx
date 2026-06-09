import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft, ExternalLink, CheckCircle2, XCircle, Phone, Copy } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  completeLead,
  getAccounts,
  getConversationMessages,
  getLead,
  skipLead,
} from "@/lib/api";
import { fmtDateTime, fmtMoney, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Message } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

export const Route = createFileRoute("/leads/$threadId")({
  head: () => ({
    meta: [{ title: "Conversation — Land Royal" }],
  }),
  errorComponent: ({ error }) => <div className="p-8 text-destructive">{error.message}</div>,
  component: ConversationPage,
});

function ConversationPage() {
  const { threadId } = Route.useParams();
  const queryClient = useQueryClient();
  const {
    data: lead,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["lead", threadId],
    queryFn: () => getLead(threadId),
  });

  const { data: accounts = [] } = useQuery({
    queryKey: ["accounts"],
    queryFn: getAccounts,
    refetchInterval: 15000,
  });

  const { data: persistedMessages = [] } = useQuery({
    queryKey: ["conversation-messages", threadId],
    queryFn: () => getConversationMessages(threadId),
    refetchInterval: 10000,
  });

  const onUpdated = () => {
    queryClient.invalidateQueries({ queryKey: ["lead", threadId] });
    queryClient.invalidateQueries({ queryKey: ["leads"] });
    queryClient.invalidateQueries({ queryKey: ["conversation-messages", threadId] });
  };
  const completeMutation = useMutation({
    mutationFn: completeLead,
    onSuccess: () => {
      onUpdated();
      toast.success("Conversation marked complete");
    },
    onError: () => toast.error("Could not mark complete"),
  });
  const skipMutation = useMutation({
    mutationFn: skipLead,
    onSuccess: () => {
      onUpdated();
      toast.success("Conversation marked invalid");
    },
    onError: () => toast.error("Could not mark invalid"),
  });

  if (isLoading) {
    return (
      <PageHeader
        title="Conversation"
        description="Loading conversation from OpenRent automation..."
      />
    );
  }

  if (error) {
    return (
      <PageHeader
        title="Conversation"
        description="Could not load conversation. Check that the FastAPI server is running on port 8000."
      />
    );
  }

  if (!lead) {
    return <div className="p-8">Conversation not found.</div>;
  }

  const account = accounts.find((a) => a.id === lead.accountId);
  // Only show real persisted messages (inbound from landlord + outbound
  // confirmed sent).  The messagesForLead() helper synthesised messages from
  // last_ai_reply which is stored *before* send_reply() is called — failed
  // sends left phantom "sent" messages in the thread view.
  const messages: Message[] = [...persistedMessages];

  return (
    <>
      <PageHeader
        title={lead.threadId}
        description={lead.propertyTitle}
        actions={
          <>
            <Button variant="outline" size="sm" asChild>
              <Link to="/leads">
                <ArrowLeft className="size-4" /> Back
              </Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={lead.propertyLink || "#"} target="_blank" rel="noreferrer">
                <ExternalLink className="size-4" /> Open property
              </a>
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => completeMutation.mutate(lead.threadId)}
            >
              <CheckCircle2 className="size-4" /> Complete
            </Button>
            <Button variant="outline" size="sm" onClick={() => skipMutation.mutate(lead.threadId)}>
              <XCircle className="size-4" /> Invalid
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 rounded-lg border bg-card flex flex-col min-h-[600px]">
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.map((m) => (
              <div
                key={m.id}
                className={cn("flex", m.sender === "landlord" ? "justify-start" : "justify-end")}
              >
                <div
                  className={cn(
                    "max-w-[75%] rounded-lg px-3 py-2 text-sm",
                    m.sender === "landlord" && "bg-muted text-foreground",
                    m.sender === "ai" && "bg-info/15 text-foreground border border-info/30",
                    m.sender === "operator" && "bg-primary text-primary-foreground",
                  )}
                >
                  <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide opacity-70 mb-0.5">
                    {m.sender}
                    <span className="opacity-60">· {fmtRelative(m.createdAt)}</span>
                  </div>
                  <div>{m.text}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-lg border bg-card p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold">Lead</h3>
              <StatusBadge status={lead.status} />
            </div>
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <Field
                label="Budget"
                value={
                  lead.priceMin && lead.priceMax
                    ? `${fmtMoney(lead.priceMin)} – ${fmtMoney(lead.priceMax)}`
                    : lead.rent
                      ? fmtMoney(lead.rent)
                      : "—"
                }
              />
              <Field
                label="Bedrooms"
                value={
                  lead.bedroomsMin && lead.bedroomsMax
                    ? `${lead.bedroomsMin}–${lead.bedroomsMax}`
                    : lead.bedrooms
                      ? String(lead.bedrooms)
                      : "—"
                }
              />
              <Field label="Area" value={lead.area} />
              <Field label="Account" value={account?.email ?? "—"} />
              <Field label="Thread ID" value={lead.threadId} />
              <Field label="Stage" value={lead.conversationStage.replaceAll("_", " ")} />
              <Field label="Initial sent" value={fmtRelative(lead.initialMessageSentAt)} />
              <Field
                label="Viewing"
                value={
                  lead.viewingDatetime
                    ? `${fmtDateTime(lead.viewingDatetime)}${lead.viewingCancelled ? " · cancelled" : ""}`
                    : "—"
                }
              />
            </dl>
            {lead.phoneNumber && (
              <div className="rounded-md border border-success/30 bg-success/10 p-3">
                <div className="text-[10px] uppercase tracking-wide text-success mb-1">
                  Extracted phone
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium tabular-nums text-foreground flex items-center gap-2">
                    <Phone className="size-4 text-success" /> {lead.phoneNumber}
                  </span>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-7"
                    onClick={() => {
                      navigator.clipboard.writeText(lead.phoneNumber!);
                      toast.success("Copied");
                    }}
                  >
                    <Copy className="size-3.5" />
                  </Button>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-lg border bg-card p-4 space-y-2">
            <h3 className="text-sm font-semibold">Account persona</h3>
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <Field
                label="Names"
                value={
                  [lead.personaName, lead.personaPartnerName].filter(Boolean).join(" & ") || "—"
                }
              />
              <Field
                label="Jobs"
                value={[lead.personaJob, lead.personaPartnerJob].filter(Boolean).join(" & ") || "—"}
              />
              <Field label="Home city" value={lead.homeCity || "—"} />
              <Field
                label="Phone asked"
                value={lead.phoneRequestedAt ? fmtRelative(lead.phoneRequestedAt) : "—"}
              />
            </dl>
          </div>

          <div className="rounded-lg border bg-card p-4">
            <h3 className="text-sm font-semibold mb-3">Timeline</h3>
            <ol className="space-y-3 text-xs">
              <TimelineItem
                time={fmtDateTime(lead.initialMessageSentAt)}
                label="Initial outreach sent"
                tone="info"
              />
              {lead.lastLandlordMessage && (
                <TimelineItem
                  time={fmtDateTime(lead.lastUpdatedAt)}
                  label="Landlord replied"
                  tone="warning"
                />
              )}
              {lead.lastAiReply && (
                <TimelineItem
                  time={fmtDateTime(lead.lastUpdatedAt)}
                  label="AI generated follow-up"
                  tone="info"
                />
              )}
              {lead.phoneNumber && (
                <TimelineItem
                  time={fmtDateTime(lead.lastUpdatedAt)}
                  label="Phone number extracted"
                  tone="success"
                />
              )}
              {lead.viewingConfirmed && (
                <TimelineItem
                  time={lead.viewingDatetime ? fmtDateTime(lead.viewingDatetime) : "Time pending"}
                  label={lead.viewingCancelled ? "Viewing cancelled" : "Viewing booked"}
                  tone={lead.viewingCancelled ? "warning" : "success"}
                />
              )}
            </ol>
          </div>
        </div>
      </div>
    </>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-foreground truncate">{value}</dd>
    </>
  );
}

function TimelineItem({
  time,
  label,
  tone,
}: {
  time: string;
  label: string;
  tone: "info" | "warning" | "success";
}) {
  const dot: Record<string, string> = {
    info: "bg-info",
    warning: "bg-warning",
    success: "bg-success",
  };
  return (
    <li className="flex items-start gap-2.5">
      <span className={cn("mt-1 size-2 rounded-full", dot[tone])} />
      <div className="flex-1">
        <div className="font-medium text-foreground">{label}</div>
        <div className="text-muted-foreground">{time}</div>
      </div>
    </li>
  );
}
