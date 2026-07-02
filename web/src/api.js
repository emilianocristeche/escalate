// API base: set VITE_API_URL at build time (Vercel) to your deployed API.
// Falls back to localhost for `npm run dev`.
const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function req(path, opts) {
  const r = await fetch(`${BASE}${path}`, opts);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

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
