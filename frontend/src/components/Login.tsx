import { useState } from "react";
import { api, setPassword } from "../api/client";

export default function Login({ onDone }: { onDone: () => void }) {
  const [v, setV] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setErr("");
    setPassword(v);
    try { await api("/auth/check"); onDone(); }
    catch (e) { setPassword(""); setErr((e as Error).message === "Password needed" ? "Wrong password." : (e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="flex h-full items-center justify-center" style={{ background: "var(--bg-0)" }}>
      <form className="card flex w-80 flex-col gap-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="font-semibold">Proofhunt</div>
        <div style={{ color: "var(--text-faint)", fontSize: 12, marginTop: -8 }}>Find the proof. Then write the email.</div>
        <input className="input" type="password" autoFocus placeholder="Password" value={v} onChange={(e) => setV(e.target.value)} />
        {err && <div style={{ color: "var(--bad)", fontSize: 12 }}>{err}</div>}
        <button className="btn-primary" disabled={busy || !v}>Sign in</button>
      </form>
    </div>
  );
}
