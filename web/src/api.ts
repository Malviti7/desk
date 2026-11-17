import { useCallback, useEffect, useState } from "react";

const TOKEN_KEY = "desk_token";

function headers(): HeadersInit {
  let t: string | null = null;
  try { t = localStorage.getItem(TOKEN_KEY); } catch { /* storage unavailable */ }
  return t ? { Authorization: `Bearer ${t}`, "Content-Type": "application/json" } : { "Content-Type": "application/json" };
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { ...init, headers: { ...headers(), ...(init?.headers || {}) } });
  if (r.status === 401) {
    const t = window.prompt("Desk API token");
    if (t) { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* ignore */ } return api(path, init); }
  }
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.headers.get("content-type")?.includes("json") ? r.json() : (r.text() as any);
}

/** Fetch + refresh every `refreshSec` seconds. */
export function useApi<T = any>(path: string, refreshSec = 60) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(() => {
    api<T>(path).then((d) => { setData(d); setError(null); }).catch((e) => setError(String(e))).finally(() => setLoading(false));
  }, [path]);
  useEffect(() => {
    load();
    const id = window.setInterval(load, refreshSec * 1000);
    return () => window.clearInterval(id);
  }, [load, refreshSec]);
  return { data, error, loading, reload: load };
}
