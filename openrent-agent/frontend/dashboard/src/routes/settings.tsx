import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — RentPilot" },
      { name: "description", content: "Global automation settings." },
    ],
  }),
  component: SettingsPage,
});

function SettingsPage() {
  const [aiAuto, setAiAuto] = useState(true);
  const [delayMin, setDelayMin] = useState(45);
  const [delayMax, setDelayMax] = useState(180);
  const [retries, setRetries] = useState(3);
  const [model, setModel] = useState("gpt-4o-mini");
  const [concurrency, setConcurrency] = useState([6]);
  const [defaultLimit, setDefaultLimit] = useState(80);

  const save = (section: string) => () => toast.success(`${section} saved`);

  return (
    <>
      <PageHeader title="Settings" description="Global automation and worker configuration." />

      <div className="space-y-4 max-w-3xl">
        <Section title="AI" description="OpenAI behavior and auto-send.">
          <Row label="Auto-send AI replies" description="Send generated replies without operator review.">
            <Switch checked={aiAuto} onCheckedChange={setAiAuto} />
          </Row>
          <Row label="OpenAI model">
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger className="w-56"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="gpt-4o">gpt-4o</SelectItem>
                <SelectItem value="gpt-4o-mini">gpt-4o-mini</SelectItem>
                <SelectItem value="gpt-4.1">gpt-4.1</SelectItem>
                <SelectItem value="gpt-4.1-mini">gpt-4.1-mini</SelectItem>
              </SelectContent>
            </Select>
          </Row>
          <Footer onSave={save("AI settings")} />
        </Section>

        <Section title="Pacing & retries" description="Delays and retry limits between actions.">
          <Row label="Min delay (seconds)"><Input type="number" value={delayMin} onChange={(e) => setDelayMin(+e.target.value)} className="w-32" /></Row>
          <Row label="Max delay (seconds)"><Input type="number" value={delayMax} onChange={(e) => setDelayMax(+e.target.value)} className="w-32" /></Row>
          <Row label="Retry limit"><Input type="number" value={retries} onChange={(e) => setRetries(+e.target.value)} className="w-32" /></Row>
          <Footer onSave={save("Pacing settings")} />
        </Section>

        <Section title="Workers" description="Scaling and per-account defaults.">
          <Row label={`Worker concurrency: ${concurrency[0]}`} description="Max simultaneous worker processes.">
            <Slider value={concurrency} onValueChange={setConcurrency} min={1} max={20} step={1} className="w-56" />
          </Row>
          <Row label="Default daily message limit"><Input type="number" value={defaultLimit} onChange={(e) => setDefaultLimit(+e.target.value)} className="w-32" /></Row>
          <Footer onSave={save("Worker settings")} />
        </Section>
      </div>
    </>
  );
}

function Section({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-card">
      <div className="px-5 py-4 border-b">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
      </div>
      <div className="divide-y">{children}</div>
    </div>
  );
}

function Row({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between px-5 py-4 gap-4">
      <div>
        <Label className="text-sm">{label}</Label>
        {description && <p className="text-xs text-muted-foreground mt-0.5">{description}</p>}
      </div>
      <div>{children}</div>
    </div>
  );
}

function Footer({ onSave }: { onSave: () => void }) {
  return (
    <div className="px-5 py-3 bg-muted/30 flex justify-end">
      <Button size="sm" onClick={onSave}>Save changes</Button>
    </div>
  );
}
