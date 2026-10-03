export const dayTime = (s: string | null | undefined) => (s ? new Date(s).toLocaleString() : "—");
export const pct = (r: number | null | undefined) => (r == null ? "—" : `${Math.round(r * 1000) / 10}%`);
export const LEAD_STAGES = ["new", "ready", "in_sequence", "replied", "meeting", "won", "lost", "bounced", "unsubscribed"] as const;
export const stageColor = (s: string) =>
  ["won", "meeting", "replied"].includes(s) ? "var(--ok)" : ["lost", "bounced", "unsubscribed"].includes(s) ? "var(--bad)" : s === "in_sequence" ? "var(--warn)" : "var(--text-faint)";
export const companyColor = (s: string) =>
  ["qualified", "judged"].includes(s) ? "var(--ok)" : ["failed", "rejected"].includes(s) ? "var(--bad)" : ["maybe", "no_contact", "filtered_out"].includes(s) ? "var(--warn)" : "var(--text-faint)";
