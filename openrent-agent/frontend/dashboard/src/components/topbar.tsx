import { useEffect, useState } from "react";
import { Sun, Moon } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { DotBadge } from "@/components/status-badge";
import { getHealth } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";

export function Topbar() {
  const [dark, setDark] = useState(true);
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30000,
  });
  useEffect(() => {
    const stored = localStorage.getItem("theme");
    const isDark = stored ? stored === "dark" : true;
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
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/80 backdrop-blur px-3">
      <SidebarTrigger />
      <Separator orientation="vertical" className="h-5" />
      <div className="flex flex-1 items-center gap-2 text-sm">
        <span className="font-medium">OpenRent command center</span>
        <DotBadge tone={data?.status === "running" ? "success" : "warning"} label={data?.status ?? "checking"} />
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
          {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </Button>
        <div className="flex size-8 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-medium">
          OP
        </div>
      </div>
    </header>
  );
}
