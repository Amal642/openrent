import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo, Fragment } from "react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getLogs } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import type { LogEntry } from "@/lib/types";

export const Route = createFileRoute("/logs")({
  head: () => ({
    meta: [
      { title: "Logs — RentPilot" },
      { name: "description", content: "Operational logs across workers and AI." },
    ],
  }),
  component: LogsPage,
});

const tabs = [
  { id: "all", label: "All" },
  { id: "worker", label: "Worker" },
  { id: "errors", label: "Errors" },
  { id: "ai", label: "AI failures" },
  { id: "login", label: "Login" },
  { id: "retry", label: "Retries" },
  { id: "agent_skip", label: "Agent skips" },
];

const levelColor = {
  info: "text-info",
  warn: "text-warning",
  error: "text-destructive",
};

function LogsPage() {
  const [tab, setTab] = useState("all");
  const [q, setQ] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(250);
  const pageSize = 50;

  const { data: logs = [], isFetching } = useQuery<LogEntry[]>({
    queryKey: ["logs", limit],
    queryFn: () => getLogs(limit),
    refetchInterval: 30000,
  });

  const filtered = useMemo(
    () =>
      [...logs].reverse().filter((l) => {
        if (tab === "errors" && l.level !== "error") return false;
        if (tab === "ai" && !(l.category === "ai" && l.level === "error")) return false;
        if (["worker", "login", "retry", "agent_skip"].includes(tab) && l.category !== tab)
          return false;
        if (q && !l.message.toLowerCase().includes(q.toLowerCase())) return false;
        return true;
      }),
    [tab, q, logs],
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const visible = filtered.slice((page - 1) * pageSize, page * pageSize);

  return (
    <>
      <PageHeader title="Logs" description="Worker, AI, login, retry and agent-skip events." />

      <div className="flex min-w-0 flex-col gap-2 mb-3 sm:flex-row">
        <Tabs value={tab} onValueChange={(v) => { setTab(v); setPage(1); }} className="min-w-0 flex-1">
          <div className="overflow-x-auto pb-1">
            <TabsList className="h-9 w-max">
              {tabs.map((t) => (
                <TabsTrigger key={t.id} value={t.id} className="text-xs">
                  {t.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
        </Tabs>
        <div className="flex gap-2">
          <Input
            placeholder="Filter logs…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            className="h-9 sm:w-56"
          />
          {limit < 2500 && (
            <Button
              variant="outline"
              size="sm"
              className="h-9 shrink-0"
              onClick={() => { setLimit(2500); setPage(1); }}
              disabled={isFetching}
            >
              {isFetching ? "Loading…" : "Full Logs"}
            </Button>
          )}
        </div>
      </div>

      <div className="rounded-lg border bg-card overflow-x-auto font-mono text-xs">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 font-sans">
              <TableHead className="w-20">Level</TableHead>
              <TableHead className="w-32">Date</TableHead>
              <TableHead className="w-28">Category</TableHead>
              <TableHead>Message</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.map((l) => (
              <Fragment key={l.id}>
                <TableRow
                  onClick={() => setExpanded(expanded === l.id ? null : l.id)}
                  className="cursor-pointer"
                >
                  <TableCell className={cn("uppercase font-semibold", levelColor[l.level])}>
                    {l.level}
                  </TableCell>
                  <TableCell className="text-muted-foreground whitespace-nowrap">
                    {fmtDate(l.createdAt)}
                  </TableCell>
                  <TableCell>{l.category}</TableCell>
                  <TableCell>{l.message}</TableCell>
                </TableRow>
                {expanded === l.id && l.context && (
                  <TableRow>
                    <TableCell colSpan={4} className="bg-muted/30">
                      <pre className="whitespace-pre-wrap text-[11px]">
                        {JSON.stringify(l.context, null, 2)}
                      </pre>
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Page {page} of {totalPages} · {filtered.length} log events
          {limit === 2500 && " (full log)"}
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((current) => Math.max(1, current - 1))}
            disabled={page <= 1}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
            disabled={page >= totalPages}
          >
            Next
          </Button>
        </div>
      </div>
    </>
  );
}
