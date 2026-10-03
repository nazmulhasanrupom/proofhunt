import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import Skeleton from "../components/Skeleton";

type Profile = { id: string; file_name: string; parsed: { name: string; headline: string; skills: string[]; tools: string[]; proof_points: string[] } };

export default function ProfilePage() {
  const toast = useToast();
  const qc = useQueryClient();
  const nav = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: ["profile"], queryFn: () => api<Profile | null>("/profiles/active") });

  const upload = useMutation({
    mutationFn: (f: File) => { const form = new FormData(); form.append("file", f); return api("/profiles", { form }); },
    onSuccess: () => { toast("CV uploaded and parsed"); qc.invalidateQueries({ queryKey: ["profile"] }); },
    onError: (e: Error) => toast(e.message, true),
  });
  const gen = useMutation({
    mutationFn: (id: string) => api(`/profiles/${id}/offer-map`, { method: "POST" }),
    onSuccess: () => { toast("Offer map created"); qc.invalidateQueries({ queryKey: ["offer-map"] }); nav("/offer-map"); },
    onError: (e: Error) => toast(e.message, true),
  });

  const p = data?.parsed;
  return (
    <div className="page">
      <div className="page-head">
        <span>Profile & CV</span>
        {data && <button className="btn-primary" disabled={gen.isPending} onClick={() => gen.mutate(data.id)}>
          {gen.isPending ? "Working…" : "Generate offer map"}</button>}
      </div>
      <div className="page-body flex flex-col gap-4">
        <div
          className="card flex flex-col items-center gap-2 py-10" style={{ borderStyle: "dashed", background: drag ? "var(--bg-4)" : undefined }}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) upload.mutate(f); }}
        >
          <p style={{ color: "var(--text-muted)" }}>{upload.isPending ? "Reading your CV…" : "Drop a CV here (PDF, DOCX, TXT, MD · max 5 MB)"}</p>
          <button className="btn" onClick={() => input.current?.click()} disabled={upload.isPending}>Choose file</button>
          <input ref={input} type="file" hidden accept=".pdf,.docx,.txt,.md" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
        </div>
        {isLoading && <Skeleton />}
        {!isLoading && !p && <p style={{ color: "var(--text-muted)" }}>No CV yet. Upload one above.</p>}
        {p && (
          <div className="card flex flex-col gap-4">
            <div><div className="font-semibold">{p.name}</div><div style={{ color: "var(--text-muted)" }}>{p.headline}</div></div>
            <div><span className="label">Skills</span><div className="flex flex-wrap gap-1.5">{p.skills.map((s) => <span key={s} className="chip">{s}</span>)}</div></div>
            <div><span className="label">Tools</span><div className="flex flex-wrap gap-1.5">{p.tools.map((s) => <span key={s} className="chip">{s}</span>)}</div></div>
            <div><span className="label">Proof points</span><ul className="list-disc pl-5">{p.proof_points.map((s) => <li key={s}>{s}</li>)}</ul></div>
          </div>
        )}
      </div>
    </div>
  );
}
