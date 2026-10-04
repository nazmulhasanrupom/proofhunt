import { useEffect, useState } from "react";
import { getActiveProfile } from "../api/client";

const LEGACY_KEY = "repliesSeenAt";  // before profiles there was one value for everything
const EVT = "replies-seen";

// each profile has its own replies, so each has its own "seen" time
const key = () => `${LEGACY_KEY}:${getActiveProfile()}`;
const read = () => { try { return localStorage.getItem(key()) ?? localStorage.getItem(LEGACY_KEY) ?? ""; } catch { return ""; } };

/** Mark replies up to this server time as read. Kept in the browser (no DB column needed). */
export function markRepliesSeen(latest: string | undefined) {
  if (!latest || latest <= read()) return;
  try { localStorage.setItem(key(), latest); } catch { /* private mode: badge just stays */ }
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
