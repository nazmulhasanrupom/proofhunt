import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fetchFile, saveFile } from "../api/client";
import { useToast } from "../components/Toast";
import Empty from "../components/Empty";
import Skeleton from "../components/Skeleton";

type Brand = {
  id: string; website_url: string | null; brand: string | null; brand_url: string | null; category: string | null; sponsorships: string | null;
  creators: string | null; emails: string | null; employees: string | null; type: "good to go" | "do manually";
  country: string | null; contact_name: string | null; contact_title: string | null; email_source: string | null; proof_count: number;
};
type Page = { rows: Brand[]; counts: { good: number; manual: number } };

const host = (u: string | null) => { try { return new URL(u ?? "").hostname.replace(/^www\./, ""); } catch { return u ?? ""; } };

/** The lead sheet of an IMA profile: one row per brand that was found. A brand with an email is "good to go". One without is kept as "do manually". */
export default function BrandLeadsPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [edit, setEdit] = useState<{ id: string; text: string } | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["brand-leads", type, q, page],
    queryFn: () => api<Page>(`/brand-leads?page=${page}&type=${encodeURIComponent(type)}&q=${encodeURIComponent(q)}`),
  });
  const save = useMutation({
    mutationFn: (v: { id: string; emails: string }) => api(`/brand-leads/${v.id}`, { method: "PATCH", body: { emails: v.emails } }),
    onSuccess: () => { toast("Saved"); setEdit(null); qc.invalidateQueries({ queryKey: ["brand-leads"] }); },
    onError: (e: Error) => toast(e.message, true),
  });
  const download = useMutation({
    mutationFn: async () => saveFile(await fetchFile("/brand-leads/export", { type: type || null, q: q || null })),
    onSuccess: () => toast("CSV ready"),
    onError: (e: Error) => toast(e.message, true),
  });
  const rows = data?.rows ?? [];
  const total = (data?.counts.good ?? 0) + (data?.counts.manual ?? 0);
  return (
    <div className="page">
      <div className="page-head">
        <span>Leads{data ? ` · ${data.counts.good} good to go · ${data.counts.manual} do manually` : ""}</span>
        <span className="flex gap-2" style={{ width: 560 }}>
          <input className="input" placeholder="Search brand, category or email" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} />
          <select className="select" style={{ width: 150 }} value={type} onChange={(e) => { setType(e.target.value); setPage(0); }} aria-label="Type">
            <option value="">All</option><option value="good to go">good to go</option><option value="do manually">do manually</option>
          </select>
          <button className="btn" disabled={download.isPending || total === 0} onClick={() => download.mutate()}>Download CSV</button>
        </span>
      </div>
      <div className="page-body flex flex-col gap-3">
        {isLoading && <Skeleton />}
        {!isLoading && rows.length === 0 && <Empty text={total === 0 ? "No brands yet. Start a campaign: every brand that gets through becomes a lead here." : "No brand matches."} />}
        {rows.length > 0 && (
          <table className="table">
            <thead><tr><th>Brand</th><th>Category</th><th>Sponsorships</th><th>Creators</th><th>Emails</th><th>Employees</th><th>Type</th></tr></thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.id} style={{ verticalAlign: "top" }}>
                  <td>
                    <div className="font-semibold">{b.brand || host(b.brand_url)}</div>
                    <a href={b.brand_url ?? "#"} target="_blank" rel="noreferrer" style={{ color: "var(--text-muted)", textDecoration: "underline" }}>{host(b.brand_url)}</a>
                    {b.website_url && b.website_url !== b.brand_url && <div><a href={b.website_url} target="_blank" rel="noreferrer" style={{ color: "var(--text-faint)", fontSize: 12, textDecoration: "underline" }}>found on {host(b.website_url)}</a></div>}
                    {b.country && <div style={{ color: "var(--text-faint)", fontSize: 12 }}>{b.country}</div>}
                  </td>
                  <td style={{ maxWidth: 200 }}>{b.category}</td>
                  <td style={{ maxWidth: 320, whiteSpace: "normal" }} title={b.sponsorships ?? ""}>
                    {b.proof_count > 0 ? <><span className="chip">{b.proof_count} proof</span><div style={{ color: "var(--text-muted)", fontSize: 12 }}>{(b.sponsorships ?? "").split(" | ")[0].slice(0, 140)}</div></> : <span style={{ color: "var(--text-faint)" }}>none found</span>}
                  </td>
                  <td style={{ maxWidth: 200, whiteSpace: "normal" }}>{b.creators}</td>
                  <td style={{ whiteSpace: "normal" }}>
                    {edit?.id === b.id ? (
                      <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); save.mutate({ id: b.id, emails: edit.text }); }}>
                        <input className="input" autoFocus placeholder="name@brand.com" value={edit.text} onChange={(e) => setEdit({ id: b.id, text: e.target.value })} />
                        <button className="btn-primary" type="submit" disabled={save.isPending}>Save</button>
                        <button className="btn" type="button" onClick={() => setEdit(null)}>Cancel</button>
                      </form>
                    ) : (
                      <>
                        {b.contact_name && <div style={{ fontSize: 12 }}>{b.contact_name}{b.contact_title ? `, ${b.contact_title}` : ""}</div>}
                        {(b.emails ?? "").split("; ").filter(Boolean).map((m) => <div key={m}>{m}</div>)}
                        <button style={{ color: "var(--text-faint)", fontSize: 12, textDecoration: "underline" }} onClick={() => setEdit({ id: b.id, text: b.emails ?? "" })}>{b.emails ? "edit" : "add email"}</button>
                      </>
                    )}
                  </td>
                  <td>{b.employees}</td>
                  <td><span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-full" style={{ background: b.type === "good to go" ? "var(--ok)" : "var(--warn)" }} />{b.type}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {(page > 0 || rows.length === 50) && (
          <div className="flex gap-2">
            <button className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <button className="btn" disabled={rows.length < 50} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        )}
      </div>
    </div>
  );
}
