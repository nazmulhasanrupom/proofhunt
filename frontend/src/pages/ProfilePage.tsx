import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Pencil } from "lucide-react";
import { api } from "../api/client";
import { KIND_LABEL, useProfiles, type ProfileKind } from "../lib/profile";
import { useToast } from "../components/Toast";
import Empty from "../components/Empty";
import NewProfileDialog from "../components/NewProfileDialog";
import Skeleton from "../components/Skeleton";

type Creator = { name: string; channel_url: string; niche: string; avg_views: string; subscribers: string; audience_countries: string[]; content_style: string; past_sponsors: string[]; open_to_deals: boolean | null };
type Detail = {
  id: string; name: string; kind: ProfileKind; file_name: string | null; created_at: string;
  parsed: { name: string; headline: string; skills: string[]; tools: string[]; proof_points: string[];
    agency?: { name: string; sender_name: string; website: string; commission_model: string }; niches?: string[]; roster?: Creator[] } | null;
  counts: { campaigns: number; companies: number; leads: number; emails_sent: number };
};

const num = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const summary = (c: Detail["counts"], sep = ", ") =>
  [num(c.campaigns, "campaign", "campaigns"), num(c.companies, "company", "companies"), num(c.leads, "lead", "leads"), `${num(c.emails_sent, "email", "emails")} sent`].join(sep);

export default function ProfilePage() {
  const toast = useToast();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const { current } = useProfiles();
  const input = useRef<HTMLInputElement>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState<string | null>(null);  // not null while renaming

  const { data, isLoading } = useQuery({
    queryKey: ["profile", current?.id], enabled: !!current,
    queryFn: () => api<Detail>(`/profiles/${current!.id}`),
  });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["profile"] }); qc.invalidateQueries({ queryKey: ["profiles"] }); };
  const isIma = data?.kind === "ima";
  const doc = isIma ? "Agency brief" : "CV";                       // what the uploaded file is
  const genLabel = isIma ? "Generate brand map" : "Generate offer map";

  // "/profile?new=1" (from the top bar, or a page that needs a profile) opens the dialog. The flag is used up at once: when the page
  // is rebuilt for a newly picked profile it must not open the dialog again.
  useEffect(() => {
    if (!params.has("new")) return;
    setCreating(true);
    setParams({}, { replace: true });
  }, [params, setParams]);
  const replace = useMutation({
    mutationFn: (f: File) => { const form = new FormData(); form.append("file", f); return api(`/profiles/${data!.id}/cv`, { method: "PUT", form }); },
    onSuccess: () => { toast(`${doc} replaced. Press ${genLabel} to use it`); refresh(); },
    onError: (e: Error) => toast(e.message, true),
  });
  const rename = useMutation({
    mutationFn: (name: string) => api(`/profiles/${data!.id}`, { method: "PATCH", body: { name } }),
    onSuccess: () => { toast("Renamed"); setNewName(null); refresh(); },
    onError: (e: Error) => toast(e.message, true),
  });
  const gen = useMutation({
    mutationFn: (id: string) => api(`/profiles/${id}/offer-map`, { method: "POST" }),
    onSuccess: () => { toast(isIma ? "Brand map created" : "Offer map created"); qc.invalidateQueries({ queryKey: ["offer-map"] }); nav("/offer-map"); },
    onError: (e: Error) => toast(e.message, true),
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`/profiles/${id}`, { method: "DELETE" }),
    // the list shrinks, and the app moves to the first profile that is left
    onSuccess: async () => { toast("Profile deleted"); await qc.invalidateQueries({ queryKey: ["profiles"] }); },
    onError: (e: Error) => toast(e.message, true),
  });
  const confirmDelete = (d: Detail) => {
    if (confirm(`Delete "${d.name}" and everything in it?\n\n${summary(d.counts)}.\n\nThis cannot be undone.`)) del.mutate(d.id);
  };

  const p = data?.parsed;
  return (
    <div className="page">
      <div className="page-head">
        <span>Profile & CV</span>
        <button className="btn-primary" onClick={() => setCreating(true)}>New profile</button>
      </div>
      <div className="page-body flex flex-col gap-4">
        {!current && <Empty text="No profile yet. A profile is one CV or one agency brief. Every section shows the data of the profile you pick." action="Create profile" onAction={() => setCreating(true)} />}
        {current && isLoading && <Skeleton />}
        {data && (
          <>
            <div className="card flex flex-col gap-3">
              <div className="flex items-center gap-2">
                {newName === null ? (
                  <>
                    <div className="text-base font-semibold">{data.name}</div>
                    <span className="chip">{KIND_LABEL[data.kind]}</span>
                    <button aria-label="Rename profile" title="Rename" onClick={() => setNewName(data.name)}><Pencil size={14} /></button>
                  </>
                ) : (
                  <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (newName.trim()) rename.mutate(newName); }}>
                    <input className="input" style={{ width: 260 }} autoFocus maxLength={60} value={newName} onChange={(e) => setNewName(e.target.value)} />
                    <button className="btn-primary" type="submit" disabled={rename.isPending || !newName.trim()}>Save</button>
                    <button className="btn" type="button" onClick={() => setNewName(null)}>Cancel</button>
                  </form>
                )}
              </div>
              <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                {data.file_name ?? doc} · added {new Date(data.created_at).toLocaleDateString()} · {summary(data.counts, " · ")}
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary" disabled={gen.isPending} onClick={() => gen.mutate(data.id)}>{gen.isPending ? "Working…" : genLabel}</button>
                <button className="btn" disabled={replace.isPending} onClick={() => input.current?.click()}>{replace.isPending ? `Reading your ${doc.toLowerCase()}…` : `Replace ${doc.toLowerCase()}`}</button>
                <input ref={input} type="file" hidden accept=".pdf,.docx,.txt,.md" onChange={(e) => { const f = e.target.files?.[0]; if (f) replace.mutate(f); e.target.value = ""; }} />
                <button className="btn btn-danger" disabled={del.isPending} onClick={() => confirmDelete(data)}>Delete profile</button>
              </div>
            </div>
            {p && isIma && (
              <div className="card flex flex-col gap-4">
                <div>
                  <div className="font-semibold">{p.agency?.name || p.name}</div>
                  <div style={{ color: "var(--text-muted)" }}>{p.headline}</div>
                  <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                    {[p.agency?.sender_name && `Sender: ${p.agency.sender_name}`, p.agency?.website, p.agency?.commission_model].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <div><span className="label">Niches</span><div className="flex flex-wrap gap-1.5">{(p.niches ?? []).map((s) => <span key={s} className="chip">{s}</span>)}</div></div>
                <div>
                  <span className="label">Roster ({p.roster?.length ?? 0})</span>
                  <div className="flex flex-col gap-2">
                    {(p.roster ?? []).map((c, i) => (
                      <div key={`${c.name}-${i}`} className="rounded-md border p-2" style={{ borderColor: "var(--border)", fontSize: 13 }}>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold">{c.name || c.channel_url}</span>
                          {c.niche && <span className="chip">{c.niche}</span>}
                          {c.open_to_deals !== null && <span style={{ color: c.open_to_deals ? "var(--ok)" : "var(--text-faint)" }}>{c.open_to_deals ? "open to deals" : "not open to deals"}</span>}
                        </div>
                        <div style={{ color: "var(--text-muted)" }}>
                          {[c.avg_views && `${c.avg_views} avg views`, c.subscribers && `${c.subscribers} subscribers`, c.audience_countries.length > 0 && c.audience_countries.join(", "), c.content_style].filter(Boolean).join(" · ")}
                        </div>
                        {c.past_sponsors.length > 0 && <div style={{ color: "var(--text-muted)" }}>Past sponsors: {c.past_sponsors.join(", ")}</div>}
                      </div>
                    ))}
                    {(p.roster ?? []).length === 0 && <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No creators were found in the brief. Replace the brief with one that has a roster.</div>}
                  </div>
                </div>
                <div style={{ color: "var(--text-faint)", fontSize: 12 }}>Only what the brief says is shown. A number the brief does not give stays empty. Press {genLabel}, then edit the niches and signals on the Offer map page.</div>
              </div>
            )}
            {p && !isIma && (
              <div className="card flex flex-col gap-4">
                <div><div className="font-semibold">{p.name}</div><div style={{ color: "var(--text-muted)" }}>{p.headline}</div></div>
                <div><span className="label">Skills</span><div className="flex flex-wrap gap-1.5">{p.skills.map((s) => <span key={s} className="chip">{s}</span>)}</div></div>
                <div><span className="label">Tools</span><div className="flex flex-wrap gap-1.5">{p.tools.map((s) => <span key={s} className="chip">{s}</span>)}</div></div>
                <div><span className="label">Proof points</span><ul className="list-disc pl-5">{p.proof_points.map((s) => <li key={s}>{s}</li>)}</ul></div>
              </div>
            )}
          </>
        )}
      </div>
      {creating && <NewProfileDialog onClose={() => setCreating(false)} />}
    </div>
  );
}
