import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Ctx = (msg: string, bad?: boolean) => void;
const ToastCtx = createContext<Ctx>(() => {});
let external: Ctx = () => {};
/** For code outside React (the query cache). */
export const pushToast: Ctx = (m, b) => external(m, b);
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string; bad: boolean }[]>([]);
  const push = useCallback<Ctx>((msg, bad = false) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, msg, bad }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 3000);
  }, []);
  external = push;
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 flex flex-col gap-2" style={{ zIndex: 50 }}>
        {items.map((i) => (
          <div key={i.id} className="card" style={{ padding: "8px 14px", borderColor: i.bad ? "var(--bad)" : "var(--border)" }}>{i.msg}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
