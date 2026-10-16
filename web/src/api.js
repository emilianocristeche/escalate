// API base: set VITE_API_URL at build time (Vercel) to your deployed API.
// Falls back to localhost for `npm run dev`.
const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

// A request that hangs this long is abandoned so the dashboard can retry: on
// Render's free tier the first request after an idle period waits while the
// instance boots (~30–60 s), and occasionally fails instead of answering.
const REQUEST_TIMEOUT_MS = 20000;

async function req(path, opts = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
  try {
    const r = await fetch(`${BASE}${path}`, { ...opts, signal: ctrl.signal });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  } catch (e) {
    if (e.name === "AbortError") throw new Error("request timed out");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export const getHealth = () => req("/health");
export const getMetrics = () => req("/metrics");
export const getAtRisk = () => req("/tickets/at-risk");
export const getTickets = () => req("/tickets?limit=100");
export const createTicket = (subject) =>
  req("/tickets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subject }),
  });
export const resolveTicket = (id) =>
  req(`/tickets/${id}/resolve`, { method: "POST" });
