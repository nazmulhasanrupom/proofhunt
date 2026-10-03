import { NavLink, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { nav } from "../nav";
import { api } from "../api/client";
import { useSeenAt } from "../lib/unread";

export default function Sidebar() {
  const { data: s } = useQuery({
    queryKey: ["settings"], refetchInterval: 60000,
    queryFn: () => api<{ sender_name: string | null; gmail_connected: boolean; gmail_address: string | null }>("/settings"),
  });
  const { data: c } = useQuery({ queryKey: ["counts"], refetchInterval: 30000, queryFn: () => api<{ leads: number; review: number; reply_times: string[] }>("/counts") });
  const seen = useSeenAt();
  const badge: Record<string, number> = {
    "/leads": c?.leads ?? 0, "/review": c?.review ?? 0, "/replies": c?.reply_times.filter((t) => t > seen).length ?? 0,
  };
  const reconnect = !!s?.gmail_address && !s?.gmail_connected;
  const dot = s?.gmail_connected ? "var(--ok)" : reconnect ? "var(--bad)" : "var(--text-faint)";
  const gmailText = s?.gmail_connected ? s.gmail_address : reconnect ? "Reconnect Gmail" : "Gmail not connected";
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r" style={{ background: "var(--bg-1)", borderColor: "var(--border)" }}>
      <div className="flex items-center gap-2 px-4 py-3 text-sm font-semibold"><img src="/favicon.svg" width={20} height={20} alt="" />Proofhunt</div>
      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {nav.map((g) => (
          <div key={g.label} className="mb-3">
            <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-faint)" }}>
              {g.label}
            </div>
            {g.items.map(({ path, label, icon: Icon }) => (
              <NavLink
                key={path}
                to={path}
                end={path === "/"}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors"
                style={({ isActive }) => ({
                  background: isActive ? "var(--bg-4)" : "transparent",
                  color: isActive ? "#fff" : "var(--text-muted)",
                  transitionDuration: "120ms",
                })}
              >
                <Icon size={16} strokeWidth={1.75} />
                <span className="flex-1">{label}</span>
                {badge[path] > 0 && <span className="badge">{badge[path]}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <Link to="/settings" className="flex items-center gap-2 border-t px-3 py-3" style={{ borderColor: "var(--border)" }}>
        <div className="flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold" style={{ background: "var(--bg-4)" }}>
          {(s?.sender_name?.[0] ?? "?").toUpperCase()}
        </div>
        <div className="min-w-0 flex-1 text-xs">
          <div className="truncate">{s?.sender_name || "Not set up"}</div>
          <div className="flex items-center gap-1" style={{ color: "var(--text-faint)" }}>
            <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: dot }} />
            <span className="truncate">{gmailText}</span>
          </div>
        </div>
      </Link>
    </aside>
  );
}
