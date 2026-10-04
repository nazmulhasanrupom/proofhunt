import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, BASE } from "../api/client";
import { useToast } from "../components/Toast";
import Empty from "../components/Empty";
import Skeleton from "../components/Skeleton";
import Drawer, { KV, Tabs } from "../components/Drawer";
import { LEAD_STAGES, dayTime, stageColor } from "../lib/fmt";

type Row = {
  id: string; stage: string; score: number | null; created_at: string; company_id: string;
  companies: { domain: string; name: string | null; country: string | null }; people: { name: string | null; title: string | null; email: string | null } | null;
};
type Detail = Omit<Row, "companies" | "people"> & {
  notes: string | null; timezone: string | null;
  companies: { id: string; domain: string; name: string | null };
  people: { name: string | null; title: string | null; email: string | null; email_kind: string | null; email_source: string | null } | null;
  judgments: { fit_score: number; problem: string; fix: string } | null;
  messages: { id: string; step: number; subject: string; body: string; status: string; scheduled_at: string | null; sent_at: string | null; error: string | null }[];
  assets: { id: string; kind: string; content_md: string; public_token: string | null; demo_url: string | null }[];
};
type Company = { evidence: { id: string; quote: string; url: string; verified: boolean }[] };
const TABS = ["Overview", "Evidence", "Emails", "Report", "Demo", "Notes"];
const label = (s: string) => s.replace(/_/g, " ");

export default function LeadsPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<"board" | "table">("board");
  const [q, setQ] = useState("");
  const [drag, setDrag] = useState<string | null>(null);
  const open = params.get("id");
  const { data, isLoading } = useQuery({ queryKey: ["leads", q], queryFn: () => api<Row[]>(`/leads?q=${encodeURIComponent(q)}`) });
  const move = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: string }) => api(`/leads/${id}`, { method: "PATCH", body: { stage } }),
    onSuccess: (_d, v) => { toast(`Moved to ${label(v.stage)}`); qc.invalidateQueries({ queryKey: ["leads"] }); qc.invalidateQueries({ queryKey: ["counts"] }); },
    onError: (e: Error) => toast(e.message, true),
  });
  const name = (l: Row) => l.companies.name || l.companies.domain;
  return (
    <div className="page">
      <div className="page-head">
        <span>Leads</span>
        <span className="flex gap-2" style={{ width: 380 }}>
          <input className="input" placeholder="Search domain or name" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn" onClick={() => setView(view === "board" ? "table" : "board")}>{view === "board" ? "Table" : "Board"}</button>
        </span>
      </div>
      <div className="page-body">
        {isLoading && <Skeleton />}
        {data?.length === 0 && <Empty text={q ? "No lead matches." : "No leads yet. Qualified companies appear here."} />}
        {!!data?.length && view === "table" && (
          <table className="table">
            <thead><tr><th>Company</th><th>Contact</th><th>Score</th><th>Stage</th><th>Created</th></tr></thead>
            <tbody>
              {data.map((l) => (
                <tr key={l.id} style={{ cursor: "pointer" }} onClick={() => setParams({ id: l.id })}>
                  <td>{name(l)}</td><td>{l.people?.name || "(generic address)"} {l.people?.email ? `· ${l.people.email}` : ""}</td><td>{l.score ?? "—"}</td>
                  <td><span className="dot" style={{ background: stageColor(l.stage) }} />{label(l.stage)}</td><td>{dayTime(l.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!!data?.length && view === "board" && (
          <div className="flex gap-3 overflow-x-auto pb-2">
            {LEAD_STAGES.map((st) => {
              const items = data.filter((l) => l.stage === st);
              return (
                <div key={st} className="w-56 shrink-0 rounded-lg p-2" style={{ background: "var(--bg-1)", minHeight: 160 }}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => { const l = data.find((x) => x.id === drag); if (l && l.stage !== st) move.mutate({ id: l.id, stage: st }); setDrag(null); }}>
                  <div className="mb-2 flex items-center px-1" style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    <span className="dot" style={{ background: stageColor(st) }} />{label(st)}<span className="flex-1" /><span className="badge">{items.length}</span>
                  </div>
                  <div className="flex flex-col gap-2">
                    {items.map((l) => (
                      <div key={l.id} draggable onDragStart={() => setDrag(l.id)} onClick={() => setParams({ id: l.id })} className="card" style={{ padding: 10, cursor: "grab", fontSize: 13 }}>
                        <div className="truncate font-medium">{name(l)}</div>
                        <div className="truncate" style={{ color: "var(--text-faint)", fontSize: 12 }}>{l.people?.name || "No named person"} · score {l.score ?? "—"}</div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      {open && <LeadDrawer id={open} onClose={() => setParams({})} />}
    </div>
  );
}

export function LeadDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState("Overview");
  const { data: l, isLoading } = useQuery({ queryKey: ["lead", id], queryFn: () => api<Detail>(`/leads/${id}`) });
  const cid = l?.companies?.id;
  const { data: co } = useQuery({ queryKey: ["company", cid], enabled: !!cid && tab === "Evidence", queryFn: () => api<Company>(`/companies/${cid}`) });
  const [notes, setNotes] = useState<string | null>(null);
  const [demo, setDemo] = useState<string | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["lead", id] }); qc.invalidateQueries({ queryKey: ["leads"] }); };
  const patch = useMutation({
    mutationFn: (body: { stage?: string; notes?: string }) => api(`/leads/${id}`, { method: "PATCH", body }),
    onSuccess: () => { toast("Saved"); refresh(); }, onError: (e: Error) => toast(e.message, true),
  });
  const saveDemo = useMutation({
    mutationFn: (demo_url: string) => api(`/leads/${id}/demo-url`, { method: "PATCH", body: { demo_url } }),
    onSuccess: () => { toast("Demo link saved"); refresh(); }, onError: (e: Error) => toast(e.message, true),
  });
  const report = l?.assets.find((a) => a.kind === "report");
  const spec = l?.assets.find((a) => a.kind === "demo_spec");
  return (
    <Drawer title={l?.companies.name || l?.companies.domain || "Lead"} sub={l?.companies.domain} onClose={onClose}>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      <div className="flex-1 overflow-y-auto p-4">
        {isLoading && <Skeleton rows={5} />}
        {l && tab === "Overview" && (
          <>
            <div className="mb-3 flex items-center gap-2">
              <span className="label mb-0">Stage</span>
              <select className="select" style={{ width: 180 }} value={l.stage} onChange={(e) => patch.mutate({ stage: e.target.value })}>
                {LEAD_STAGES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
              </select>
            </div>
            <KV k="Score" v={l.score} />
            <KV k="Contact" v={l.people ? `${l.people.name || "No named person"} · ${l.people.title || "—"}` : "—"} />
            <KV k="Email" v={l.people?.email ? `${l.people.email} (${l.people.email_kind})` : "—"} />
            <KV k="Time zone" v={l.timezone} />
            {l.judgments && <><div className="label mt-3">Problem</div>{l.judgments.problem}<div className="label mt-3">Fix</div>{l.judgments.fix}</>}
          </>
        )}
        {l && tab === "Evidence" && (
          <div className="flex flex-col gap-2">
            {!co && <Skeleton rows={3} />}
            {co?.evidence.map((e) => (
              <div key={e.id} className="card" style={{ fontSize: 13, padding: 12 }}>“{e.quote}”
                <div><a href={e.url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "var(--text-faint)", textDecoration: "underline" }}>{e.url}</a></div></div>
            ))}
            {co && !co.evidence.length && <Empty text="No evidence saved." />}
          </div>
        )}
        {l && tab === "Emails" && (
          <div className="flex flex-col gap-2">
            {!l.messages.length && <Empty text="No emails yet." />}
            {l.messages.map((m) => (
              <div key={m.id} className="card" style={{ padding: 12 }}>
                <div className="flex items-center gap-2" style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  <span>{m.step === 0 ? "Main email" : `Follow-up ${m.step}`}</span><span className="chip">{m.status}</span>
                  <span className="flex-1" /><span>{m.sent_at ? `sent ${dayTime(m.sent_at)}` : m.scheduled_at ? `due ${dayTime(m.scheduled_at)}` : ""}</span>
                </div>
                <div className="mt-1 font-medium">{m.subject}</div>
                <pre className="mt-1" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 13, color: "var(--text-muted)" }}>{m.body}</pre>
                {m.error && <div style={{ color: "var(--warn)", fontSize: 12 }}>{m.error}</div>}
              </div>
            ))}
          </div>
        )}
        {l && tab === "Report" && (
          !report ? <Empty text="No report for this lead." /> : (
            <>
              {report.public_token && <a className="btn mb-3 inline-block" href={`${BASE}/r/${report.public_token}`} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}>Open public page</a>}
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 13 }}>{report.content_md}</pre>
            </>
          )
        )}
        {l && tab === "Demo" && (
          !spec ? <Empty text="No demo spec for this lead." /> : (
            <>
              <span className="label">Demo link</span>
              <div className="mb-3 flex gap-2">
                <input className="input" placeholder="https://…" value={demo ?? spec.demo_url ?? ""} onChange={(e) => setDemo(e.target.value)} />
                <button className="btn" onClick={() => demo != null && saveDemo.mutate(demo)}>Save</button>
              </div>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 13 }}>{spec.content_md}</pre>
            </>
          )
        )}
        {l && tab === "Notes" && (
          <>
            <textarea className="textarea" style={{ minHeight: 200 }} value={notes ?? l.notes ?? ""} onChange={(e) => setNotes(e.target.value)} />
            <button className="btn-primary mt-2" onClick={() => notes != null && patch.mutate({ notes })}>Save notes</button>
          </>
        )}
      </div>
    </Drawer>
  );
}
