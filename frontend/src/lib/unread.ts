import { useEffect, useState } from "react";

const KEY = "repliesSeenAt";
const EVT = "replies-seen";

const read = () => { try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; } };

/** Mark replies up to this server time as read. Kept in the browser (no DB column needed). */
export function markRepliesSeen(latest: string | undefined) {
  if (!latest || latest <= read()) return;
  try { localStorage.setItem(KEY, latest); } catch { /* private mode: badge just stays */ }
  window.dispatchEvent(new Event(EVT));
}

export function useSeenAt() {
  const [v, setV] = useState(read);
  useEffect(() => {
    const h = () => setV(read());
    window.addEventListener(EVT, h);
    return () => window.removeEventListener(EVT, h);
  }, []);
  return v;
}
