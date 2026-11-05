import { useEffect, useState } from "react";
import { api } from "../api.js";
import ActionPreview from "./ActionPreview.jsx";

// Ops Manager dashboard. Alerts, their method and explanation come from backend/app/detect.py;
// this screen only groups and displays them. A task from an alert goes through the same
// preview -> Confirm flow as chat actions.

const kindLabel = (kind) => kind.replace(/_/g, " ");
// The snapshot is shown in the data's own time zone (as sent by the server), not the browser's.
const snapshotLabel = (iso) => `${iso.slice(0, 10)} ${iso.slice(11, 16)} (UTC${iso.slice(19) || "+00:00"})`;

function AlertCard({ alert, onApiError }) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const prepareTask = async () => {
    setBusy(true);
    setError("");
    try {
      setPreview((await api.taskFromAlert(alert.id)).preview);
    } catch (err) {
      onApiError(err);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`card alert ${alert.severity}`}>
      <div className="alert-head">
        <span className={`sev ${alert.severity}`}>{alert.severity}</span>
        <span className="tag">{kindLabel(alert.kind)}</span>
        <code className="muted small">{alert.id}</code>
      </div>
      <h3>{alert.title}</h3>
      <p>{alert.explanation}</p>
      <dl className="alert-meta">
        <div><dt>Method</dt><dd>{alert.method}</dd></div>
        <div><dt>Evidence</dt><dd>{alert.evidence.map((e) => <code key={e} className="chip">{e}</code>)}</dd></div>
        {alert.accounts.length > 0 && (
          <div><dt>Accounts</dt><dd>{alert.accounts.map((a) => <code key={a} className="chip">{a}</code>)}</dd></div>
        )}
        <div><dt>Suggested</dt><dd>{alert.suggested_action}</dd></div>
      </dl>
      {error && <div className="error">{error}</div>}
      {preview
        ? <ActionPreview preview={preview} onApiError={onApiError} />
        : <button className="secondary" onClick={prepareTask} disabled={busy}>{busy ? "Preparing…" : "Create follow-up task"}</button>}
    </div>
  );
}

export default function Dashboard({ onApiError }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [kind, setKind] = useState("all");

  const load = () => {
    setError("");
    api.alerts().then(setData).catch((err) => {
      onApiError(err);
      setError(err.message);
    });
  };
  useEffect(() => {
    load();
  }, []);

  if (error) return <div className="page"><div className="error">{error}</div></div>;
  if (!data) return <div className="page muted">Running detectors…</div>;

  const counts = data.alerts.reduce((acc, a) => ({ ...acc, [a.kind]: (acc[a.kind] || 0) + 1 }), {});
  const shown = data.alerts.filter((a) => kind === "all" || a.kind === kind);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Ops dashboard</h2>
          <p className="muted">Data snapshot ("now"): {snapshotLabel(data.now)} · {data.alerts.length} alerts</p>
        </div>
        <button className="secondary" onClick={load}>Refresh</button>
      </div>
      <div className="filters">
        <button className={kind === "all" ? "tab active" : "tab"} onClick={() => setKind("all")}>All ({data.alerts.length})</button>
        {Object.entries(counts).map(([k, n]) => (
          <button key={k} className={kind === k ? "tab active" : "tab"} onClick={() => setKind(k)}>{kindLabel(k)} ({n})</button>
        ))}
      </div>
      {shown.length === 0 && <div className="empty muted">No alerts.</div>}
      <div className="alerts">
        {shown.map((a) => <AlertCard key={a.id} alert={a} onApiError={onApiError} />)}
      </div>
    </div>
  );
}
