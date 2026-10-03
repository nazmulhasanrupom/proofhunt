import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import ChipInput from "../components/ChipInput";
import Empty from "../components/Empty";
import Skeleton from "../components/Skeleton";

type Filters = {
  leadsWanted: number; maxCompaniesToScan: number; maxCreditsPerRun: number; maxPerCompany: number;
  company: { countries: string[]; employeeRanges: number[][]; allowUnknownSize: boolean; webKeywords: string[]; minKeywordHits: number; excludeDomains: string[]; cooldownDays: number };
  person: { titlePriority: string[]; excludeTitle: string[]; seniority: string[]; excludeSeniority: string[]; matchMode: string };
  qualify: { minFitScore: number; maybeFrom: number; demoFrom: number };
  email: { allowGeneric: boolean; requireMx: boolean };
};
type Campaign = { id: string; name: string; status: string; filters: Filters; created_at: string };

const DEFAULTS: Filters = {
  leadsWanted: 100, maxCompaniesToScan: 500, maxCreditsPerRun: 2500, maxPerCompany: 1,
  company: { countries: ["United States", "United Kingdom", "Canada", "Australia"], employeeRanges: [[1, 10], [11, 50]], allowUnknownSize: true,
    webKeywords: ["seo agency", "content marketing", "link building", "digital marketing agency", "white label seo"], minKeywordHits: 1, excludeDomains: [], cooldownDays: 180 },
  person: { titlePriority: ["founder", "co-founder", "ceo", "coo", "head of operations"], excludeTitle: ["intern", "assistant", "junior", "coordinator"],
    seniority: ["owner", "c_suite"], excludeSeniority: ["intern", "entry"], matchMode: "title_or_seniority" },
  qualify: { minFitScore: 70, maybeFrom: 50, demoFrom: 85 },
  email: { allowGeneric: true, requireMx: true },
};

const rangesText = (r: number[][]) => r.map(([a, b]) => `${a}-${b}`).join(", ");
const parseRanges = (t: string) => t.split(",").map((x) => x.trim().split("-").map(Number)).filter((p) => p.length === 2 && p.every((n) => !isNaN(n)));

function Num({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return <div><span className="label">{label}</span><input className="input" type="number" value={value} onChange={(e) => onChange(Number(e.target.value))} /></div>;
}

export default function CampaignsPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["campaigns"], queryFn: () => api<Campaign[]>("/campaigns") });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [f, setF] = useState<Filters>(DEFAULTS);
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setF({ ...f, [k]: v });
  const queries = Math.max(1, Math.floor(f.maxCompaniesToScan / 5));
  const cost = f.maxCompaniesToScan * 4 + queries * 4;

  const create = useMutation({
    mutationFn: () => api("/campaigns", { body: { name, filters: f } }),
    onSuccess: () => { toast("Campaign created"); setOpen(false); setName(""); qc.invalidateQueries({ queryKey: ["campaigns"] }); },
    onError: (e: Error) => toast(e.message, true),
  });
  const start = useMutation({
    mutationFn: (id: string) => api<{ id: string }>(`/campaigns/${id}/runs`, { method: "POST" }),
    onSuccess: (r) => { toast("Run started"); nav(`/activity?run=${r.id}`); },
    onError: (e: Error) => toast(e.message, true),
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`/campaigns/${id}`, { method: "DELETE" }),
    onSuccess: () => { toast("Campaign deleted"); qc.invalidateQueries({ queryKey: ["campaigns"] }); },
  });

  return (
    <div className="page">
      <div className="page-head"><span>Campaigns</span><button className="btn-primary" onClick={() => setOpen(!open)}>{open ? "Close" : "New campaign"}</button></div>
      <div className="page-body flex flex-col gap-4">
        {open && (
          <div className="card flex flex-col gap-4">
            <div><span className="label">Name</span><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="SEO agencies — US/UK" /></div>
            <div className="grid grid-cols-4 gap-3">
              <Num label="Leads wanted" value={f.leadsWanted} onChange={(n) => set("leadsWanted", n)} />
              <Num label="Max companies to scan" value={f.maxCompaniesToScan} onChange={(n) => set("maxCompaniesToScan", n)} />
              <Num label="Max credits per run" value={f.maxCreditsPerRun} onChange={(n) => set("maxCreditsPerRun", n)} />
              <Num label="Cooldown days" value={f.company.cooldownDays} onChange={(n) => set("company", { ...f.company, cooldownDays: n })} />
            </div>
            <div><span className="label">Countries</span><ChipInput value={f.company.countries} onChange={(v) => set("company", { ...f.company, countries: v })} /></div>
            <div><span className="label">Web keywords</span><ChipInput value={f.company.webKeywords} onChange={(v) => set("company", { ...f.company, webKeywords: v })} /></div>
            <div className="grid grid-cols-3 gap-3">
              <div><span className="label">Employee ranges (e.g. 1-10, 11-50)</span>
                <input className="input" defaultValue={rangesText(f.company.employeeRanges)} onBlur={(e) => set("company", { ...f.company, employeeRanges: parseRanges(e.target.value) })} /></div>
              <Num label="Min keyword hits" value={f.company.minKeywordHits} onChange={(n) => set("company", { ...f.company, minKeywordHits: n })} />
              <label className="flex items-end gap-2 pb-2"><input type="checkbox" checked={f.company.allowUnknownSize} onChange={(e) => set("company", { ...f.company, allowUnknownSize: e.target.checked })} /> Allow unknown size</label>
            </div>
            <div><span className="label">Exclude domains</span><ChipInput value={f.company.excludeDomains} onChange={(v) => set("company", { ...f.company, excludeDomains: v })} /></div>
            <div><span className="label">Title priority (first wins)</span><ChipInput value={f.person.titlePriority} onChange={(v) => set("person", { ...f.person, titlePriority: v })} /></div>
            <div><span className="label">Exclude titles</span><ChipInput value={f.person.excludeTitle} onChange={(v) => set("person", { ...f.person, excludeTitle: v })} /></div>
            <div className="grid grid-cols-5 gap-3">
              <Num label="Min fit score" value={f.qualify.minFitScore} onChange={(n) => set("qualify", { ...f.qualify, minFitScore: n })} />
              <Num label="Maybe from" value={f.qualify.maybeFrom} onChange={(n) => set("qualify", { ...f.qualify, maybeFrom: n })} />
              <Num label="Demo from" value={f.qualify.demoFrom} onChange={(n) => set("qualify", { ...f.qualify, demoFrom: n })} />
              <label className="flex items-end gap-2 pb-2"><input type="checkbox" checked={f.email.allowGeneric} onChange={(e) => set("email", { ...f.email, allowGeneric: e.target.checked })} /> Allow generic email</label>
              <label className="flex items-end gap-2 pb-2"><input type="checkbox" checked={f.email.requireMx} onChange={(e) => set("email", { ...f.email, requireMx: e.target.checked })} /> Require MX</label>
            </div>
            <div className="flex items-center justify-between">
              <span style={{ color: "var(--text-muted)" }}>Estimated cost: about {cost.toLocaleString()} Firecrawl credits ({f.maxCompaniesToScan} × 4 + {queries} queries × 4)</span>
              <button className="btn-primary" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>Create campaign</button>
            </div>
          </div>
        )}
        {isLoading && <Skeleton />}
        {!isLoading && data?.length === 0 && !open && <Empty text="No campaigns yet." action="New campaign" onAction={() => setOpen(true)} />}
        {data && data.length > 0 && (
          <table className="table">
            <thead><tr><th>Name</th><th>Companies to scan</th><th>Leads wanted</th><th>Created</th><th /></tr></thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td><td>{c.filters.maxCompaniesToScan}</td><td>{c.filters.leadsWanted}</td><td>{new Date(c.created_at).toLocaleDateString()}</td>
                  <td className="text-right">
                    <button className="btn" disabled={start.isPending} onClick={() => start.mutate(c.id)}>Start run</button>{" "}
                    <button className="btn btn-danger" onClick={() => { if (confirm(`Delete "${c.name}"?`)) del.mutate(c.id); }}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
