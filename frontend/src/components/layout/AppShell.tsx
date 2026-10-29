import * as PopoverPrimitive from "@radix-ui/react-popover";
import { useQuery } from "@tanstack/react-query";
import {
  Bell, Building2, Check, ChevronsLeft, ChevronsRight, LogOut, Menu as MenuIcon, Moon, Search, Sun, UserRound,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Sheet } from "@/components/ui/overlay";
import { Badge, Kbd, Tip } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { cn, timeAgo } from "@/lib/utils";
import { CommandPalette } from "./CommandPalette";
import { Logo } from "./Logo";
import { NAV, ROUTE_TITLES } from "./nav";

function useCounts() {
  const { can } = useAuth();
  return useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<{ items: any[]; unread: number }>("/notifications"),
    refetchInterval: 60_000,
    enabled: can("dashboard.read"),
  });
}

function SidebarNav({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const { can } = useAuth();
  const { data } = useCounts();
  const review = data?.items.find((i) => i.kind === "review")?.title?.match(/^\d+/)?.[0];
  const alerts = data?.items.filter((i) => i.kind === "alert").length;
  return (
    <nav aria-label="Primary" className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
      {NAV.map((g) => {
        const items = g.items.filter((i) => can(i.perm));
        if (!items.length) return null;
        return (
          <div key={g.label}>
            {!collapsed && <div className="mb-1.5 px-2 text-[10.5px] font-medium uppercase tracking-[0.14em] text-fg-subtle">{g.label}</div>}
            <ul className="space-y-0.5">
              {items.map((i) => {
                const badge = i.badgeKey === "review" ? review : i.badgeKey === "alerts" && alerts ? String(alerts) : undefined;
                const link = (
                  <NavLink to={i.to} onClick={onNavigate}
                    className={({ isActive }) => cn("group flex h-8 items-center gap-2.5 rounded-md px-2 text-[13.5px] transition-colors",
                      isActive ? "bg-surface-3 text-fg shadow-card" : "text-fg-muted hover:bg-surface-2 hover:text-fg", collapsed && "justify-center px-0")}>
                    {({ isActive }) => (
                      <>
                        <i.icon className={cn("size-4 shrink-0", isActive ? "text-accent" : "text-fg-subtle group-hover:text-fg-muted")} />
                        {!collapsed && <span className="flex-1 truncate">{i.label}</span>}
                        {!collapsed && badge && (
                          <span className={cn("rounded-full px-1.5 text-[10.5px] font-semibold tabular", i.badgeKey === "alerts" ? "bg-danger-soft text-danger" : "bg-warn-soft text-warn")}>{badge}</span>
                        )}
                      </>
                    )}
                  </NavLink>
                );
                return <li key={i.to}>{collapsed ? <Tip content={i.label} side="right">{link}</Tip> : link}</li>;
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function Notifications() {
  const { data } = useCounts();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Notifications (${data?.unread ?? 0})`} className="relative">
          <Bell />
          {!!data?.unread && <span className="absolute right-2 top-2 size-2 rounded-full bg-danger ring-2 ring-canvas" />}
        </Button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content align="end" sideOffset={8} className="z-[60] w-[360px] rounded-lg border border-line-strong bg-surface shadow-pop animate-fade-in">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <span className="text-sm font-semibold">Notifications</span>
            <Badge tone={data?.unread ? "danger" : "neutral"}>{data?.unread ?? 0} active</Badge>
          </div>
          <ul className="max-h-[420px] divide-y divide-line overflow-y-auto">
            {!data?.items.length && <li className="px-4 py-8 text-center text-sm text-fg-muted">You're all caught up.</li>}
            {data?.items.map((n, i) => (
              <li key={i}>
                <button onClick={() => { setOpen(false); nav(n.link); }} className="flex w-full gap-3 px-4 py-3 text-left hover:bg-surface-2">
                  <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.severity === "critical" ? "bg-danger" : n.severity === "high" ? "bg-warn" : "bg-info")} />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium text-fg">{n.title}</span>
                    <span className="mt-0.5 block truncate text-[12.5px] text-fg-muted">{n.body}</span>
                    {n.at && <span className="mt-0.5 block text-[11px] text-fg-subtle">{timeAgo(n.at)}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

function Breadcrumbs() {
  const loc = useLocation();
  const parts = loc.pathname.split("/").filter(Boolean);
  return (
    <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 text-[13px] text-fg-subtle md:flex">
      <Link to="/dashboard" className="hover:text-fg">Workspace</Link>
      {parts.map((p, i) => (
        <span key={i} className="flex items-center gap-1.5">
          <span aria-hidden>/</span>
          <span className={i === parts.length - 1 ? "truncate text-fg" : ""}>{ROUTE_TITLES[p] ?? decodeURIComponent(p)}</span>
        </span>
      ))}
    </nav>
  );
}

export function UserMenu() {
  const { user, signOut } = useAuth();
  const nav = useNavigate();
  if (!user) return null;
  const initials = user.name.split(" ").filter((w) => /^[A-Z]/.test(w)).map((w) => w[0]).slice(0, 2).join("");
  return (
    <Menu>
      <MenuTrigger asChild>
        <button className="flex items-center gap-2 rounded-md p-1 pr-2 hover:bg-surface-2" aria-label="Account menu">
          <span className="grid size-7 place-items-center rounded-full bg-accent-soft text-[11.5px] font-semibold text-accent">{initials}</span>
          <span className="hidden text-left leading-tight lg:block">
            <span className="block text-[12.5px] font-medium text-fg">{user.name}</span>
            <span className="block text-[11px] text-fg-subtle">{user.role_label}</span>
          </span>
        </button>
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>{user.email}</MenuLabel>
        <MenuItem onSelect={() => nav(user.role === "candidate" ? "/assessment" : "/settings")}><UserRound />{user.role_label}</MenuItem>
        <MenuSeparator />
        <MenuItem onSelect={async () => { await signOut(); nav("/login", { replace: true }); }} danger><LogOut />Sign out</MenuItem>
      </MenuContent>
    </Menu>
  );
}

function OrgSwitcher({ collapsed }: { collapsed: boolean }) {
  const { user } = useAuth();
  return (
    <Menu>
      <MenuTrigger asChild>
        <button className={cn("flex w-full items-center gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-2 text-left hover:border-line-strong", collapsed && "justify-center px-0")} aria-label="Switch organization">
          <Building2 className="size-4 shrink-0 text-fg-subtle" />
          {!collapsed && <span className="min-w-0 flex-1"><span className="block truncate text-[12.5px] font-medium">{user?.organization.name}</span>
            <span className="block text-[10.5px] text-fg-subtle">Tenant · demo mode</span></span>}
        </button>
      </MenuTrigger>
      <MenuContent align="start">
        <MenuLabel>Organizations</MenuLabel>
        <MenuItem><Check className="!text-accent" />{user?.organization.name}</MenuItem>
        <MenuItem disabled>Multi-tenant switching: single tenant in prototype</MenuItem>
      </MenuContent>
    </Menu>
  );
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <Button variant="ghost" size="icon" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
      {theme === "dark" ? <Sun /> : <Moon />}
    </Button>
  );
}

export function AppShell({ children }: { children?: ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("ag.sidebar") === "1");
  const [mobile, setMobile] = useState(false);
  const [palette, setPalette] = useState(false);
  useEffect(() => localStorage.setItem("ag.sidebar", collapsed ? "1" : "0"), [collapsed]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  return (
    <div className="flex h-full">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[80] focus:rounded-md focus:bg-accent-strong focus:px-3 focus:py-2 focus:text-white">Skip to content</a>
      <aside className={cn("hidden shrink-0 flex-col border-r border-line bg-surface transition-[width] duration-200 md:flex", collapsed ? "w-[64px]" : "w-[248px]")}>
        <div className={cn("flex h-14 items-center border-b border-line px-4", collapsed && "justify-center px-0")}>
          <Link to="/dashboard" aria-label="AptiGuard AI home"><Logo collapsed={collapsed} /></Link>
        </div>
        <div className={cn("px-3 pt-3", collapsed && "px-2")}><OrgSwitcher collapsed={collapsed} /></div>
        <SidebarNav collapsed={collapsed} />
        <div className="border-t border-line p-2">
          <Button variant="ghost" size="sm" className={cn("w-full", collapsed ? "justify-center" : "justify-start")} onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            {collapsed ? <ChevronsRight /> : <><ChevronsLeft />Collapse</>}
          </Button>
        </div>
      </aside>
      <Sheet open={mobile} onOpenChange={setMobile} title={<Logo />} side="left" width="max-w-[280px]">
        <div className="px-3 pt-3"><OrgSwitcher collapsed={false} /></div>
        <SidebarNav collapsed={false} onNavigate={() => setMobile(false)} />
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-canvas/85 px-4 backdrop-blur md:px-6">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setMobile(true)} aria-label="Open navigation"><MenuIcon /></Button>
          <Breadcrumbs />
          <div className="flex-1" />
          <button onClick={() => setPalette(true)} className="hidden h-8 w-64 items-center gap-2 rounded-md border border-line-strong bg-surface-2 px-2.5 text-[13px] text-fg-subtle hover:border-fg-subtle/40 sm:flex" aria-label="Open search">
            <Search className="size-3.5" /><span className="flex-1 text-left">Search…</span><Kbd>⌘K</Kbd>
          </button>
          <Button variant="ghost" size="icon" className="sm:hidden" onClick={() => setPalette(true)} aria-label="Search"><Search /></Button>
          <ThemeToggle />
          <Notifications />
          <UserMenu />
        </header>
        <main id="main" className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1440px] px-4 py-6 md:px-8 md:py-8 animate-fade-in">{children ?? <Outlet />}</div>
        </main>
      </div>
      <CommandPalette open={palette} onOpenChange={setPalette} />
    </div>
  );
}
