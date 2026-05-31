import { cn } from "@/lib/utils";
import { STATUS_META, TONE_CLASS } from "@/lib/status";
import type { LeadStatus } from "@/lib/types";

export function StatusBadge({ status, className }: { status: LeadStatus; className?: string }) {
  const meta = STATUS_META[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONE_CLASS[meta.tone],
        className
      )}
    >
      {meta.tone === "warning" && <span className="size-1.5 rounded-full bg-warning animate-pulse" />}
      {meta.label}
    </span>
  );
}

export function DotBadge({ tone, label }: { tone: "success" | "warning" | "destructive" | "muted" | "info"; label: string }) {
  const dotColor: Record<string, string> = {
    success: "bg-success",
    warning: "bg-warning",
    destructive: "bg-destructive",
    info: "bg-info",
    muted: "bg-muted-foreground",
  };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-foreground">
      <span className={cn("size-1.5 rounded-full", dotColor[tone])} />
      {label}
    </span>
  );
}
