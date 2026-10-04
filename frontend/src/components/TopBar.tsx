import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Check, ChevronDown, Plus } from "lucide-react";
import { nav as groups } from "../nav";
import { useProfiles } from "../lib/profile";

const items = groups.flatMap((g) => g.items);
export const isShared = (path: string) => !!items.find((i) => i.path === path)?.shared;

const initial = (name?: string) => (name?.trim()[0] ?? "?").toUpperCase();

function Switcher() {
  const { profiles, current, select } = useProfiles();
  const go = useNavigate();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", away); window.removeEventListener("keydown", esc); };
  }, [open]);

  return (
    <div ref={box} className="relative">
      <button className="btn flex items-center gap-2" style={{ padding: "3px 10px" }} aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="avatar">{initial(current?.name)}</span>
        <span className="truncate" style={{ maxWidth: 200, fontSize: 13 }}>{current?.name ?? "No profile yet"}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="menu" role="listbox">
          {profiles.map((p) => (
            <button key={p.id} className="menu-item" role="option" aria-selected={p.id === current?.id} onClick={() => { select(p.id); setOpen(false); }}>
              <span className="avatar">{initial(p.name)}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate">{p.name}</span>
                {p.headline && <span className="menu-sub block truncate">{p.headline}</span>}
              </span>
              {p.id === current?.id && <Check size={14} />}
            </button>
          ))}
          {profiles.length > 0 && <div className="menu-sep" />}
          <button className="menu-item" onClick={() => { setOpen(false); go("/profile?new=1"); }}><Plus size={14} />New profile</button>
        </div>
      )}
    </div>
  );
}

/** Top corner of every page: which profile you are looking at. Account-wide pages say so instead. */
export default function TopBar() {
  const { pathname } = useLocation();
  return (
    <div className="topbar">
      {isShared(pathname) ? <span>Shared by all profiles</span> : <><span>Profile</span><Switcher /></>}
    </div>
  );
}
