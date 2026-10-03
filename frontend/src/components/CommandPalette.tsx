import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Building2, Users, type LucideIcon } from "lucide-react";
import { api } from "../api/client";
import { nav } from "../nav";

type Item = { key: string; label: string; sub?: string; icon: LucideIcon; to: string };
const pages: Item[] = nav.flatMap((g) => g.items.map((i) => ({ key: i.path, label: i.label, sub: g.label, icon: i.icon, to: i.path })));

/** Ctrl+K (or Cmd+K): jump to a page, a company or a lead. */
export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const [term, setTerm] = useState("");
  const go = useNavigate();
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); setQ(""); setSel(0); }
      else if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  useEffect(() => { if (open) input.current?.focus(); }, [open]);
  useEffect(() => { const t = setTimeout(() => setTerm(q.trim()), 200); return () => clearTimeout(t); }, [q]);

  const enabled = open && term.length >= 2;
  const co = useQuery({ queryKey: ["pal-co", term], enabled, queryFn: () => api<{ id: string; domain: string; name: string | null }[]>(`/companies?q=${encodeURIComponent(term)}`) });
  const ld = useQuery({ queryKey: ["pal-ld", term], enabled, queryFn: () => api<{ id: string; stage: string; companies: { domain: string; name: string | null } }[]>(`/leads?q=${encodeURIComponent(term)}`) });

  const items = useMemo<Item[]>(() => {
    const needle = q.trim().toLowerCase();
    const p = pages.filter((i) => !needle || i.label.toLowerCase().includes(needle));
    const c = (enabled ? co.data ?? [] : []).slice(0, 6).map((x) => ({ key: "c" + x.id, label: x.name || x.domain, sub: `Company · ${x.domain}`, icon: Building2, to: `/companies?id=${x.id}` }));
    const l = (enabled ? ld.data ?? [] : []).slice(0, 6).map((x) => ({ key: "l" + x.id, label: x.companies.name || x.companies.domain, sub: `Lead · ${x.stage.replace(/_/g, " ")}`, icon: Users, to: `/leads?id=${x.id}` }));
    return [...p, ...c, ...l];
  }, [q, enabled, co.data, ld.data]);

  if (!open) return null;
  const pick = (i?: Item) => { if (i) { go(i.to); setOpen(false); } };
  return (
    <div className="palette" onClick={() => setOpen(false)}>
      <div className="palette-box" onClick={(e) => e.stopPropagation()}>
        <input ref={input} className="input" style={{ border: 0, borderBottom: "1px solid var(--border)", borderRadius: 0, padding: 14 }}
          placeholder="Jump to a page, company or lead" value={q}
          onChange={(e) => { setQ(e.target.value); setSel(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
            else if (e.key === "Enter") pick(items[sel]);
          }} />
        <div className="overflow-y-auto p-1">
          {!items.length && <div className="p-4" style={{ color: "var(--text-faint)" }}>Nothing found.</div>}
          {items.map((i, n) => (
            <button key={i.key} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left" onMouseEnter={() => setSel(n)} onClick={() => pick(i)}
              style={{ background: n === sel ? "var(--bg-4)" : "transparent" }}>
              <i.icon size={16} strokeWidth={1.75} /><span className="flex-1 truncate">{i.label}</span>
              <span style={{ color: "var(--text-faint)", fontSize: 12 }}>{i.sub}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
