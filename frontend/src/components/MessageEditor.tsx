import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api } from "../api/client";
import { useToast } from "./Toast";

export type Msg = { id: string; step: number; subject: string; body: string; status?: string; error?: string | null };
type Rewritten = { subject: string; body: string; warnings: string[] };

/** Edit one email by hand or rewrite it with the AI. Typed edits save when you leave the field. An AI rewrite waits for your Save. */
export default function MessageEditor({ m, onSaved, readOnly }: { m: Msg; onSaved: () => void; readOnly?: boolean }) {
  const toast = useToast();
  const [subject, setSubject] = useState(m.subject);
  const [body, setBody] = useState(m.body);
  const [ai, setAi] = useState<Rewritten | null>(null);
  const [instruction, setInstruction] = useState("");
  const [showAi, setShowAi] = useState(false);
  useEffect(() => { setSubject(m.subject); setBody(m.body); setAi(null); }, [m.id, m.subject, m.body]);

  const save = useMutation({
    mutationFn: (p: { subject: string; body: string }) => api(`/messages/${m.id}`, { method: "PATCH", body: p }),
    onSuccess: () => { toast("Saved"); setAi(null); onSaved(); },
    onError: (e: Error) => toast(e.message, true),
  });
  const rewrite = useMutation({
    mutationFn: () => api<Rewritten>(`/messages/${m.id}/rewrite`, { method: "POST", body: { instruction } }),
    onSuccess: (r) => { setSubject(r.subject); setBody(r.body); setAi(r); },
    onError: (e: Error) => toast(e.message, true),
  });
  const typed = (s: string, b: string) => { if (!ai && !readOnly && (s !== m.subject || b !== m.body)) save.mutate({ subject: s, body: b }); };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="label mb-0">{m.step === 0 ? "Main email" : `Follow-up ${m.step}`}</span>
        {m.status && <span className="chip">{m.status}</span>}
        <span className="flex-1" />
        {!readOnly && <button className="btn" onClick={() => setShowAi(!showAi)}><Sparkles size={14} strokeWidth={1.75} style={{ display: "inline", marginRight: 4 }} />Rewrite with AI</button>}
      </div>
      {m.error && <div style={{ color: "var(--warn)", fontSize: 12 }}>{m.error}</div>}
      {showAi && !readOnly && (
        <div className="flex gap-2">
          <input className="input" placeholder="Optional: what to change. Example: shorter, friendlier, mention the report" value={instruction}
            onChange={(e) => setInstruction(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !rewrite.isPending && rewrite.mutate()} />
          <button className="btn-primary" style={{ whiteSpace: "nowrap" }} disabled={rewrite.isPending} onClick={() => rewrite.mutate()}>{rewrite.isPending ? "Writing…" : "Rewrite"}</button>
        </div>
      )}
      <input className="input" readOnly={readOnly} value={subject} onChange={(e) => setSubject(e.target.value)} onBlur={() => typed(subject, body)} />
      <textarea className="textarea" readOnly={readOnly} style={{ minHeight: 170 }} value={body} onChange={(e) => setBody(e.target.value)} onBlur={() => typed(subject, body)} />
      {ai && (
        <div className="card flex flex-col gap-2" style={{ padding: 10, borderColor: "var(--text-faint)" }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>AI draft. It is not saved yet. You can still edit it above.</div>
          {ai.warnings.length > 0 && <ul style={{ fontSize: 12, color: "var(--warn)", paddingLeft: 16, listStyle: "disc" }}>{ai.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
          <div className="flex gap-2">
            <button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate({ subject, body })}>Save this version</button>
            <button className="btn" onClick={() => { setSubject(m.subject); setBody(m.body); setAi(null); }}>Discard</button>
            <button className="btn" disabled={rewrite.isPending} onClick={() => rewrite.mutate()}>Try again</button>
          </div>
        </div>
      )}
    </div>
  );
}
