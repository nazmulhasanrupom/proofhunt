export const BASE = import.meta.env.VITE_API_URL || "/api";

const KEY = "accessPassword";
export const getPassword = () => { try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; } };
export const setPassword = (v: string) => { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch { /* private mode */ } };

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body) headers["Content-Type"] = "application/json";
  const pw = getPassword();
  if (pw) headers["Authorization"] = `Bearer ${pw}`;
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
