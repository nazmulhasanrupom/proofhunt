import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useProfiles } from "../lib/profile";
import { useToast } from "./Toast";

/** New profile: a name and a CV. The CV is read by the AI, then you can generate the offer map. */
export default function NewProfileDialog({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const { select } = useProfiles();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const create = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("name", name.trim());
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
      <form className="card fixed flex flex-col gap-3" style={{ zIndex: 71, left: "50%", top: "16vh", transform: "translateX(-50%)", width: 460, maxWidth: "92vw", background: "var(--bg-2)" }}
        onSubmit={(e) => { e.preventDefault(); if (ready) create.mutate(); }}>
        <div className="font-semibold">New profile</div>
        <div>
          <span className="label">Name</span>
          <input className="input" autoFocus maxLength={60} placeholder="For example: SEO consultant" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <span className="label">CV</span>
          <div className="flex flex-col items-center gap-2 rounded-md border py-6 text-center"
            style={{ borderStyle: "dashed", borderColor: "var(--border)", background: drag ? "var(--bg-4)" : undefined }}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}>
            <p style={{ color: file ? "var(--text)" : "var(--text-muted)" }}>{file ? file.name : "Drop a CV here (PDF, DOCX, TXT, MD · max 5 MB)"}</p>
            <button type="button" className="btn" onClick={() => input.current?.click()} disabled={create.isPending}>{file ? "Choose another file" : "Choose file"}</button>
            <input ref={input} type="file" hidden accept=".pdf,.docx,.txt,.md" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
          </div>
        </div>
        {create.isPending && <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Reading your CV. This takes a few seconds.</div>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose} disabled={create.isPending}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={!ready}>{create.isPending ? "Creating…" : "Create profile"}</button>
        </div>
      </form>
    </>
  );
}
