import { useLocation } from "react-router-dom";
import { nav } from "../nav";

export default function Placeholder() {
  const { pathname } = useLocation();
  const item = nav.flatMap((g) => g.items).find((i) => i.path === pathname);
  return (
    <div className="flex h-full flex-col" style={{ background: "var(--bg-2)" }}>
      <header className="flex h-12 items-center border-b px-6 font-medium" style={{ borderColor: "var(--border)" }}>
        {item?.label ?? "Not found"}
      </header>
      <div className="flex flex-1 flex-col items-center justify-center gap-3" style={{ color: "var(--text-muted)" }}>
        <p>{item?.hint ?? "Page not found."}</p>
        {item?.action && <button className="btn-primary" disabled style={{ opacity: 0.5 }}>{item.action}</button>}
      </div>
    </div>
  );
}
