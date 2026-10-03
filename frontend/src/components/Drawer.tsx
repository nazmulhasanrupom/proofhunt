import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";

export default function Drawer({ title, sub, onClose, children }: { title: string; sub?: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <>
      <div className="fixed inset-0" style={{ zIndex: 39 }} onClick={onClose} />
      <aside className="drawer">
        <div className="flex items-start gap-2 border-b px-4 py-3" style={{ borderColor: "var(--border)" }}>
          <div className="min-w-0 flex-1">
            <div className="truncate font-semibold">{title}</div>
            {sub && <div className="truncate" style={{ color: "var(--text-faint)", fontSize: 12 }}>{sub}</div>}
          </div>
          <button className="btn" onClick={onClose} aria-label="Close"><X size={16} strokeWidth={1.75} /></button>
        </div>
        {children}
      </aside>
    </>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: string[]; value: string; onChange: (t: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => <button key={t} role="tab" className="tab" aria-selected={t === value} onClick={() => onChange(t)}>{t}</button>)}
    </div>
  );
}

export function KV({ k, v }: { k: string; v: ReactNode }) {
  return <div className="flex gap-3 py-1" style={{ fontSize: 13 }}><span className="w-28 shrink-0" style={{ color: "var(--text-faint)" }}>{k}</span><span className="min-w-0 break-words">{v ?? "—"}</span></div>;
}
