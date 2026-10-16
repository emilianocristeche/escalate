// API base: set VITE_API_URL at build time (Vercel) to your deployed API.
// Falls back to localhost for `npm run dev`.
const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

// A request that hangs this long is abandoned so the dashboard can retry: on
// Render's free tier the first request after an idle period waits while the
// instance boots (~30–60 s), and occasionally fails instead of answering.
const REQUEST_TIMEOUT_MS = 20000;

// The dashboard never calls /health: some browser blockers drop any request
// whose path contains "health", which would leave it stuck on "Waking up".
// Wake-up is detected from the first data response (/tickets), and read-only
// mode from the X-Read-Only header the API adds to every response.
async function send(path, opts = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
  try {
    const r = await fetch(`${BASE}${path}`, { ...opts, signal: ctrl.signal });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return { body: await r.json(), headers: r.headers };
  } catch (e) {
    if (e.name === "AbortError") throw new Error("request timed out");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

async function req(path, opts) {
  return (await send(path, opts)).body;
}

// Tickets plus whether the API is read-only (null if the header is missing).
export async function getTickets() {
  const { body, headers } = await send("/tickets?limit=100");
  const ro = headers.get("X-Read-Only");
  return { tickets: body, readOnly: ro === null ? null : ro === "true" };
}
export const getMetrics = () => req("/metrics");
export const getAtRisk = () => req("/tickets/at-risk");
export const createTicket = (subject) =>
  req("/tickets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subject }),
  });
export const resolveTicket = (id) =>
  req(`/tickets/${id}/resolve`, { method: "POST" });
