import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import Empty from "../components/Empty";
import Skeleton from "../components/Skeleton";
import SendBanner, { useSendStatus } from "../components/SendBanner";
import Drawer from "../components/Drawer";
import MessageEditor from "../components/MessageEditor";

type Row = {
  id: string; step: number; subject: string; body: string; status: string; scheduled_at: string | null; sent_at: string | null; error: string | null;
  gmail_message_id: string | null;
  leads: { timezone: string | null; companies: { domain: string; name: string }; people: { name: string; email: string } };
};

const DOT: Record<string, string> = { draft: "var(--text-faint)", sent: "var(--ok)", failed: "var(--bad)", sending: "var(--warn)", scheduled: "var(--warn)", approved: "var(--warn)", cancelled: "var(--text-faint)" };
const FILTERS = ["", "approved", "scheduled", "draft", "sent", "failed", "cancelled"];
const EDITABLE = ["draft", "approved", "scheduled", "failed"];
const time = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");
const day = (r: Row) => { const t = r.sent_at ?? r.scheduled_at; return t ? new Date(t).toLocaleDateString([], { weekday: "short", year: "numeric", month: "short", day: "numeric" }) : "Waiting for a time"; };

export default function OutboxPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const { data: s } = useSendStatus();
  const { data, isLoading } = useQuery({ queryKey: ["outbox", status], queryFn: () => api<Row[]>(`/outbox${status ? `?status=${status}` : ""}`), refetchInterval: 15000 });
  const retry = useMutation({
    mutationFn: (id: string) => api(`/messages/${id}/retry`, { method: "POST" }),
    onSuccess: () => { toast("Back in the queue"); qc.invalidateQueries({ queryKey: ["outbox"] }); },
    onError: (e: Error) => toast(e.message, true),
  });
  const [edit, setEdit] = useState<string | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["outbox"] }); qc.invalidateQueries({ queryKey: ["counts"] }); qc.invalidateQueries({ queryKey: ["review"] }); };
  const unapprove = useMutation({
    mutationFn: (id: string) => api<{ back_in_review: boolean }>(`/messages/${id}/unapprove`, { method: "POST" }),
    onSuccess: (r) => { toast(r.back_in_review ? "Unapproved. The lead is back in the Review queue" : "Unapproved. It is a draft now"); refresh(); },
    onError: (e: Error) => toast(e.message, true),
  });
  const approve = useMutation({
    mutationFn: (id: string) => api(`/messages/${id}/approve`, { method: "POST" }),
    onSuccess: () => { toast("Approved"); refresh(); }, onError: (e: Error) => toast(e.message, true),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/messages/${id}`, { method: "DELETE" }),
    onSuccess: () => { toast("Deleted"); setEdit(null); refresh(); }, onError: (e: Error) => toast(e.message, true),
  });
  const editing = data?.find((r) => r.id === edit);
  const groups = new Map<string, Row[]>();
  data?.forEach((r) => groups.set(day(r), [...(groups.get(day(r)) ?? []), r]));

  return (
    <div className="page">
      <div className="page-head">
        <span>Outbox</span>
        <div className="flex items-center gap-3">
          {s && <span style={{ color: "var(--text-muted)", fontSize: 12 }}>Last 24 h: {s.sent_24h} of {s.cap} sent</span>}
          <select className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
            {FILTERS.map((f) => <option key={f} value={f}>{f || "All"}</option>)}
          </select>
        </div>
      </div>
      <SendBanner />
      <div className="page-body">
        {isLoading && <Skeleton />}
        {!isLoading && !data?.length && <Empty text="No messages yet. Approve a lead in the Review queue." />}
        {[...groups.entries()].map(([d, rows]) => (
          <div key={d} className="mb-6">
            <div className="label">{d}</div>
            <table className="table">
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td style={{ width: 70, color: "var(--text-faint)" }}>{time(r.sent_at ?? r.scheduled_at)}</td>
                    <td style={{ width: 200 }}>{r.leads.companies.name || r.leads.companies.domain}</td>
                    <td style={{ width: 240, color: "var(--text-muted)" }}>{r.leads.people.email}</td>
                    <td style={{ width: 90 }}>{r.step === 0 ? "Main" : `Follow-up ${r.step}`}</td>
                    <td>{r.subject}{r.error && <div style={{ color: "var(--bad)", fontSize: 12 }}>{r.error}</div>}</td>
                    <td style={{ width: 130 }}>
                      <span className="dot" style={{ background: DOT[r.status] ?? "var(--text-faint)" }} />{r.status}{r.gmail_message_id === "dry-run" ? " (dry run)" : ""}
                    </td>
                    <td style={{ width: 300 }} className="text-right">
                      <span className="flex justify-end gap-1">
                        {r.status === "failed" && <button className="btn" onClick={() => retry.mutate(r.id)}>Retry</button>}
                        {r.status === "draft" && <button className="btn" onClick={() => approve.mutate(r.id)}>Approve</button>}
                        {["approved", "scheduled", "failed"].includes(r.status) && <button className="btn" onClick={() => unapprove.mutate(r.id)}>Unapprove</button>}
                        {EDITABLE.includes(r.status) && <button className="btn" onClick={() => setEdit(r.id)}>Edit</button>}
                        {r.status !== "sent" && r.status !== "sending" && <button className="btn btn-danger" onClick={() => { if (confirm("Delete this email? Later emails of this lead that are not sent will be cancelled.")) remove.mutate(r.id); }}>Delete</button>}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      {editing && (
        <Drawer title={editing.leads.companies.name || editing.leads.companies.domain} sub={`${editing.leads.people.email} · ${editing.status}`} onClose={() => setEdit(null)}>
          <div className="flex-1 overflow-y-auto p-4">
            {["approved", "scheduled"].includes(editing.status) && (
              <div className="mb-3" style={{ color: "var(--text-muted)", fontSize: 12 }}>This email is waiting to be sent. Your changes are used when it goes out.</div>
            )}
            <MessageEditor m={editing} onSaved={refresh} />
          </div>
        </Drawer>
      )}
    </div>
  );
}
