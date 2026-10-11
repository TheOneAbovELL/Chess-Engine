import { useQuery } from "@tanstack/react-query";
import {
  BookOpenText,
  CheckCircle2,
  Cpu,
  Download,
  FlaskConical,
  LayoutDashboard,
  Library,
  Menu,
  Microscope,
  Settings,
  Swords,
  X,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Toaster } from "./Toaster";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/play", label: "Play", icon: Swords },
  { to: "/analysis", label: "Analysis", icon: Microscope },
  { to: "/games", label: "Game History", icon: Library },
  { to: "/import", label: "Import Games", icon: Download },
  { to: "/explorer", label: "Opening Explorer", icon: BookOpenText },
  { to: "/lab", label: "Engine Lab", icon: FlaskConical },
  { to: "/settings", label: "Settings", icon: Settings },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 64 64" className="size-8" aria-hidden>
        <rect width="64" height="64" rx="14" fill="#1d2125" />
        <path fill="#d6a756" d="M24 50h16l-2-6h-12zM22 54h20v4H22zM32 8a5 5 0 0 1 2 9.6V20h5v4h-4l3 18H26l3-18h-4v-4h5v-2.4A5 5 0 0 1 32 8z" />
      </svg>
      <div className="leading-tight">
        <p className="text-[15px] font-semibold tracking-tight text-ink-50">ChessLab</p>
        <p className="text-[10px] uppercase tracking-[0.14em] text-ink-400">Analysis laboratory</p>
      </div>
    </div>
  );
}

function ServerStatus() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000, retry: false });
  if (health.isPending) return <p className="text-xs text-ink-400">Connecting…</p>;
  if (health.isError)
    return (
      <p className="flex items-center gap-1.5 text-xs text-[#ff8f88]">
        <XCircle className="size-3.5" /> Server offline
      </p>
    );
  const engines = health.data.engines;
  return (
    <div className="space-y-1 text-xs">
      <p className="flex items-center gap-1.5 text-ink-300">
        <CheckCircle2 className="size-3.5 text-q-best" /> Local server · v{health.data.version}
      </p>
      <NavLink to="/settings#engines" className="flex items-center gap-1.5 text-ink-300 hover:text-ink-100">
        <Cpu className={cn("size-3.5", engines.stockfish === "unavailable" ? "text-q-inaccuracy" : "text-q-best")} />
        Stockfish {engines.stockfish === "unavailable" ? "not found" : engines.stockfish}
      </NavLink>
    </div>
  );
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="space-y-0.5" aria-label="Main">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              isActive ? "bg-ink-750 text-ink-50 shadow-[inset_2px_0_0_var(--color-brass-500)]" : "text-ink-300 hover:bg-ink-800 hover:text-ink-100",
            )
          }
        >
          <Icon className="size-4 shrink-0" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

export function Layout() {
  const location = useLocation();
  // The menu belongs to the page it was opened on, so navigating closes it.
  const [menuPath, setMenuPath] = useState<string | null>(null);
  const menuOpen = menuPath === location.pathname;
  const setMenuOpen = (open: boolean) => setMenuPath(open ? location.pathname : null);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[232px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-brass-500 focus:px-3 focus:py-2 focus:text-ink-950">
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-ink-800 bg-ink-900/80 px-3 py-5 lg:flex">
        <div className="px-2">
          <Logo />
        </div>
        <div className="mt-7 flex-1 overflow-y-auto">
          <NavItems />
        </div>
        <div className="border-t border-ink-800 px-2 pt-4">
          <ServerStatus />
        </div>
      </aside>

      {/* Mobile header */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-ink-800 bg-ink-900/95 px-4 py-2.5 backdrop-blur lg:hidden">
        <Logo />
        <button
          type="button"
          className="inline-flex size-10 items-center justify-center rounded-lg text-ink-200 hover:bg-ink-800"
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(!menuOpen)}
        >
          {menuOpen ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </header>
      {menuOpen && (
        <div className="fixed inset-x-0 top-[57px] z-20 border-b border-ink-800 bg-ink-900 px-3 py-3 shadow-2xl lg:hidden">
          <NavItems onNavigate={() => setMenuOpen(false)} />
          <div className="mt-3 border-t border-ink-800 px-2 pt-3">
            <ServerStatus />
          </div>
        </div>
      )}

      <main id="main" className="min-w-0 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <div className="mx-auto max-w-[1500px]">
          <Outlet />
        </div>
      </main>
      <Toaster />
    </div>
  );
}
