import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Activity, Database, Server, Wifi } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DotBadge } from "@/components/status-badge";
import { getHealth, getSettings, getWorkersStatus, updateSettings } from "@/lib/api";
import type { AutomationSettings } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings - Land Royal" },
      { name: "description", content: "Global automation settings." },
    ],
  }),
  component: SettingsPage,
});

function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: settings, isLoading, error } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });
  const { data: health, refetch: refetchHealth, isFetching: testingApi } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
  });
  const { data: workerStatus } = useQuery({
    queryKey: ["worker-status"],
    queryFn: getWorkersStatus,
    refetchInterval: 15000,
  });
  const [draft, setDraft] = useState<Partial<AutomationSettings>>({});

  useEffect(() => {
    if (settings) setDraft(settings);
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: (updated) => {
      setDraft(updated);
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Settings saved");
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Could not save settings"),
  });

  if (isLoading) return <PageHeader title="Settings" description="Loading backend settings..." />;
  if (error || !settings) {
    return <PageHeader title="Settings" description="Could not load settings from the backend." />;
  }

  const save = () => saveMutation.mutate(draft);
  const apiOnline = health?.status === "running";

  return (
    <>
      <PageHeader
        title="Settings"
        description="Backend connectivity, OpenAI settings, worker concurrency, pacing, and limits."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetchHealth().then(() => toast.success("API connectivity checked"))}
            disabled={testingApi}
          >
            <Wifi className="size-4" /> Test API
          </Button>
        }
      />

      <div className="mb-4 grid gap-3 md:grid-cols-4">
        <StatusTile
          icon={Server}
          label="Backend"
          value={apiOnline ? "running" : settings.backend_status}
          tone={apiOnline ? "success" : "destructive"}
        />
        <StatusTile
          icon={Database}
          label="Redis"
          value={settings.redis_status}
          tone={settings.redis_status === "running" ? "success" : "destructive"}
        />
        <StatusTile
          icon={Activity}
          label="Workers"
          value={`${workerStatus?.running ?? 0}/${workerStatus?.total ?? 0} running`}
          tone={(workerStatus?.errored ?? 0) > 0 ? "destructive" : "success"}
        />
        <StatusTile
          icon={Wifi}
          label="Queue"
          value={workerStatus?.queue ?? "unknown"}
          tone="warning"
        />
      </div>

      <div className="max-w-3xl space-y-4">
        <Section title="AI" description="OpenAI reply generation and auto-send behavior.">
          <Row label="Auto-send AI replies" description="Controls whether workers send AI replies automatically.">
            <Switch
              checked={!!draft.auto_send}
              onCheckedChange={(auto_send) => setDraft({ ...draft, auto_send })}
            />
          </Row>
          <Row label="OpenAI model">
            <Select
              value={draft.openai_model}
              onValueChange={(openai_model) => setDraft({ ...draft, openai_model })}
            >
              <SelectTrigger className="w-full sm:w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="gpt-4.1">gpt-4.1</SelectItem>
                <SelectItem value="gpt-4.1-mini">gpt-4.1-mini</SelectItem>
                <SelectItem value="gpt-4o">gpt-4o</SelectItem>
                <SelectItem value="gpt-4o-mini">gpt-4o-mini</SelectItem>
              </SelectContent>
            </Select>
          </Row>
        </Section>

        <Section title="Pacing & retries" description="Delays and retry limits between browser actions.">
          <Row label="Min delay (seconds)">
            <NumberInput
              value={draft.min_delay_seconds}
              onChange={(min_delay_seconds) => setDraft({ ...draft, min_delay_seconds })}
            />
          </Row>
          <Row label="Max delay (seconds)">
            <NumberInput
              value={draft.max_delay_seconds}
              onChange={(max_delay_seconds) => setDraft({ ...draft, max_delay_seconds })}
            />
          </Row>
          <Row label="Retry limit">
            <NumberInput
              value={draft.retry_limit}
              onChange={(retry_limit) => setDraft({ ...draft, retry_limit })}
            />
          </Row>
        </Section>

        <Section title="Workers" description="Concurrency and account daily defaults.">
          <Row
            label={`Worker concurrency: ${draft.worker_concurrency ?? 1}`}
            description="Maximum simultaneous account workers."
          >
            <Slider
              value={[draft.worker_concurrency ?? 1]}
              onValueChange={([worker_concurrency]) => setDraft({ ...draft, worker_concurrency })}
              min={1}
              max={20}
              step={1}
              className="w-full sm:w-56"
            />
          </Row>
          <Row label="Default daily message limit">
            <NumberInput
              value={draft.daily_message_limit}
              onChange={(daily_message_limit) => setDraft({ ...draft, daily_message_limit })}
            />
          </Row>
        </Section>

        <div className="flex justify-end">
          <Button onClick={save} disabled={saveMutation.isPending}>
            {saveMutation.isPending ? "Saving..." : "Save changes"}
          </Button>
        </div>
      </div>
    </>
  );
}

function StatusTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  tone: "success" | "warning" | "destructive";
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <Icon className="size-4 text-muted-foreground" />
        <DotBadge tone={tone} label={value} />
      </div>
      <div className="text-sm font-medium">{label}</div>
    </div>
  );
}

function Section({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-card">
      <div className="border-b px-5 py-4">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
      </div>
      <div className="divide-y">{children}</div>
    </div>
  );
}

function Row({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-4">
      <div>
        <Label className="text-sm">{label}</Label>
        {description ? <p className="mt-0.5 text-xs text-muted-foreground">{description}</p> : null}
      </div>
      <div>{children}</div>
    </div>
  );
}

function NumberInput({ value, onChange }: { value?: number; onChange: (value: number) => void }) {
  return (
    <Input
      type="number"
      value={value ?? 0}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-32"
    />
  );
}
