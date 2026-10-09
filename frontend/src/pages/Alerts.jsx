import { useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { Badge, Banner, Empty, PageHead, SEVERITY_TONE } from "../components/ui";
import { dateTime } from "../format";

export default function Alerts() {
  const [rows, setRows] = useState(null);
  const [unreadOnly, setUnreadOnly] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.get("/alerts", { params: { unread_only: unreadOnly } }).then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e)));
  useEffect(() => { load(); }, [unreadOnly]);

  const refresh = async () => {
    setBusy(true); setError("");
    try { await api.post("/alerts/refresh"); await load(); } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };
  const markRead = async (id) => {
    try { await api.put(`/alerts/${id}/read`); load(); } catch (err) { setError(errorMessage(err)); }
  };

  return (
    <>
      <PageHead title="Alerts" subtitle="Low stock, out of stock, and expiry warnings">
        <label className="check"><input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />Unread only</label>
        <button className="btn" onClick={refresh} disabled={busy}>{busy ? "Checking…" : "Refresh alerts"}</button>
      </PageHead>
      <Banner onClose={() => setError("")}>{error}</Banner>
      <div className="panel">
        {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? <Empty>{unreadOnly ? "No unread alerts. Stock looks healthy." : "No alerts."}</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Severity</th><th>Type</th><th>Message</th><th>Raised</th><th /></tr></thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id} style={a.is_read ? { opacity: .55 } : null}>
                    <td><Badge tone={SEVERITY_TONE[a.severity]}>{a.severity}</Badge></td>
                    <td>{a.alert_type.replace(/_/g, " ").toLowerCase()}</td><td>{a.message}</td><td>{dateTime(a.created_at)}</td>
                    <td>{!a.is_read && <button className="btn secondary small" onClick={() => markRead(a.id)}>Mark as read</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
