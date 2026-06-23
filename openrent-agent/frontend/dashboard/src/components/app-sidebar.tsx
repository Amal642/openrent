import { Link, useRouterState } from "@tanstack/react-router";
import { AlertTriangle, Brain, Cpu, LayoutDashboard, MapPin, MessageSquare, Network, ScrollText, Search, Settings, Users, Zap } from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useQuery } from "@tanstack/react-query";
import { getFailedAccountsCount } from "@/lib/api";

const items = [
  { title: "Dashboard", url: "/", icon: LayoutDashboard },
  { title: "Accounts", url: "/accounts", icon: Users },
  { title: "Workers", url: "/workers", icon: Cpu },
  { title: "Proxies", url: "/proxies", icon: Network },
  { title: "Locations", url: "/locations", icon: MapPin },
  { title: "Search Profiles", url: "/search-profiles", icon: Search },
  { title: "Leads", url: "/leads", icon: MessageSquare },
  { title: "Logs", url: "/logs", icon: ScrollText },
  { title: "Settings", url: "/settings", icon: Settings },
  { title: "AI Advisor 🧠", url: "/advisor", icon: Brain },
];

export function AppSidebar() {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const { isMobile, setOpenMobile } = useSidebar();
  const isActive = (url: string) => (url === "/" ? path === "/" : path.startsWith(url));
  const closeMobileSidebar = () => {
    if (isMobile) {
      setOpenMobile(false);
    }
  };

  const { data: failedCount = 0 } = useQuery({
    queryKey: ["failed-accounts-count"],
    queryFn: getFailedAccountsCount,
    refetchInterval: 60000,
  });

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="border-b bg-sidebar">
        <div className="flex items-center gap-2 px-2 py-2">
          <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-sm">
            <Zap className="size-4" />
          </div>
          <div className="flex flex-col leading-tight group-data-[collapsible=icon]:hidden">
            <span className="text-sm font-semibold">Land Royal</span>
            <span className="text-[11px] text-muted-foreground">Operations workspace</span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent className="bg-sidebar">
        <SidebarGroup>
          <SidebarGroupLabel className="text-[11px]">Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.url}>
                  <SidebarMenuButton asChild isActive={isActive(item.url)} tooltip={item.title}>
                    <Link to={item.url} onClick={closeMobileSidebar}>
                      <item.icon className="size-4" />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
              <SidebarMenuItem>
                <SidebarMenuButton
                  asChild
                  isActive={isActive("/failed-accounts")}
                  tooltip="Failed Accounts"
                >
                  <Link
                    to="/failed-accounts"
                    className="flex items-center gap-2"
                    onClick={closeMobileSidebar}
                  >
                    <AlertTriangle className="size-4" />
                    <span className="flex-1">Failed Accounts</span>
                    {failedCount > 0 && (
                      <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1.5 text-[10px] font-semibold text-destructive-foreground">
                        {failedCount}
                      </span>
                    )}
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
