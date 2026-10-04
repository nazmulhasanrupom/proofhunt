import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import Empty from "../components/Empty";
import { statusColor, type Run } from "./RunsPage";
import { companyColor } from "../lib/fmt";

type Ev = { id: number; level: string; stage: string; message: string; created_at: string };
type RunFull = Run & { campaigns?: { name: string; filters?: { maxCreditsPerStage?: number; maxLlmCallsPerStage?: number } } };
type Co = { id: string; domain: string; name: string | null; country: string | null; size_estimate: number | null; status: string; fail_reason: string | null; score: number | null };
const STAGES = ["discovery", "audit", "extract", "contacts", "judge", "assets", "sequences"];
const STAGE_NAME: Record<string, string> = { assets: "reports", sequences: "emails" };

export default function ActivityPage() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const qc = useQueryClient();
  const go = useNavigate();
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<RunFull[]>("/runs"), refetchInterval: 5000 });
  const runId = params.get("run") ?? runs.data?.[0]?.id;
  const run = useQuery({ queryKey: ["run", runId], enabled: !!runId, queryFn: () => api<RunFull>(`/runs/${runId}`), refetchInterval: 3000 });
  const cos = useQuery({ queryKey: ["run-companies", runId], enabled: !!runId, queryFn: () => api<Co[]>(`/runs/${runId}/companies`), refetchInterval: 5000 });
  const [events, setEvents] = useState<Ev[]>([]);
  const last = useRef(0);

  useEffect(() => { setEvents([]); last.current = 0; }, [runId]);
  useEffect(() => {
    if (!runId) return;
    let dead = false;
    const tick = async () => {
      const more = await api<Ev[]>(`/runs/${runId}/events?after=${last.current}`).catch(() => []);
      if (!dead && more.length) { last.current = more[more.length - 1].id; setEvents((e) => [...e, ...more]); }
    };
    tick();  // show the log at once, not after the first 3 seconds
    const t = setInterval(tick, 3000);
    return () => { dead = true; clearInterval(t); };
  }, [runId]);

  const act = async (what: "pause" | "resume" | "cancel") => {
    if (what === "cancel" && !confirm("Cancel this run?")) return;
    try {
      await api(`/runs/${runId}/${what}`, { method: "POST" });
      toast(what === "resume" ? "Continuing" : `Run ${what === "pause" ? "paused" : "cancelled"}`);
      qc.invalidateQueries({ queryKey: ["run", runId] }); qc.invalidateQueries({ queryKey: ["runs"] });
    } catch (e) { toast((e as Error).message, true); }
  };

  const waiting = (cos.data ?? []).filter((c) => ["new", "auditing", "audited", "extracted", "contacted"].includes(c.status));
  const qualifyRest = async () => {
    if (!confirm(`Stop searching and qualify the ${waiting.length} companies this run already found?\n\nIt reads their sites (about 4 Firecrawl credits each if never read), finds contacts, scores the fit and writes emails. This run will be cancelled.`)) return;
    try {
      const out = await api<{ runs: { run_id: string }[]; still_filtered: { domain: string; reason: string }[] }>("/companies/qualify", { body: { ids: waiting.map((c) => c.id) } });
      if (!out.runs.length) { toast(`Nothing started. ${out.still_filtered[0]?.domain ?? "They"} still filtered out: ${out.still_filtered[0]?.reason ?? ""}`, true); return; }
      if (r && ["paused", "failed"].includes(r.status)) await api(`/runs/${runId}/cancel`, { method: "POST" }).catch(() => null);
      toast("Qualifying the companies found so far");
      qc.invalidateQueries({ queryKey: ["runs"] });
      setParams({ run: out.runs[0].run_id });
    } catch (e) { toast((e as Error).message, true); }
  };

  if (runs.isLoading) return <div className="page"><div className="page-head">Activity</div></div>;
  if (!runId) return <div className="page"><div className="page-head">Activity</div><Empty text="No run yet. Start one from Campaigns, or qualify companies on the Companies page." /></div>;
  const r = run.data;
  const idx = r?.stage ? STAGES.indexOf(r.stage) : -1;
  const usage = (r?.counters as unknown as { stage_usage?: Record<string, { credits?: number; llm_calls?: number }>; limits_hit?: { stage: string }[]; manual?: boolean }) ?? {};
  const f = r?.campaigns?.filters;
  const hit = new Set((usage.limits_hit ?? []).map((h) => h.stage));
  return (
    <div className="page">
      <div className="page-head">
        <span className="flex items-center gap-3">
          Activity
          <select className="select" style={{ width: 280 }} value={runId} onChange={(e) => setParams({ run: e.target.value })}>
            {runs.data?.map((x) => (
              <option key={x.id} value={x.id}>{x.campaigns?.name ?? "run"}{x.counters?.manual ? " (manual)" : ""} · {x.status} · {x.started_at ? new Date(x.started_at).toLocaleString() : "queued"}</option>
            ))}
          </select>
          {r && <span><span className="dot" style={{ background: statusColor(r.status) }} />{r.status}</span>}
        </span>
        <span className="flex gap-2">
          {r && ["paused", "failed"].includes(r.status) && !r.counters?.manual && waiting.length > 0 && (
            <button className="btn-primary" title="Stop searching for new companies. Qualify the ones already found." onClick={qualifyRest}>Qualify the {waiting.length} found</button>
          )}
          {r?.status === "running" && <button className="btn" onClick={() => act("pause")}>Pause</button>}
          {r && ["paused", "failed"].includes(r.status) && <button className="btn" onClick={() => act("resume")}>Resume</button>}
          {r?.status === "done" && <button className="btn" title="Pick up companies a stage limit left behind. Every stage gets a fresh limit." onClick={() => act("resume")}>Continue</button>}
          {r && ["queued", "running", "paused"].includes(r.status) && <button className="btn btn-danger" onClick={() => act("cancel")}>Cancel</button>}
        </span>
      </div>
      <div className="page-body flex flex-col gap-4">
        {r && (
          <>
            <div className="flex gap-1">
              {STAGES.map((s, i) => (
                <div key={s} className="flex-1 text-center text-xs" style={{ padding: "6px 0", borderRadius: 6, background: i <= idx ? "var(--bg-4)" : "var(--bg-3)", color: i === idx ? "#fff" : "var(--text-muted)" }}>
                  {STAGE_NAME[s] ?? s}{hit.has(s) ? " · limit" : ""}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-5 gap-3">
              {[["Companies", r.counters?.found ?? 0], ["Qualified", r.counters?.qualified ?? 0], ["No contact", r.counters?.no_contact ?? 0], ["Credits used", r.credits_used], ["AI calls", r.llm_calls]].map(([k, v]) => (
                <div key={k} className="card"><div className="label">{k}</div><div className="text-xl font-semibold">{v}</div></div>
              ))}
            </div>
            {usage.stage_usage && Object.keys(usage.stage_usage).length > 0 && (
              <div className="card" style={{ fontSize: 12 }}>
                <span className="label">Used per stage (each stage has its own limit: {f?.maxCreditsPerStage ?? 500} credits, {f?.maxLlmCallsPerStage ?? 300} AI calls)</span>
                <div className="grid grid-cols-7 gap-2">
                  {STAGES.map((s) => {
                    const u = usage.stage_usage?.[s];
                    return <div key={s} style={{ color: hit.has(s) ? "var(--warn)" : "var(--text-muted)" }}><div>{STAGE_NAME[s] ?? s}</div><div>{u ? `${u.credits ?? 0} cr · ${u.llm_calls ?? 0} AI` : "—"}</div></div>;
                  })}
                </div>
              </div>
            )}
            {r.error && <div className="card" style={{ borderColor: "var(--warn)" }}>{r.error}</div>}
          </>
        )}
        <div>
          <span className="label">Companies in this run ({cos.data?.length ?? 0})</span>
          {cos.data && cos.data.length > 0 ? (
            <div style={{ maxHeight: 320, overflowY: "auto" }}>
              <table className="table">
                <thead><tr><th>Domain</th><th>Name</th><th>Country</th><th>Size</th><th>Score</th><th>Status</th></tr></thead>
                <tbody>
                  {cos.data.map((c) => (
                    <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => go(`/companies?id=${c.id}`)}>
                      <td>{c.domain}</td><td>{c.name ?? "—"}</td><td>{c.country ?? "—"}</td><td>{c.size_estimate ?? "—"}</td><td>{c.score ?? "—"}</td>
                      <td><span className="dot" style={{ background: companyColor(c.status) }} />{c.status}{c.fail_reason ? <span style={{ color: "var(--text-faint)" }}> · {c.fail_reason}</span> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <div style={{ color: "var(--text-faint)", fontSize: 13 }}>No companies yet.</div>}
        </div>
        <div className="card font-mono text-xs" style={{ maxHeight: 320, overflowY: "auto" }}>
          {events.length === 0 && <span style={{ color: "var(--text-faint)" }}>No log lines for this run.</span>}
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
