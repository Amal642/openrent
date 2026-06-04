import { useEffect, useState } from "react";
import { Sun, Moon, Search } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { DotBadge } from "@/components/status-badge";
import { getHealth } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";

export function Topbar() {
  const [dark, setDark] = useState(false);
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30000,
  });
  useEffect(() => {
    const stored = localStorage.getItem("theme");
    const isDark = stored ? stored === "dark" : false;
    setDark(isDark);
    document.documentElement.classList.toggle("dark", isDark);
  }, []);
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  };
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b bg-background/85 backdrop-blur px-3 md:px-5">
      <SidebarTrigger />
      <Separator orientation="vertical" className="h-5" />
      <div className="flex flex-1 items-center gap-3 text-sm">
        <div className="hidden min-w-0 flex-col sm:flex">
          <span className="font-semibold leading-tight">OpenRent command center</span>
          <span className="text-xs text-muted-foreground">Live outreach, replies, and workers</span>
        </div>
        <DotBadge tone={data?.status === "running" ? "success" : "warning"} label={data?.status ?? "checking"} />
      </div>
      <div className="ml-auto flex items-center gap-2">
        <a
          href="/leads"
          className="hidden h-9 w-56 items-center gap-2 rounded-md border bg-card px-3 text-sm text-muted-foreground transition hover:text-foreground md:flex"
        >
          <Search className="size-4" />
          <span>Search leads</span>
        </a>
        <Button variant="outline" size="icon" onClick={toggle} aria-label="Toggle theme">
          {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </Button>
        <div className="flex size-9 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-semibold shadow-sm">
          OP
        </div>
      </div>
    </header>
  );
}
