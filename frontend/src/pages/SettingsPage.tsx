import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useToast } from "../components/Toast";

type S = {
  sender_name: string | null; sender_title: string | null; signature: string | null; postal_address: string | null;
  auto_send: boolean; daily_send_cap: number; dry_run: boolean;
  gmail_connected: boolean; gmail_address: string | null;
  warmup_enabled: boolean; send_window_start: string; send_window_end: string;
  min_gap_seconds: number; max_gap_seconds: number; followup_days: number[]; firecrawl_start_balance?: number | null;
};
type Text = "sender_name" | "sender_title" | "postal_address";
type Num = "daily_send_cap" | "min_gap_seconds" | "max_gap_seconds";

export default function SettingsPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => api<S>("/settings") });
  const [f, setF] = useState<Partial<S>>({});
  useEffect(() => { if (data) setF(data); }, [data]);

  // Google sends the user back here with ?gmail=connected or ?gmail=error&reason=...
  useEffect(() => {
    const g = params.get("gmail");
    if (!g) return;
    if (g === "connected") toast("Gmail connected");
    else toast(params.get("reason") || "Gmail connect failed", true);
    qc.invalidateQueries({ queryKey: ["settings"] });
    qc.invalidateQueries({ queryKey: ["sending-status"] });
    setParams({}, { replace: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => { qc.invalidateQueries({ queryKey: ["settings"] }); qc.invalidateQueries({ queryKey: ["sending-status"] }); };
  const save = useMutation({
    mutationFn: () => api("/settings", { method: "PUT", body: {
      sender_name: f.sender_name, sender_title: f.sender_title, signature: f.signature, postal_address: f.postal_address,
      auto_send: f.auto_send, daily_send_cap: f.daily_send_cap, warmup_enabled: f.warmup_enabled,
      send_window_start: f.send_window_start, send_window_end: f.send_window_end,
      min_gap_seconds: f.min_gap_seconds, max_gap_seconds: f.max_gap_seconds, followup_days: f.followup_days, firecrawl_start_balance: f.firecrawl_start_balance,
    } }),
    onSuccess: () => { toast("Settings saved"); refresh(); },
    onError: (e: Error) => toast(e.message, true),
  });
  const connect = useMutation({
    mutationFn: () => api<{ url: string }>("/auth/google/start", { method: "POST", body: {} }),
    onSuccess: (r) => { window.location.href = r.url; },
    onError: (e: Error) => toast(e.message, true),
  });
  const disconnect = useMutation({
    mutationFn: () => api("/auth/google/disconnect", { method: "POST" }),
    onSuccess: () => { toast("Gmail disconnected"); refresh(); },
    onError: (e: Error) => toast(e.message, true),
  });
  const testLead = useMutation({
    mutationFn: () => api<{ email: string }>("/gmail/test-lead", { method: "POST", body: { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone } }),
    onSuccess: (r) => toast(`Test lead made. It is in the Review queue. Emails go to ${r.email}`),
    onError: (e: Error) => toast(e.message, true),
  });

  const text = (k: Text, label: string) => (
    <div><span className="label">{label}</span><input className="input" value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>
  );
  const num = (k: Num, label: string) => (
    <div><span className="label">{label}</span><input className="input" type="number" value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: Number(e.target.value) })} /></div>
  );
  const days = f.followup_days ?? [3, 4, 7];
  const needsReconnect = !!data?.gmail_address && !data?.gmail_connected;

  return (
    <div className="page">
      <div className="page-head"><span>Settings</span><button className="btn-primary" onClick={() => save.mutate()}>Save</button></div>
      <div className="page-body flex max-w-xl flex-col gap-4">
        <div className="card flex flex-col gap-2">
          <span className="label">Gmail</span>
          <div className="flex items-center gap-2">
            <span className="dot" style={{ background: data?.gmail_connected ? "var(--ok)" : needsReconnect ? "var(--bad)" : "var(--text-faint)", marginRight: 0 }} />
            <span>{data?.gmail_connected ? `Connected as ${data.gmail_address}` : needsReconnect ? `Login for ${data?.gmail_address} no longer works` : "Not connected"}</span>
            <span className="flex-1" />
            {data?.gmail_connected && <button className="btn btn-danger" onClick={() => disconnect.mutate()}>Disconnect</button>}
            <button className="btn-primary" onClick={() => connect.mutate()}>{data?.gmail_connected ? "Reconnect" : needsReconnect ? "Reconnect Gmail" : "Connect Gmail"}</button>
          </div>
          {data?.gmail_connected && (
            <div className="flex items-center gap-2" style={{ color: "var(--text-faint)", fontSize: 12 }}>
              <button className="btn" onClick={() => testLead.mutate()}>Create test lead</button>
              Makes a lead that emails your own address. Use it for the one real test.
            </div>
          )}
        </div>

        {text("sender_name", "Sender name")}
        {text("sender_title", "Sender title")}
        <div><span className="label">Signature (optional, replaces name + title)</span><textarea className="textarea" value={f.signature ?? ""} onChange={(e) => setF({ ...f, signature: e.target.value })} /></div>
        {text("postal_address", "Postal address (needed for US/UK email rules, and for real sending)")}

        <div className="card flex flex-col gap-3">
          <span className="label">Sending limits</span>
          <div className="grid grid-cols-2 gap-3">
            {num("daily_send_cap", "Daily cap (max 50)")}
            <label className="flex items-end gap-2 pb-2"><input type="checkbox" checked={!!f.warmup_enabled} onChange={(e) => setF({ ...f, warmup_enabled: e.target.checked })} /> Warm-up (10 a day, +5 each week)</label>
            <div><span className="label">Send window start (lead's time)</span><input className="input" type="time" value={f.send_window_start ?? ""} onChange={(e) => setF({ ...f, send_window_start: e.target.value })} /></div>
            <div><span className="label">Send window end (lead's time)</span><input className="input" type="time" value={f.send_window_end ?? ""} onChange={(e) => setF({ ...f, send_window_end: e.target.value })} /></div>
            {num("min_gap_seconds", "Min gap between emails (seconds)")}
            {num("max_gap_seconds", "Max gap between emails (seconds)")}
          </div>
          <div>
            <span className="label">Follow-up after (business days): step 1, step 2, step 3</span>
            <div className="grid grid-cols-3 gap-3">
              {[0, 1, 2].map((i) => (
                <input key={i} className="input" type="number" value={days[i] ?? ""} onChange={(e) => setF({ ...f, followup_days: days.map((d, j) => (j === i ? Number(e.target.value) : d)) })} />
              ))}
            </div>
          </div>
        </div>

        <div>
          <span className="label">Firecrawl starting balance (credits). Used for "credits left".</span>
          <input className="input" type="number" min={0} value={f.firecrawl_start_balance ?? ""} onChange={(e) => setF({ ...f, firecrawl_start_balance: e.target.value === "" ? null : Number(e.target.value) })} />
        </div>

        <label className="flex items-center gap-2"><input type="checkbox" checked={!!f.auto_send} onChange={(e) => setF({ ...f, auto_send: e.target.checked })} /> Auto send (skip the review queue)</label>
        <div style={{ color: "var(--text-faint)", fontSize: 12 }}>Keep review on for the first 50 leads. DRY_RUN is {data?.dry_run ? "on" : "off"} (set in .env).</div>
      </div>
    </div>
  );
}
