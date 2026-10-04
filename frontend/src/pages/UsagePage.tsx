import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import Skeleton from "../components/Skeleton";
import BarChart from "../components/BarChart";
import { dayTime } from "../lib/fmt";

type U = {
  days: { day: string; credits: number; llm_calls: number; tokens: number; emails: number }[];
  total: { credits: number; llm_calls: number; tokens: number; emails: number };
  credits_left: number | null;
  per_run: { id: string; campaign: string | null; profile: string | null; started_at: string | null; credits: number; llm_calls: number; tokens: number; qualified: number }[];
};

export default function UsagePage() {
  const nav = useNavigate();
  const [days, setDays] = useState(30);
  const { data: u, isLoading } = useQuery({ queryKey: ["usage", days], queryFn: () => api<U>(`/usage?days=${days}`), refetchInterval: 60000 });
  return (
    <div className="page">
      <div className="page-head">
        <span>Usage & credits</span>
        <select className="select" style={{ width: 130 }} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </select>
      </div>
      <div className="page-body flex flex-col gap-4">
        {isLoading && <Skeleton rows={5} />}
        {u && (
          <>
            <div className="grid grid-cols-4 gap-3">
              <div className="card"><div className="label">Credits left</div><div className="text-2xl font-semibold">{u.credits_left ?? "—"}</div>
                {u.credits_left == null && <div style={{ fontSize: 12, color: "var(--text-faint)" }}>Set a balance in Settings</div>}</div>
              <div className="card"><div className="label">Firecrawl credits used</div><div className="text-2xl font-semibold">{u.total.credits}</div></div>
              <div className="card"><div className="label">LLM tokens</div><div className="text-2xl font-semibold">{u.total.tokens.toLocaleString()}</div><div style={{ fontSize: 12, color: "var(--text-faint)" }}>{u.total.llm_calls} calls</div></div>
              <div className="card"><div className="label">Emails sent</div><div className="text-2xl font-semibold">{u.total.emails}</div></div>
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="card"><span className="label">Firecrawl credits per day</span><BarChart unit="credits" data={u.days.map((d) => ({ label: d.day, value: d.credits }))} /></div>
              <div className="card"><span className="label">LLM tokens per day</span><BarChart unit="tokens" data={u.days.map((d) => ({ label: d.day, value: d.tokens }))} /></div>
              <div className="card"><span className="label">Emails per day (dry runs count too)</span><BarChart unit="emails" data={u.days.map((d) => ({ label: d.day, value: d.emails }))} /></div>
            </div>
            <div>
              <span className="label">Per run</span>
              <table className="table">
                <thead><tr><th>Campaign</th><th>Profile</th><th>Started</th><th>Credits</th><th>LLM calls</th><th>Tokens</th><th>Qualified</th><th>Credits per qualified</th></tr></thead>
                <tbody>
                  {u.per_run.map((r) => (
                    <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => nav(`/activity?run=${r.id}`)}>
                      <td>{r.campaign}</td><td>{r.profile ?? "—"}</td><td>{dayTime(r.started_at)}</td><td>{r.credits}</td><td>{r.llm_calls}</td><td>{r.tokens.toLocaleString()}</td>
                      <td>{r.qualified}</td><td>{r.qualified ? (r.credits / r.qualified).toFixed(1) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
