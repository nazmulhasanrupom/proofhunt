import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useProfiles, type ProfileKind } from "../lib/profile";
import { useToast } from "./Toast";

/** What a profile can be. "General" holds the business types: today only IMA (an influencer marketing agency), more will follow. */
const BUSINESSES: { kind: ProfileKind; label: string }[] = [{ kind: "ima", label: "IMA (influencer marketing agency)" }];

/** New profile: a type, a name and a file. A freelancer uploads a CV, a general business uploads its brief. The AI reads it, then you can generate the offer map. */
export default function NewProfileDialog({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const { select } = useProfiles();
  const [name, setName] = useState("");
  const [type, setType] = useState<"freelancer" | "general">("freelancer");
  const [business, setBusiness] = useState<ProfileKind>(BUSINESSES[0].kind);
  const kind: ProfileKind = type === "freelancer" ? "freelancer" : business;
  const doc = kind === "ima" ? "agency brief" : "CV";
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const create = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("name", name.trim());
      form.append("kind", kind);
      form.append("file", file!);
      return api<{ id: string; name: string }>("/profiles", { form });
    },
    onSuccess: async (p) => {
      await qc.invalidateQueries({ queryKey: ["profiles"] });  // wait: the new profile must be in the list before we pick it
      select(p.id);
      toast(`Profile '${p.name}' created`);
      onClose();
    },
    onError: (e: Error) => toast(e.message, true),
  });
  const ready = name.trim() !== "" && !!file && !create.isPending;
  const pick = (f?: File) => { if (f) setFile(f); };

  return (
    <>
      <div className="fixed inset-0" style={{ background: "rgba(0,0,0,.5)", zIndex: 70 }} onClick={() => !create.isPending && onClose()} />
      <form className="card fixed flex flex-col gap-3" style={{ zIndex: 71, left: "50%", top: "10vh", transform: "translateX(-50%)", width: 460, maxWidth: "92vw", background: "var(--bg-2)" }}
        onSubmit={(e) => { e.preventDefault(); if (ready) create.mutate(); }}>
        <div className="font-semibold">New profile</div>
        <div>
          <span className="label">Name</span>
          <input className="input" autoFocus maxLength={60} placeholder={kind === "ima" ? "For example: Fylint" : "For example: SEO consultant"} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <span className="label">Type</span>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Profile type">
            {([["freelancer", "Freelancer", "You sell your own skills. Upload a CV."], ["general", "General", "A business. Pick its kind below."]] as const).map(([v, title, sub]) => (
              <button key={v} type="button" role="radio" aria-checked={type === v} disabled={create.isPending} className="rounded-md border p-2 text-left"
                style={{ borderColor: type === v ? "var(--accent)" : "var(--border)", background: type === v ? "var(--bg-4)" : undefined }} onClick={() => setType(v)}>
                <div className="font-semibold" style={{ fontSize: 13 }}>{title}</div>
                <div style={{ color: "var(--text-muted)", fontSize: 12 }}>{sub}</div>
              </button>
            ))}
          </div>
          {type === "general" && (
            <select className="select mt-2" aria-label="Business kind" value={business} disabled={create.isPending} onChange={(e) => setBusiness(e.target.value as ProfileKind)}>
              {BUSINESSES.map((b) => <option key={b.kind} value={b.kind}>{b.label}</option>)}
            </select>
          )}
        </div>
        <div>
          <span className="label">{kind === "ima" ? "Agency brief" : "CV"}</span>
          <div className="flex flex-col items-center gap-2 rounded-md border py-6 text-center"
            style={{ borderStyle: "dashed", borderColor: "var(--border)", background: drag ? "var(--bg-4)" : undefined }}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}>
            <p style={{ color: file ? "var(--text)" : "var(--text-muted)" }}>{file ? file.name : `Drop a ${doc} here (PDF, DOCX, TXT, MD · max 5 MB)`}</p>
            <button type="button" className="btn" onClick={() => input.current?.click()} disabled={create.isPending}>{file ? "Choose another file" : "Choose file"}</button>
            <input ref={input} type="file" hidden accept=".pdf,.docx,.txt,.md" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
          </div>
        </div>
        {create.isPending && <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Reading your {doc}. This takes a few seconds.</div>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose} disabled={create.isPending}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={!ready}>{create.isPending ? "Creating…" : "Create profile"}</button>
        </div>
      </form>
    </>
  );
}
