import { Fragment, useEffect, useState } from "react";
import { api } from "../api.js";

// Internal audit trail (every tool call, input, output, access decision, answer, login and
// confirmation) plus the executed actions. Payloads are hidden server-side for roles without
// full data permissions (Support L1).

const FILTERS = [
  ["conversation_id", "Conversation id"],
  ["user_id", "User"],
  ["tool", "Tool / name"],
];

function pretty(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

export default function AuditViewer({ initialFilter, onApiError }) {
  const [filter, setFilter] = useState({ decision: "", ...initialFilter });
  const [entries, setEntries] = useState(null);
  const [actions, setActions] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [error, setError] = useState("");

  const load = (f = filter) => {
    setError("");
    Promise.all([api.audit({ ...f, limit: 50 }), api.actions()])
      .then(([audit, acts]) => {
        setEntries(audit.entries || []);
        setActions(acts);
        if (audit.error) setError(audit.message);
      })
      .catch((err) => {
        onApiError(err);
        setError(err.message);
      });
  };
  useEffect(() => {
    const f = { decision: "", ...initialFilter };
    setFilter(f);
    load(f);
  }, [initialFilter]);

  const submit = (e) => {
    e.preventDefault();
    load();
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Audit trail</h2>
          <p className="muted">Latest 50 matching entries. Every tool call and decision is recorded on the server.</p>
        </div>
      </div>

      <form className="filters" onSubmit={submit}>
        {FILTERS.map(([key, label]) => (
          <input key={key} placeholder={label} value={filter[key] || ""}
                 onChange={(e) => setFilter({ ...filter, [key]: e.target.value.trim() })} />
        ))}
        <select value={filter.decision} onChange={(e) => setFilter({ ...filter, decision: e.target.value })}>
          <option value="">Any decision</option>
          <option value="allowed">allowed</option>
          <option value="denied">denied</option>
          <option value="error">error</option>
        </select>
        <button className="primary">Apply</button>
        <button type="button" className="secondary" onClick={() => { const f = { decision: "" }; setFilter(f); load(f); }}>
          Clear
        </button>
      </form>

      {error && <div className="error">{error}</div>}
      {!entries ? <div className="muted">Loading…</div> : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr><th>Time (UTC)</th><th>User</th><th>Role</th><th>Event</th><th>Name</th><th>Decision</th><th>Conversation</th></tr>
            </thead>
            <tbody>
              {entries.length === 0 && <tr><td colSpan={7} className="muted">No entries.</td></tr>}
              {entries.map((e) => (
                <Fragment key={e.id}>
                  <tr className="clickable" onClick={() => setOpenId(openId === e.id ? null : e.id)}>
                    <td>{e.ts.replace("T", " ").replace("+00:00", "")}</td>
                    <td>{e.user_id || "—"}</td>
                    <td>{e.role || "—"}</td>
                    <td>{e.event}</td>
                    <td><code>{e.name}</code></td>
                    <td>{e.decision && <span className={`tag ${e.decision}`}>{e.decision}</span>}</td>
                    <td><code className="small">{e.conversation_id || ""}</code></td>
                  </tr>
                  {openId === e.id && (
                    <tr className="detail">
                      <td colSpan={7}>
                        <div className="split">
                          <div><div className="muted small">Input</div><pre>{pretty(e.input)}</pre></div>
                          <div><div className="muted small">Output</div><pre>{pretty(e.output)}</pre></div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="section-title">Executed actions</h3>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr><th>Id</th><th>Action</th><th>Details</th><th>Created by</th><th>Confirmed by</th><th>Created (UTC)</th></tr>
          </thead>
          <tbody>
            {actions.length === 0 && <tr><td colSpan={6} className="muted">No actions yet.</td></tr>}
            {actions.map((a) => (
              <tr key={a.id}>
                <td><code>{a.id}</code></td>
                <td>{a.action}</td>
                <td className="small">
                  {Object.entries(a.payload).filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                </td>
                <td>{a.created_by}</td>
                <td>{a.confirmed_by.join(", ")}</td>
                <td>{a.created_at.replace("T", " ").replace("+00:00", "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
