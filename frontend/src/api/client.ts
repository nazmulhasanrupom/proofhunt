export const BASE = import.meta.env.VITE_API_URL || "/api";

const KEY = "accessPassword";
export const getPassword = () => { try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; } };
export const setPassword = (v: string) => { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch { /* private mode */ } };

// The profile every call is for. ProfileProvider sets it. Sent as X-Profile-Id.
let activeProfile = "";
export const setActiveProfile = (id: string) => { activeProfile = id; };
export const getActiveProfile = () => activeProfile;

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body) headers["Content-Type"] = "application/json";
  const pw = getPassword();
  if (pw) headers["Authorization"] = `Bearer ${pw}`;
  if (activeProfile) headers["X-Profile-Id"] = activeProfile;
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method: opts.method ?? (opts.body || opts.form ? "POST" : "GET"),
      headers,
      body: opts.form ?? (opts.body ? JSON.stringify(opts.body) : undefined),
    });
  } catch {
    throw new ApiError("Cannot reach the server. Check that the API is running.", 0);
  }
  if (res.status === 401) window.dispatchEvent(new Event("auth-required"));
  if (!res.ok) {
    let msg = res.statusText || `Error ${res.status}`;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch { /* keep statusText */ }
    throw new ApiError(msg, res.status);
  }
  return res.json() as Promise<T>;
}

/** POST, and get a file back (for example a CSV). Same headers as api(). */
export async function fetchFile(path: string, body: unknown): Promise<File> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const pw = getPassword();
  if (pw) headers["Authorization"] = `Bearer ${pw}`;
  if (activeProfile) headers["X-Profile-Id"] = activeProfile;
  let res: Response;
  try {
    res = await fetch(BASE + path, { method: "POST", headers, body: JSON.stringify(body) });
  } catch {
    throw new ApiError("Cannot reach the server. Check that the API is running.", 0);
  }
  if (res.status === 401) window.dispatchEvent(new Event("auth-required"));
  if (!res.ok) {
    let msg = res.statusText || `Error ${res.status}`;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j); } catch { /* keep statusText */ }
    throw new ApiError(msg, res.status);
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? "download.csv";
  return new File([await res.blob()], name, { type: "text/csv" });
}

/** Save a file to the computer. */
export function saveFile(f: File) {
  const url = URL.createObjectURL(f);
  const a = document.createElement("a");
  a.href = url; a.download = f.name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The phone / browser share sheet, when it can send files. */
export const canShareFile = (f: File) => typeof navigator !== "undefined" && !!navigator.canShare && navigator.canShare({ files: [f] });
