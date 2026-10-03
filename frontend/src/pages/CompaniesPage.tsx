import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import Empty from "../components/Empty";
import Skeleton from "../components/Skeleton";
import Drawer, { KV, Tabs } from "../components/Drawer";
import { companyColor, dayTime } from "../lib/fmt";

type Row = {
  id: string; domain: string; name: string | null; country: string | null; size_estimate: number | null; size_bucket: string | null;
  keyword_hits: string[] | null; status: string; fail_reason: string | null; score: number | null;
};
type Detail = Row & {
  tech: Record<string, boolean>; facts: Record<string, unknown>; last_audited_at: string | null;
  pages: { id: string; url: string; kind: string; fetched_at: string }[];
  evidence: { id: string; kind: string; quote: string; url: string; verified: boolean }[];
  people: { id: string; name: string | null; title: string | null; email: string | null; email_kind: string | null; email_source: string | null; source_url: string | null; selected: boolean }[];
  judgments: { id: string; fit_score: number; problem: string; fix: string; value_estimate: string; confidence: string; disqualifiers: unknown; created_at: string }[];
};
const STATUSES = ["new", "auditing", "audited", "extracted", "failed", "filtered_out", "no_contact", "judged", "qualified", "maybe", "rejected", "contacted"];
const TABS = ["Facts", "Evidence", "People", "Judgment", "Pages"];

export default function CompaniesPage() {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const open = params.get("id");
  const { data, isLoading } = useQuery({
    queryKey: ["companies", status, q, page],
    queryFn: () => api<Row[]>(`/companies?page=${page}&status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}`),
  });
  return (
    <div className="page">
      <div className="page-head">
        <span>Companies</span>
        <span className="flex gap-2" style={{ width: 380 }}>
          <input className="input" placeholder="Search domain or name" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} />
          <select className="select" style={{ width: 150 }} value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </span>
      </div>
      <div className="page-body">
        {isLoading && <Skeleton />}
        {data?.length === 0 && <Empty text={q || status ? "No company matches." : "No companies yet. Start a run from Campaigns."} />}
        {!!data?.length && (
          <>
            <table className="table">
              <thead><tr><th>Domain</th><th>Name</th><th>Country</th><th>Size</th><th>Keyword hits</th><th>Score</th><th>Status</th></tr></thead>
              <tbody>
                {data.map((c) => (
                  <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => setParams({ id: c.id })}>
                    <td>{c.domain}</td><td>{c.name ?? "—"}</td><td>{c.country ?? "—"}</td>
                    <td>{c.size_estimate ?? c.size_bucket ?? "—"}</td><td>{c.keyword_hits?.length ?? 0}</td><td>{c.score ?? "—"}</td>
                    <td><span className="dot" style={{ background: companyColor(c.status) }} />{c.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex items-center gap-2">
              <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
              <button className="btn" disabled={data.length < 50} onClick={() => setPage(page + 1)}>Next</button>
              <span style={{ color: "var(--text-faint)", fontSize: 12 }}>Page {page + 1}</span>
            </div>
          </>
        )}
      </div>
      {open && <CompanyDrawer id={open} onClose={() => setParams({})} />}
    </div>
  );
}

export function CompanyDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState("Facts");
  const { data: c, isLoading } = useQuery({ queryKey: ["company", id], queryFn: () => api<Detail>(`/companies/${id}`) });
  const rejudge = useMutation({
    mutationFn: () => api<{ status: string }>(`/companies/${id}/rejudge`, { method: "POST" }),
    onSuccess: (r) => { toast(`Judged again: ${r.status}`); qc.invalidateQueries({ queryKey: ["company", id] }); qc.invalidateQueries({ queryKey: ["companies"] }); },
    onError: (e: Error) => toast(e.message, true),
  });
  return (
    <Drawer title={c?.name || c?.domain || "Company"} sub={c?.domain} onClose={onClose}>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      <div className="flex-1 overflow-y-auto p-4">
        {isLoading && <Skeleton rows={5} />}
        {c && tab === "Facts" && (
          <>
            <KV k="Status" v={<><span className="dot" style={{ background: companyColor(c.status) }} />{c.status}{c.fail_reason ? ` — ${c.fail_reason}` : ""}</>} />
            <KV k="Country" v={c.country} /><KV k="Size" v={c.size_estimate ?? c.size_bucket} />
            <KV k="Last audit" v={dayTime(c.last_audited_at)} />
            {Object.entries(c.facts ?? {}).map(([k, v]) => <KV key={k} k={k.replace(/_/g, " ")} v={typeof v === "string" ? v : JSON.stringify(v)} />)}
            <div className="label mt-3">Tech found</div>
            <div className="flex flex-wrap gap-1">{Object.keys(c.tech ?? {}).map((t) => <span key={t} className="chip">{t}</span>)}{!Object.keys(c.tech ?? {}).length && "—"}</div>
            <div className="label mt-3">Keyword hits</div>
            <div className="flex flex-wrap gap-1">{c.keyword_hits?.map((t) => <span key={t} className="chip">{t}</span>)}{!c.keyword_hits?.length && "—"}</div>
          </>
        )}
        {c && tab === "Evidence" && (
          <div className="flex flex-col gap-2">
            {!c.evidence.length && <Empty text="No evidence saved." />}
            {c.evidence.map((e) => (
              <div key={e.id} className="card" style={{ fontSize: 13, padding: 12 }}>
                “{e.quote}”
                <div className="mt-1 flex items-center gap-2" style={{ fontSize: 12, color: "var(--text-faint)" }}>
                  <span className="dot" style={{ background: e.verified ? "var(--ok)" : "var(--warn)", marginRight: 0 }} />{e.verified ? "verified" : "not verified"} · {e.kind}
                  <a href={e.url} target="_blank" rel="noreferrer" className="truncate" style={{ textDecoration: "underline" }}>{e.url}</a>
                </div>
              </div>
            ))}
          </div>
        )}
        {c && tab === "People" && (
          <div className="flex flex-col gap-2">
            {!c.people.length && <Empty text="No people found on the site." />}
            {c.people.map((p) => (
              <div key={p.id} className="card" style={{ padding: 12 }}>
                <div className="font-medium">{p.name ?? "—"} {p.selected && <span className="chip ml-1">picked</span>}</div>
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>{p.title ?? "—"}</div>
                <div style={{ fontSize: 13 }}>{p.email ? `${p.email} (${p.email_kind})` : "No published email"}</div>
                {(p.email_source || p.source_url) && <a href={p.email_source || p.source_url!} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "var(--text-faint)", textDecoration: "underline" }}>source</a>}
              </div>
            ))}
          </div>
        )}
        {c && tab === "Judgment" && (
          <div className="flex flex-col gap-3">
            <button className="btn self-start" disabled={rejudge.isPending} onClick={() => rejudge.mutate()}>{rejudge.isPending ? "Judging… (slow)" : "Judge again"}</button>
            {!c.judgments.length && <Empty text="Not judged yet." />}
            {c.judgments.slice(0, 1).map((j) => (
              <div key={j.id} className="card">
                <div className="text-xl font-semibold">{j.fit_score}</div>
                <KV k="Confidence" v={j.confidence} /><KV k="Value" v={j.value_estimate} />
                <div className="label mt-2">Problem</div>{j.problem}
                <div className="label mt-2">Fix</div>{j.fix}
                {Array.isArray(j.disqualifiers) && j.disqualifiers.length > 0 && <><div className="label mt-2">Disqualifiers</div>{JSON.stringify(j.disqualifiers)}</>}
              </div>
            ))}
            {c.judgments.length > 1 && <div style={{ color: "var(--text-faint)", fontSize: 12 }}>{c.judgments.length - 1} older judgment(s). Scores: {c.judgments.slice(1).map((j) => j.fit_score).join(", ")}</div>}
          </div>
        )}
        {c && tab === "Pages" && (
          <table className="table">
            <tbody>{c.pages.map((p) => <tr key={p.id}><td className="w-20">{p.kind}</td><td><a href={p.url} target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>{p.url}</a></td></tr>)}</tbody>
          </table>
        )}
      </div>
    </Drawer>
  );
}
