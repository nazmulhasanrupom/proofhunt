import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";

export type SendStatus = {
  dry_run: boolean; gmail_connected: boolean; gmail_address: string | null; sender_name: string;
  blockers: string[]; cap: number; sent_24h: number;
};

export function useSendStatus() {
  return useQuery({ queryKey: ["sending-status"], queryFn: () => api<SendStatus>("/sending/status"), refetchInterval: 30000 });
}

/** Thin warning strip. Shows when nothing is really sent, or when sending is blocked. */
export default function SendBanner() {
  const { data: s } = useSendStatus();
  if (!s) return null;
  const msgs: string[] = [];
  if (s.dry_run) msgs.push("DRY_RUN is on. Nothing is really sent.");
  if (!s.gmail_connected && !s.blockers.some((b) => b.includes("Gmail"))) msgs.push("Gmail is not connected.");
  msgs.push(...s.blockers);
  if (!msgs.length) return null;
  return (
    <div className="flex items-center gap-2 border-b px-6 py-2" style={{ borderColor: "var(--border)", background: "var(--bg-3)", fontSize: 12 }}>
      <span className="dot" style={{ background: "var(--warn)", marginRight: 0 }} />
      <span style={{ color: "var(--text-muted)" }}>{msgs.join(" · ")}</span>
      <Link to="/settings" style={{ color: "var(--text)", textDecoration: "underline" }}>Settings</Link>
    </div>
  );
}
