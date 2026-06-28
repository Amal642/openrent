import type { LeadStatus } from "./types";

export const STATUS_META: Record<LeadStatus, { label: string; tone: "info" | "warning" | "success" | "destructive" | "muted" }> = {
  INITIAL_MESSAGE_SENT: { label: "Sent", tone: "info" },
  NEW_REPLY: { label: "New reply", tone: "warning" },
  AI_REPLIED: { label: "AI replied", tone: "success" },
  PHONE_ACQUIRED: { label: "Phone acquired", tone: "success" },
  AI_FAILED: { label: "AI failed", tone: "destructive" },
  REPLY_DISABLED: { label: "Reply disabled", tone: "muted" },
  AGENT_SKIPPED: { label: "Agent skipped", tone: "muted" },
  SKIPPED: { label: "Skipped", tone: "muted" },
  DUPLICATE_LEAD: { label: "Duplicate", tone: "muted" },
  VIEWING_CANCELLED: { label: "Viewing cancelled", tone: "muted" },
  INACTIVE_NO_REPLY: { label: "Inactive (no reply)", tone: "muted" },
  SHORT_TERM_PROPERTY: { label: "Short term", tone: "muted" },
  CLOSED: { label: "Closed", tone: "success" },
  WHATSAPP_SHARED: { label: "WhatsApp shared", tone: "info" },
};

export const TONE_CLASS: Record<string, string> = {
  info: "bg-info/15 text-info border-info/30",
  warning: "bg-warning/15 text-warning border-warning/40",
  success: "bg-success/15 text-success border-success/30",
  destructive: "bg-destructive/15 text-destructive border-destructive/40",
  muted: "bg-muted text-muted-foreground border-border",
};
