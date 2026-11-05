import { useState } from "react";
import { api } from "../api.js";

// Preview of a state-changing action. Only this Confirm button executes it (the model has no confirm
// tool). The server checks the signed token against the exact stored payload and de-duplicates.
export default function ActionPreview({ preview, onApiError }) {
  const [state, setState] = useState("pending"); // pending | busy | done | cancelled | failed
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const confirm = async () => {
    setState("busy");
    try {
      setResult(await api.confirm(preview));
      setState("done");
    } catch (err) {
      onApiError?.(err);
      setError(err.message);
      setState("failed");
    }
  };

  const fields = Object.entries(preview.payload).filter(([, v]) => v !== null && v !== "");

  return (
    <div className={`action ${state}`}>
      <div className="action-head">
        <strong>{preview.label}</strong>
        <span className="muted small">needs your confirmation · expires {new Date(preview.expires_at).toLocaleTimeString()}</span>
      </div>
      <dl>
        {fields.map(([k, v]) => (
          <div key={k}>
            <dt>{k.replace(/_/g, " ")}</dt>
            <dd>{String(v)}</dd>
          </div>
        ))}
      </dl>
      {preview.already_exists && state === "pending" && (
        <div className="note">
          This already exists as <code>{preview.already_exists.id}</code>. Confirming will not create a duplicate.
        </div>
      )}
      {state === "pending" && (
        <div className="row">
          <button className="primary" onClick={confirm}>Confirm</button>
          <button className="secondary" onClick={() => setState("cancelled")}>Cancel</button>
        </div>
      )}
      {state === "busy" && <div className="muted">Confirming…</div>}
      {state === "cancelled" && <div className="muted">Cancelled. Nothing was done.</div>}
      {state === "failed" && <div className="error">{error}</div>}
      {state === "done" && (
        <div className="success">
          {result.created
            ? <>Done. Created <code>{result.action.id}</code>.</>
            : <>Already done as <code>{result.action.id}</code>. No duplicate was created.</>}
        </div>
      )}
    </div>
  );
}
