import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Pencil } from "lucide-react";
import { api } from "../api/client";
import { useProfiles } from "../lib/profile";
import { useToast } from "../components/Toast";
import Empty from "../components/Empty";
import NewProfileDialog from "../components/NewProfileDialog";
import Skeleton from "../components/Skeleton";

type Detail = {
  id: string; name: string; file_name: string | null; created_at: string;
  parsed: { name: string; headline: string; skills: string[]; tools: string[]; proof_points: string[] } | null;
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

  // "/profile?new=1" (from the top bar, or a page that needs a profile) opens the dialog. The flag is used up at once: when the page
  // is rebuilt for a newly picked profile it must not open the dialog again.
  useEffect(() => {
    if (!params.has("new")) return;
    setCreating(true);
    setParams({}, { replace: true });
  }, [params, setParams]);
  const replace = useMutation({
    mutationFn: (f: File) => { const form = new FormData(); form.append("file", f); return api(`/profiles/${data!.id}/cv`, { method: "PUT", form }); },
    onSuccess: () => { toast("CV replaced. Press Generate offer map to use it"); refresh(); },
    onError: (e: Error) => toast(e.message, true),
  });
  const rename = useMutation({
    mutationFn: (name: string) => api(`/profiles/${data!.id}`, { method: "PATCH", body: { name } }),
    onSuccess: () => { toast("Renamed"); setNewName(null); refresh(); },
    onError: (e: Error) => toast(e.message, true),
  });
  const gen = useMutation({
    mutationFn: (id: string) => api(`/profiles/${id}/offer-map`, { method: "POST" }),
    onSuccess: () => { toast("Offer map created"); qc.invalidateQueries({ queryKey: ["offer-map"] }); nav("/offer-map"); },
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
        {!current && <Empty text="No profile yet. A profile is one CV. Every section shows the data of the profile you pick." action="Create profile" onAction={() => setCreating(true)} />}
        {current && isLoading && <Skeleton />}
        {data && (
          <>
            <div className="card flex flex-col gap-3">
              <div className="flex items-center gap-2">
                {newName === null ? (
                  <>
                    <div className="text-base font-semibold">{data.name}</div>
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
                {data.file_name ?? "CV"} · added {new Date(data.created_at).toLocaleDateString()} · {summary(data.counts, " · ")}
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary" disabled={gen.isPending} onClick={() => gen.mutate(data.id)}>{gen.isPending ? "Working…" : "Generate offer map"}</button>
                <button className="btn" disabled={replace.isPending} onClick={() => input.current?.click()}>{replace.isPending ? "Reading your CV…" : "Replace CV"}</button>
                <input ref={input} type="file" hidden accept=".pdf,.docx,.txt,.md" onChange={(e) => { const f = e.target.files?.[0]; if (f) replace.mutate(f); e.target.value = ""; }} />
                <button className="btn btn-danger" disabled={del.isPending} onClick={() => confirmDelete(data)}>Delete profile</button>
              </div>
            </div>
            {p && (
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
