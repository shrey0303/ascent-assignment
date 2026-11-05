import { useState } from "react";

// Shown under every answer: confidence and why, sources, which source won each conflict, and
// documents that were excluded (for example the deprecated policy). All of it comes from the server.

const precedenceLine = (order = []) => order.map((t) => t.replace(/_/g, " ")).join(" > ");

// One sentence for the precedence decision of this answer, shown on every answer.
function precedenceDecision(sources, conflicts, excluded, toolCalls) {
  if (conflicts.length) return `${conflicts.length} conflict${conflicts.length === 1 ? "" : "s"} between sources, resolved by precedence (details below).`;
  const top = [...sources].filter((s) => s.precedence_rank).sort((a, b) => a.precedence_rank - b.precedence_rank)[0];
  const base = top ? `No conflict between sources; highest-precedence source used: ${top.doc_type?.replace(/_/g, " ")}.` : toolCalls ? "Based on account records only; no document precedence was needed." : "No sources were consulted for this reply.";
  return excluded.length ? `${base} ${excluded.length} outdated document${excluded.length === 1 ? "" : "s"} excluded.` : base;
}

const value = (v) =>
  v === null || v === undefined ? "—" : typeof v === "boolean" ? (v ? "yes" : "no") : typeof v === "object" ? JSON.stringify(v) : String(v);

export default function TrustPanel({ answer }) {
  const [open, setOpen] = useState(false);
  const { confidence, confidence_basis = [], sources = [], conflicts = [], excluded_sources = [], removed_citations = [],
          precedence_order = [] } = answer;
  const sorted = [...sources].sort((a, b) => (a.precedence_rank || 99) - (b.precedence_rank || 99));

  return (
    <div className="trust">
      <div className="trust-summary">
        <span className={`confidence ${confidence}`}>Confidence: {confidence}</span>
        <span className="muted">{sources.length} source{sources.length === 1 ? "" : "s"}</span>
        {conflicts.length > 0 && <span className="tag warn">{conflicts.length} conflict{conflicts.length === 1 ? "" : "s"} resolved</span>}
        {excluded_sources.length > 0 && <span className="tag">{excluded_sources.length} excluded</span>}
        {removed_citations.length > 0 && <span className="tag error">unsupported citation removed</span>}
        <span className="muted small">{(answer.latency_ms / 1000).toFixed(1)} s · {answer.tool_calls} tool call{answer.tool_calls === 1 ? "" : "s"}</span>
        <button className="link" onClick={() => setOpen(!open)}>{open ? "Hide details" : "Sources & reasoning"}</button>
      </div>
      <div className="small precedence">
        <strong>Precedence:</strong> {precedenceDecision(sources, conflicts, excluded_sources, answer.tool_calls)}
      </div>

      {open && (
        <div className="trust-body">
          <section>
            <h4>Precedence rule</h4>
            <p className="small">{precedenceLine(precedence_order)}. Deprecated or superseded documents are never used.</p>
          </section>

          <section>
            <h4>Why this confidence</h4>
            <p className="small">{confidence_basis.join(" · ")}</p>
          </section>

          {conflicts.length > 0 && (
            <section>
              <h4>Precedence decisions</h4>
              {conflicts.map((c, i) => (
                <div key={i} className="conflict">
                  <div><strong>{c.term}</strong></div>
                  <div className="win">
                    Used: <strong>{value(c.winner?.value)}</strong> from <code>{c.winner?.source?.source_id}</code>
                  </div>
                  {c.overridden.map((o, j) => (
                    <div key={j} className="lose">
                      Overridden: {value(o.value)} from <code>{o.source?.source_id}</code>
                    </div>
                  ))}
                  <div className="muted small">{c.reason}</div>
                </div>
              ))}
            </section>
          )}

          {sources.length > 0 && (
            <section>
              <h4>Sources</h4>
              {sorted.map((s) => (
                <div key={s.source_id} className="source">
                  <div>
                    <code>{s.source_id}</code>
                    {s.doc_type && <span className="tag">{s.doc_type}</span>}
                    {s.precedence_rank && <span className="muted small"> precedence rank {s.precedence_rank}</span>}
                  </div>
                  {s.doc_title && <div className="small">{s.doc_title}</div>}
                  {s.quote && <blockquote>{s.quote}</blockquote>}
                </div>
              ))}
            </section>
          )}

          {excluded_sources.length > 0 && (
            <section>
              <h4>Not used</h4>
              {excluded_sources.map((x) => (
                <div key={x.doc_id} className="small">
                  <code>{x.doc_id}</code> <span className="tag">{x.status}</span> {x.reason}
                </div>
              ))}
            </section>
          )}

          {removed_citations.length > 0 && (
            <section>
              <h4>Removed citations</h4>
              <p className="small">The model cited sources it did not consult; they were removed: {removed_citations.join(", ")}</p>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
