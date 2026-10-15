import { useEffect, useState, useCallback } from "react";
import {
  getHealth,
  getMetrics,
  getAtRisk,
  getTickets,
  createTicket,
  resolveTicket,
} from "./api.js";

const SEV_CLASS = { P1: "sev-p1", P2: "sev-p2", P3: "sev-p3", P4: "sev-p4" };

function Stat({ label, value, warn }) {
  return (
    <div className={`stat ${warn ? "stat-warn" : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export default function App() {
  const [metrics, setMetrics] = useState(null);
  const [atRisk, setAtRisk] = useState([]);
  const [tickets, setTickets] = useState([]);
  const [subject, setSubject] = useState("");
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  // The API reports read-only mode (public demo); hide write controls then.
  const [readOnly, setReadOnly] = useState(false);

  useEffect(() => {
    getHealth().then((h) => setReadOnly(Boolean(h.read_only))).catch(() => {});
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [m, ar, ts] = await Promise.all([
        getMetrics(),
        getAtRisk(),
        getTickets(),
      ]);
      setMetrics(m);
      setAtRisk(ar);
      setTickets(ts);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000); // poll every 10s
    return () => clearInterval(id);
  }, [refresh]);

  async function onCreate(e) {
    e.preventDefault();
    if (!subject.trim()) return;
    try {
      await createTicket(subject.trim());
      setSubject("");
      setActionError(null);
    } catch (err) {
      setActionError(err.message); // e.g. 429 rate limit, 403 read-only
    }
    refresh();
  }

  async function onResolve(id) {
    try {
      await resolveTicket(id);
      setActionError(null);
    } catch (err) {
      setActionError(err.message);
    }
    refresh();
  }

  return (
    <div className="wrap">
      <header>
        <h1>Escalate</h1>
        <span className="sub">support queue · SLA early warning</span>
      </header>

      {error && <div className="error">API unreachable: {error}</div>}
      {actionError && <div className="error">Action failed: {actionError}</div>}
      {readOnly && <div className="readonly">Read-only demo: creating and resolving tickets is disabled.</div>}

      {metrics && (
        <section className="stats">
          <Stat label="open" value={metrics.open} />
          <Stat label="at risk" value={metrics.at_risk} warn={metrics.at_risk > 0} />
          <Stat label="breached" value={metrics.breached_open} warn={metrics.breached_open > 0} />
          <Stat label="breach rate" value={`${Math.round(metrics.breach_rate * 100)}%`} />
          <Stat label="resolved" value={metrics.resolved} />
          <Stat label="MTTR (min)" value={metrics.mttr_minutes ?? "—"} />
        </section>
      )}

      {!readOnly && (
        <form className="new" onSubmit={onCreate}>
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="New ticket subject (auto-classified on submit)…"
          />
          <button type="submit">Add</button>
        </form>
      )}

      <section>
        <h2>At risk ({atRisk.length})</h2>
        {atRisk.length === 0 ? (
          <p className="empty">Nothing breaching soon. 🎉</p>
        ) : (
          <ul className="risk">
            {atRisk.map((t) => (
              <li key={t.id}>
                <span className={`badge ${SEV_CLASS[t.severity]}`}>{t.severity}</span>
                <span className="risk-subj">{t.subject}</span>
                <span className="risk-mtb">breach in {t.minutes_to_breach}m</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2>Queue ({tickets.length})</h2>
        <table>
          <thead>
            <tr>
              <th>Sev</th><th>Category</th><th>Subject</th><th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {tickets.map((t) => (
              <tr key={t.id} className={t.resolved ? "row-resolved" : ""}>
                <td><span className={`badge ${SEV_CLASS[t.severity]}`}>{t.severity}</span></td>
                <td>{t.category}</td>
                <td>{t.subject}</td>
                <td>{t.resolved ? "resolved" : "open"}</td>
                <td>
                  {!t.resolved && !readOnly && (
                    <button className="link" onClick={() => onResolve(t.id)}>resolve</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
