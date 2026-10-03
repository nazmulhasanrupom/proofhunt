import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import Empty from "../components/Empty";
import { statusColor, type Run } from "./RunsPage";

type Ev = { id: number; level: string; stage: string; message: string; created_at: string };
const STAGES = ["discovery", "audit", "extract", "contacts", "judge", "assets", "sequences"];

export default function ActivityPage() {
  const [params] = useSearchParams();
  const toast = useToast();
  const qc = useQueryClient();
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<Run[]>("/runs") });
  const runId = params.get("run") ?? runs.data?.[0]?.id;
  const run = useQuery({ queryKey: ["run", runId], enabled: !!runId, queryFn: () => api<Run>(`/runs/${runId}`), refetchInterval: 3000 });
  const [events, setEvents] = useState<Ev[]>([]);
  const last = useRef(0);

  useEffect(() => { setEvents([]); last.current = 0; }, [runId]);
  useEffect(() => {
    if (!runId) return;
    const t = setInterval(async () => {
      const more = await api<Ev[]>(`/runs/${runId}/events?after=${last.current}`).catch(() => []);
      if (more.length) { last.current = more[more.length - 1].id; setEvents((e) => [...e, ...more]); }
    }, 3000);
    return () => clearInterval(t);
  }, [runId]);

  const act = async (what: "pause" | "resume" | "cancel") => {
    if (what === "cancel" && !confirm("Cancel this run?")) return;
    try { await api(`/runs/${runId}/${what}`, { method: "POST" }); toast(`Run ${what}`); qc.invalidateQueries({ queryKey: ["run", runId] }); }
    catch (e) { toast((e as Error).message, true); }
  };

  if (!runId) return <div className="page"><div className="page-head">Activity</div><Empty text="No run is active." /></div>;
  const r = run.data;
  const idx = r?.stage ? STAGES.indexOf(r.stage) : -1;
  return (
    <div className="page">
      <div className="page-head">
        <span>Activity {r && <><span className="dot ml-3" style={{ background: statusColor(r.status) }} />{r.status}</>}</span>
        <span className="flex gap-2">
          {r?.status === "running" && <button className="btn" onClick={() => act("pause")}>Pause</button>}
          {(r?.status === "paused" || r?.status === "failed") && <button className="btn" onClick={() => act("resume")}>Resume</button>}
          {r && ["queued", "running", "paused"].includes(r.status) && <button className="btn btn-danger" onClick={() => act("cancel")}>Cancel</button>}
        </span>
      </div>
      <div className="page-body flex flex-col gap-4">
        {r && (
          <>
            <div className="flex gap-1">
              {STAGES.map((s, i) => (
                <div key={s} className="flex-1 text-center text-xs" style={{ padding: "6px 0", borderRadius: 6, background: i <= idx ? "var(--bg-4)" : "var(--bg-3)", color: i === idx ? "#fff" : "var(--text-muted)" }}>{s}</div>
              ))}
            </div>
            <div className="grid grid-cols-5 gap-3">
              {[["Companies", r.counters?.found ?? 0], ["Qualified", r.counters?.qualified ?? 0], ["No contact", r.counters?.no_contact ?? 0], ["Credits used", r.credits_used], ["LLM calls", r.llm_calls]].map(([k, v]) => (
                <div key={k} className="card"><div className="label">{k}</div><div className="text-xl font-semibold">{v}</div></div>
              ))}
            </div>
            {r.error && <div className="card" style={{ borderColor: "var(--warn)" }}>{r.error}</div>}
          </>
        )}
        <div className="card font-mono text-xs" style={{ maxHeight: 420, overflowY: "auto" }}>
          {events.length === 0 && <span style={{ color: "var(--text-faint)" }}>Waiting for log lines…</span>}
          {events.map((e) => (
            <div key={e.id}>
              <span style={{ color: "var(--text-faint)" }}>{new Date(e.created_at).toLocaleTimeString()} </span>
              <span style={{ color: e.level === "error" ? "var(--bad)" : e.level === "warn" ? "var(--warn)" : "var(--text-muted)" }}>[{e.stage}] </span>{e.message}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
