export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const CSRF_COOKIE = "csrf_token";

let serverCsrf: string | null = null;

/** Clears CSRF token cached from `/auth/bootstrap` (call after logout). */
export function clearServerCsrf(): void {
  serverCsrf = null;
}

/**
 * Ensures a browser session (guest if needed) and returns a CSRF token for mutating API calls.
 */
export async function refreshCsrfFromServer(): Promise<void> {
  const r = await fetch(`${API_BASE_URL}/auth/bootstrap`, {
    method: "POST",
    credentials: "include",
  });
  if (r.ok) {
    const j = (await r.json()) as { csrf_token?: string };
    serverCsrf = j.csrf_token ?? null;
  } else {
    serverCsrf = null;
  }
}

function getCookie(name: string) {
  if (typeof document === "undefined") return null;
  const parts = document.cookie.split(";").map((p) => p.trim());
  for (const p of parts) {
    if (!p) continue;
    const eq = p.indexOf("=");
    if (eq === -1) continue;
    const k = p.slice(0, eq).trim();
    if (k !== name) continue;
    return decodeURIComponent(p.slice(eq + 1));
  }
  return null;
}

export function csrfHeaders(): Record<string, string> {
  const t = serverCsrf ?? getCookie(CSRF_COOKIE);
  return t ? { "X-CSRF-Token": t } : {};
}
