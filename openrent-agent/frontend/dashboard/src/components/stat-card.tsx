import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  delta,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: string | number;
  delta?: string;
  icon?: LucideIcon;
  tone?: "default" | "success" | "warning" | "destructive";
}) {
  const toneClass = {
    default: "text-foreground",
    success: "text-success",
    warning: "text-warning",
    destructive: "text-destructive",
  }[tone];
  const iconClass = {
    default: "bg-primary/10 text-primary",
    success: "bg-success/10 text-success",
    warning: "bg-warning/15 text-warning",
    destructive: "bg-destructive/10 text-destructive",
  }[tone];
  return (
    <div className="rounded-lg border bg-card p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="flex items-start justify-between">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        {Icon && (
          <span className={cn("flex size-8 items-center justify-center rounded-md", iconClass)}>
            <Icon className="size-4" />
          </span>
        )}
      </div>
      <div className={cn("mt-2 text-2xl font-semibold tabular-nums", toneClass)}>{value}</div>
      {delta && <div className="mt-1 text-xs text-muted-foreground">{delta}</div>}
    </div>
  );
}
