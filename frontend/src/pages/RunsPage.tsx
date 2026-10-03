import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import Empty from "../components/Empty";
import Skeleton from "../components/Skeleton";

export type Run = {
  id: string; status: string; stage: string | null; counters: Record<string, number>; credits_used: number; llm_calls: number;
  error: string | null; started_at: string | null; campaigns?: { name: string };
};

export const statusColor = (s: string) =>
  s === "done" ? "var(--ok)" : s === "failed" || s === "cancelled" ? "var(--bad)" : s === "paused" ? "var(--warn)" : s === "running" ? "var(--ok)" : "var(--text-faint)";

export default function RunsPage() {
  const nav = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["runs"], queryFn: () => api<Run[]>("/runs"), refetchInterval: 5000 });
  return (
    <div className="page">
      <div className="page-head"><span>Runs</span></div>
      <div className="page-body">
        {isLoading && <Skeleton />}
        {data?.length === 0 && <Empty text="No runs yet. Start one from Campaigns." />}
        {data && data.length > 0 && (
          <table className="table">
            <thead><tr><th>Campaign</th><th>Status</th><th>Stage</th><th>Companies</th><th>Qualified</th><th>Credits</th><th>LLM calls</th><th>Started</th></tr></thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => nav(`/activity?run=${r.id}`)}>
                  <td>{r.campaigns?.name}</td>
                  <td><span className="dot" style={{ background: statusColor(r.status) }} />{r.status}</td>
                  <td>{r.stage ?? "—"}</td><td>{r.counters?.found ?? 0}</td><td>{r.counters?.qualified ?? 0}</td>
                  <td>{r.credits_used}</td><td>{r.llm_calls}</td><td>{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
