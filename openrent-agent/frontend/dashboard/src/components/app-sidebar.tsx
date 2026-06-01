import { Link, useRouterState } from "@tanstack/react-router";
import { LayoutDashboard, Users, Search, MessageSquare, ScrollText, Settings, Zap, Cpu } from "lucide-react";
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
} from "@/components/ui/sidebar";

const items = [
  { title: "Dashboard", url: "/", icon: LayoutDashboard },
  { title: "Accounts", url: "/accounts", icon: Users },
  { title: "Workers", url: "/workers", icon: Cpu },
  { title: "Search Profiles", url: "/search-profiles", icon: Search },
  { title: "Leads", url: "/leads", icon: MessageSquare },
  { title: "Logs", url: "/logs", icon: ScrollText },
  { title: "Settings", url: "/settings", icon: Settings },
];

export function AppSidebar() {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const isActive = (url: string) => (url === "/" ? path === "/" : path.startsWith(url));

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="border-b bg-sidebar">
        <div className="flex items-center gap-2 px-2 py-2">
          <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-sm">
            <Zap className="size-4" />
          </div>
          <div className="flex flex-col leading-tight group-data-[collapsible=icon]:hidden">
            <span className="text-sm font-semibold">RentPilot</span>
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
                    <Link to={item.url}>
                      <item.icon className="size-4" />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
