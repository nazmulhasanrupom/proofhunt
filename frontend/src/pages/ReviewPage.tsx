import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import Empty from "../components/Empty";
import Skeleton from "../components/Skeleton";
import SendBanner from "../components/SendBanner";

type Msg = { id: string; step: number; subject: string; body: string; error: string | null; evidence_ids: string[] };
type Lead = {
  id: string; score: number;
  companies: { domain: string; name: string }; people: { name: string; title: string; email: string; email_kind: string } | null;
  judgments: { problem: string; fix: string } | null;  // null for a test lead
  messages: Msg[]; evidence: { id: string; quote: string; url: string; kind: string }[];
  assets: { kind: string; content_md: string }[];
};

export default function ReviewPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["review"], queryFn: () => api<Lead[]>("/review") });
  const [sel, setSel] = useState(0);
  const lead = data?.[Math.min(sel, (data?.length ?? 1) - 1)];

  const done = () => qc.invalidateQueries({ queryKey: ["review"] });
  const act = useMutation({
    mutationFn: ({ id, what }: { id: string; what: "approve" | "skip" | "regenerate" }) => api(`/leads/${id}/${what}`, { method: "POST" }),
    onSuccess: (_d, v) => { toast(v.what === "approve" ? "Approved" : v.what === "skip" ? "Skipped" : "New drafts created"); done(); },
    onError: (e: Error) => toast(e.message, true),
  });
  const save = async (m: Msg, patch: Partial<Msg>) => {
    try { await api(`/messages/${m.id}`, { method: "PATCH", body: patch }); toast("Saved"); done(); }
    catch (e) { toast((e as Error).message, true); }
  };

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (["TEXTAREA", "INPUT"].includes(t.tagName) || !data?.length || !lead) return;
      const k = e.key.toLowerCase();
      if (k === "j") setSel((s) => Math.min(s + 1, data.length - 1));
      else if (k === "k") setSel((s) => Math.max(s - 1, 0));
      else if (k === "a") act.mutate({ id: lead.id, what: "approve" });
      else if (k === "s") act.mutate({ id: lead.id, what: "skip" });
      else if (k === "r") act.mutate({ id: lead.id, what: "regenerate" });
      else if (k === "e") document.querySelector<HTMLTextAreaElement>("textarea")?.focus();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  return (
    <div className="page">
      <div className="page-head">
        <span>Review queue</span>
        <span style={{ color: "var(--text-faint)", fontSize: 12 }}>A approve · E edit · R regenerate · S skip · J/K next/prev</span>
      </div>
      <SendBanner />
      <div className="flex min-h-0 flex-1">
        <div className="w-64 shrink-0 overflow-y-auto border-r p-2" style={{ borderColor: "var(--border)" }}>
          {isLoading && <Skeleton />}
          {data?.map((l, i) => (
            <button key={l.id} onClick={() => setSel(i)} className="block w-full rounded-md px-3 py-2 text-left"
              style={{ background: lead?.id === l.id ? "var(--bg-4)" : "transparent" }}>
              <div>{l.companies.name || l.companies.domain}</div>
              <div style={{ color: "var(--text-faint)", fontSize: 12 }}>{l.companies.domain} · score {l.score}</div>
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          {!isLoading && !lead && <Empty text="No drafts to review." />}
          {lead && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-semibold">{lead.people?.name ?? "No contact"} · {lead.people?.title ?? "—"}</div>
                  <div style={{ color: "var(--text-muted)" }}>{lead.people?.email ?? "—"} ({lead.people?.email_kind ?? "—"}) · {lead.companies.domain}</div>
                </div>
                <div className="flex gap-2">
                  <button className="btn" onClick={() => act.mutate({ id: lead.id, what: "regenerate" })}>Regenerate</button>
                  <button className="btn btn-danger" onClick={() => act.mutate({ id: lead.id, what: "skip" })}>Skip</button>
                  <button className="btn-primary" onClick={() => act.mutate({ id: lead.id, what: "approve" })}>Approve</button>
                </div>
              </div>
              {lead.judgments && <div className="card"><span className="label">Problem</span>{lead.judgments.problem}<span className="label mt-2">Fix</span>{lead.judgments.fix}</div>}
              <div className="grid gap-4" style={{ gridTemplateColumns: "1fr 280px" }}>
                <div className="flex flex-col gap-3">
                  {lead.messages.map((m) => (
                    <div key={m.id} className="card flex flex-col gap-2">
                      <span className="label">{m.step === 0 ? "Main email" : `Follow-up ${m.step}`}</span>
                      {m.error && <div style={{ color: "var(--warn)", fontSize: 12 }}>{m.error}</div>}
                      <input className="input" key={m.id + m.subject} defaultValue={m.subject} onBlur={(e) => e.target.value !== m.subject && save(m, { subject: e.target.value })} />
                      <textarea className="textarea" style={{ minHeight: 160 }} key={m.id + m.body} defaultValue={m.body} onBlur={(e) => e.target.value !== m.body && save(m, { body: e.target.value })} />
                    </div>
                  ))}
                </div>
                <div className="flex flex-col gap-3">
                  <span className="label">Evidence used</span>
                  {lead.evidence.map((e) => (
                    <div key={e.id} className="card" style={{ fontSize: 12 }}>“{e.quote}”<div><a href={e.url} target="_blank" rel="noreferrer" style={{ color: "var(--text-faint)" }}>{e.url}</a></div></div>
                  ))}
                  {lead.assets.map((a) => (
                    <details key={a.kind} className="card" style={{ fontSize: 12 }}>
                      <summary>{a.kind === "report" ? "Audit report" : "Demo spec"}</summary>
                      <pre style={{ whiteSpace: "pre-wrap" }}>{a.content_md}</pre>
                    </details>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
