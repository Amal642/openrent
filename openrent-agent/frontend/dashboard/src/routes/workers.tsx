import { createFileRoute } from "@tanstack/react-router";
import { Pause, Play, Power, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { DotBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { controlAccountWorker, getWorkers, getWorkersStatus } from "@/lib/api";
import type { WorkerStatus } from "@/lib/types";
import { fmtRelative } from "@/lib/format";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

export const Route = createFileRoute("/workers")({
  head: () => ({
    meta: [{ title: "Workers - RentPilot" }],
  }),
  component: WorkersPage,
});

const workerTone: Record<WorkerStatus, "success" | "warning" | "destructive" | "muted"> = {
  queued: "warning",
  running: "success",
  stopping: "warning",
  idle: "muted",
  completed: "success",
  stopped: "muted",
  retrying: "warning",
  proxy_error: "destructive",
  login_error: "destructive",
  paused: "warning",
  error: "destructive",
};

function WorkersPage() {
  const queryClient = useQueryClient();
  const {
    data: workers = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["workers"],
    queryFn: getWorkers,
    refetchInterval: 10000,
  });
  const { data: status } = useQuery({
    queryKey: ["worker-status"],
    queryFn: getWorkersStatus,
    refetchInterval: 10000,
  });
  const mutation = useMutation({
    mutationFn: controlAccountWorker,
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["workers"] });
      queryClient.invalidateQueries({ queryKey: ["worker-status"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      toast.success(`Worker ${variables.action} requested`);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Worker action failed"),
  });

  if (isLoading) return <PageHeader title="Workers" description="Loading worker status..." />;
  if (error) return <PageHeader title="Workers" description="Could not load worker status." />;

  return (
    <>
      <PageHeader
        title="Workers"
        description={`${status?.running ?? 0} running · ${status?.paused ?? 0} paused · ${status?.errored ?? 0} errored`}
      />

      <div className="overflow-x-auto rounded-lg border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead>Account</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Phase</TableHead>
              <TableHead>Heartbeat</TableHead>
              <TableHead>Job</TableHead>
              <TableHead>Last error</TableHead>
              <TableHead className="text-right">Controls</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {workers.map((worker) => (
              <TableRow key={worker.id}>
                <TableCell>
                  <div className="font-medium">{worker.account_email}</div>
                  <div className="text-xs text-muted-foreground">Account {worker.account_id}</div>
                </TableCell>
                <TableCell>
                  <DotBadge tone={workerTone[worker.status] ?? "muted"} label={worker.status} />
                  {worker.stale ? (
                    <div className="mt-1 text-xs text-destructive">stale heartbeat</div>
                  ) : null}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">{worker.phase}</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {worker.last_heartbeat ? fmtRelative(worker.last_heartbeat) : "-"}
                  {worker.started_at ? <div>started {fmtRelative(worker.started_at)}</div> : null}
                </TableCell>
                <TableCell className="max-w-[180px] truncate text-xs text-muted-foreground">
                  {worker.job_id || "-"}
                  {worker.retry_count ? (
                    <div className="text-warning">
                      retry {worker.retry_count}
                      {worker.retry_next_at ? ` · ${fmtRelative(worker.retry_next_at)}` : ""}
                    </div>
                  ) : null}
                  {worker.last_completed_at ? (
                    <div>completed {fmtRelative(worker.last_completed_at)}</div>
                  ) : null}
                </TableCell>
                <TableCell className="max-w-[320px] truncate text-xs text-muted-foreground">
                  {worker.last_error || "-"}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() =>
                        mutation.mutate({ accountId: String(worker.account_id), action: "start" })
                      }
                      aria-label="Start worker"
                    >
                      <Play className="size-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() =>
                        mutation.mutate({ accountId: String(worker.account_id), action: "stop" })
                      }
                      aria-label="Stop worker"
                    >
                      <Power className="size-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() =>
                        mutation.mutate({ accountId: String(worker.account_id), action: "pause" })
                      }
                      aria-label="Pause worker"
                    >
                      <Pause className="size-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() =>
                        mutation.mutate({ accountId: String(worker.account_id), action: "resume" })
                      }
                      aria-label="Resume worker"
                    >
                      <RefreshCw className="size-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
