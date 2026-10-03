import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import Empty from "../components/Empty";
import Skeleton from "../components/Skeleton";
import { dayTime, pct } from "../lib/fmt";

export type Rate = { key: string; sent: number; replied: number; rate: number };
type Stats = {
  cards: { qualified: number; sent_week: number; sent_week_dry: number; reply_rate: number | null; credits_left: number | null };
  funnel: { label: string; count: number }[];
  reply_rates: Record<string, Rate[]>;
  top_signals: Rate[];
  hot_replies: { id: string; from_email: string; received_at: string; snippet: string; leads: { id: string; companies: { domain: string; name: string | null } } }[];
};
const DIMS: [string, string][] = [["offer_row", "Offer row"], ["signal", "Signal"], ["country", "Country"], ["size", "Size"], ["email_kind", "Email kind"], ["score_band", "Score band"]];

export default function DashboardPage() {
  const { data: s, isLoading } = useQuery({ queryKey: ["stats"], queryFn: () => api<Stats>("/stats"), refetchInterval: 30000 });
  const top = Math.max(1, s?.funnel[0]?.count ?? 1);
  return (
    <div className="page">
      <div className="page-head"><span>Dashboard</span></div>
      <div className="page-body flex flex-col gap-4">
        {isLoading && <Skeleton rows={5} />}
        {s && (
          <>
            <div className="grid grid-cols-4 gap-3">
              <Card k="Qualified leads" v={s.cards.qualified} />
              <Card k="Sent this week" v={s.cards.sent_week} note={s.cards.sent_week_dry ? `+${s.cards.sent_week_dry} dry run` : undefined} />
              <Card k="Reply rate" v={pct(s.cards.reply_rate)} />
              <Card k="Credits left" v={s.cards.credits_left ?? "—"} note={s.cards.credits_left == null ? "Set a balance in Settings" : undefined} />
            </div>
            <div className="card flex flex-col gap-2">
              <span className="label">Funnel</span>
              {s.funnel.map((f, i) => (
                <div key={f.label} className="flex items-center gap-3" style={{ fontSize: 13 }}>
                  <span className="w-28" style={{ color: "var(--text-muted)" }}>{f.label}</span>
                  <div className="bar flex-1"><div style={{ width: `${(f.count / top) * 100}%` }} /></div>
                  <span className="w-24 text-right">{f.count}{i > 0 && s.funnel[i - 1].count > 0 && <span style={{ color: "var(--text-faint)" }}> · {pct(f.count / s.funnel[i - 1].count)}</span>}</span>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="card">
                <span className="label">Top 3 signals by reply rate</span>
                {!s.top_signals.length && <div style={{ color: "var(--text-faint)", fontSize: 13 }}>Needs sent emails first. Use this to edit the Offer map.</div>}
                {s.top_signals.map((r) => (
                  <div key={r.key} className="flex justify-between py-1" style={{ fontSize: 13 }}>
                    <span className="truncate">{r.key}</span><span>{pct(r.rate)} <span style={{ color: "var(--text-faint)" }}>({r.replied}/{r.sent})</span></span>
                  </div>
                ))}
              </div>
              <div className="card">
                <span className="label">Hot replies</span>
                {!s.hot_replies.length && <div style={{ color: "var(--text-faint)", fontSize: 13 }}>No interested replies yet.</div>}
                {s.hot_replies.map((r) => (
                  <Link key={r.id} to="/replies" className="block py-1" style={{ fontSize: 13 }}>
                    <div className="flex justify-between"><span>{r.leads.companies.name || r.leads.companies.domain}</span><span style={{ color: "var(--text-faint)" }}>{dayTime(r.received_at)}</span></div>
                    <div className="truncate" style={{ color: "var(--text-muted)" }}>{r.snippet}</div>
                  </Link>
                ))}
              </div>
            </div>
            <div className="card">
              <span className="label">Reply rate by group (leads that got an email)</span>
              {!Object.values(s.reply_rates).some((v) => v.length) && <Empty text="No sent emails yet, so no reply rates." />}
              <div className="grid grid-cols-3 gap-4">
                {DIMS.map(([k, name]) => !!s.reply_rates[k]?.length && (
                  <div key={k}>
                    <div className="mb-1 font-medium" style={{ fontSize: 13 }}>{name}</div>
                    {s.reply_rates[k].map((r) => (
                      <div key={r.key} className="flex justify-between" style={{ fontSize: 12, color: "var(--text-muted)" }}>
                        <span className="truncate">{r.key}</span><span>{pct(r.rate)} ({r.replied}/{r.sent})</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Card({ k, v, note }: { k: string; v: string | number; note?: string }) {
  return <div className="card"><div className="label">{k}</div><div className="text-2xl font-semibold">{v}</div>{note && <div style={{ fontSize: 12, color: "var(--text-faint)" }}>{note}</div>}</div>;
}
