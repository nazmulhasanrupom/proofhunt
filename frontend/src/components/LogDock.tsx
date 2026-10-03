import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Trash2 } from "lucide-react";
import { api } from "../api/client";

type Ev = { id: number; level: string; stage: string | null; message: string; created_at: string; run_id: string | null };
const COLOR: Record<string, string> = { error: "var(--bad)", warn: "var(--warn)", info: "var(--text-muted)" };
const KEY = "logDockOpen";
const get = () => { try { return localStorage.getItem(KEY) === "1"; } catch { return false; } };

/** Backend log at the bottom of every page: runs, sending, replies, email edits. */
export default function LogDock() {
  const [open, setOpen] = useState(get);
  const [events, setEvents] = useState<Ev[]>([]);
  const [level, setLevel] = useState("all");
  const [offline, setOffline] = useState(false);
  const last = useRef(0);
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    let dead = false;
    const tick = async () => {
      try {
        const more = await api<Ev[]>(`/events?after=${last.current}&limit=150`);
        if (dead) return;
        setOffline(false);
        if (more.length) { last.current = more[more.length - 1].id; setEvents((e) => [...e, ...more].slice(-600)); }
      } catch { if (!dead) setOffline(true); }
    };
    tick();
    const t = setInterval(tick, open ? 3000 : 10000);
    return () => { dead = true; clearInterval(t); };
  }, [open]);

  useEffect(() => { if (open && stick.current && box.current) box.current.scrollTop = box.current.scrollHeight; }, [events, open, level]);
  const toggle = () => { const v = !open; setOpen(v); try { localStorage.setItem(KEY, v ? "1" : "0"); } catch { /* ignore */ } };

  const shown = events.filter((e) => level === "all" || e.level === level);
  const tail = events[events.length - 1];
  const errors = events.filter((e) => e.level === "error").length;
  return (
    <div className="shrink-0 border-t" style={{ borderColor: "var(--border)", background: "var(--bg-1)" }}>
      <div className="flex h-8 items-center gap-3 px-4" style={{ fontSize: 12 }}>
        <button className="flex items-center gap-1" onClick={toggle} style={{ color: "var(--text-muted)" }}>
          {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}<span className="font-medium">Log</span>
        </button>
        {errors > 0 && <span className="chip" style={{ color: "var(--bad)" }}>{errors} error{errors > 1 ? "s" : ""}</span>}
        {offline && <span style={{ color: "var(--bad)" }}>cannot reach the server</span>}
        {!open && tail && <span className="truncate" style={{ color: COLOR[tail.level] ?? "var(--text-muted)" }}>[{tail.stage}] {tail.message}</span>}
        {open && (
          <>
            <select className="select" style={{ width: 100, padding: "2px 6px", fontSize: 12 }} value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="all">All</option><option value="info">Info</option><option value="warn">Warnings</option><option value="error">Errors</option>
            </select>
            <button onClick={() => setEvents([])} title="Clear the view" style={{ color: "var(--text-faint)" }}><Trash2 size={14} /></button>
            <span style={{ color: "var(--text-faint)" }}>{shown.length} lines · live</span>
          </>
        )}
      </div>
      {open && (
        <div ref={box} className="overflow-y-auto border-t px-4 py-2 font-mono" style={{ height: 220, fontSize: 12, borderColor: "var(--border)" }}
          onScroll={(e) => { const t = e.currentTarget; stick.current = t.scrollHeight - t.scrollTop - t.clientHeight < 24; }}>
          {!shown.length && <span style={{ color: "var(--text-faint)" }}>Nothing yet. Runs, sending, replies and email edits appear here.</span>}
          {shown.map((e) => (
            <div key={e.id} style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              <span style={{ color: "var(--text-faint)" }}>{new Date(e.created_at).toLocaleTimeString()} </span>
              <span style={{ color: COLOR[e.level] ?? "var(--text-muted)" }}>[{e.stage ?? "app"}] {e.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
