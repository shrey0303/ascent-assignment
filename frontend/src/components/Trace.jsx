import { useState } from "react";

// Live plan-and-execute trace: each step's plan, then the tool calls it made and what came back.

function status(output) {
  if (!output) return ["running", "running…"];
  if (output.error === "access_denied") return ["denied", "access denied"];
  if (output.restricted) return ["denied", "restricted"];
  if (output.error) return ["error", output.error];
  if (output.confirmation_required) return ["ok", "preview created"];
  return ["ok", "ok"];
}

function ToolCall({ call, result }) {
  const [open, setOpen] = useState(false);
  const [kind, label] = status(result?.output);
  return (
    <div className="tool">
      <button className="tool-head" onClick={() => setOpen(!open)}>
        <span className={`dot ${kind}`} />
        <code>{call.name}</code>
        <span className={`tag ${kind}`}>{label}</span>
        {result?.output?.injection_warning && <span className="tag warn">injection text ignored</span>}
        <span className="muted chevron">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="tool-body">
          <div className="muted small">Input</div>
          <pre>{JSON.stringify(call.args, null, 2)}</pre>
          {result && (
            <>
              <div className="muted small">Output</div>
              <pre>{JSON.stringify(result.output, null, 2)}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function Trace({ events, running }) {
  const [open, setOpen] = useState(true);
  if (!events.length && !running) return null;

  const results = Object.fromEntries(events.filter((e) => e.type === "tool_result").map((e) => [e.id, e]));
  const steps = [];
  for (const e of events) {
    if (e.type !== "plan" && e.type !== "tool_call") continue;
    let step = steps.find((s) => s.step === e.step);
    if (!step) steps.push((step = { step: e.step, plan: null, calls: [] }));
    if (e.type === "plan") step.plan = e.text;
    else step.calls.push(e);
  }
  const callCount = steps.reduce((n, s) => n + s.calls.length, 0);

  return (
    <div className="trace">
      <button className="trace-head" onClick={() => setOpen(!open)}>
        <span>{running ? <span className="spinner" /> : "✓"}</span>
        <strong>Plan &amp; tool trace</strong>
        <span className="muted">
          {steps.length} step{steps.length === 1 ? "" : "s"} · {callCount} tool call{callCount === 1 ? "" : "s"}
        </span>
        <span className="muted chevron">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <ol className="steps">
          {steps.map((s) => (
            <li key={s.step}>
              {s.plan && <div className="plan">{s.plan}</div>}
              {s.calls.map((c) => <ToolCall key={c.id} call={c} result={results[c.id]} />)}
            </li>
          ))}
          {running && <li className="muted">Thinking…</li>}
        </ol>
      )}
    </div>
  );
}
