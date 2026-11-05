import { useEffect, useRef, useState } from "react";
import { streamChat } from "../api.js";
import Trace from "./Trace.jsx";
import TrustPanel from "./TrustPanel.jsx";
import ActionPreview from "./ActionPreview.jsx";
import RichText from "./RichText.jsx";

// One chat screen for both chatbots. Which bot the user gets (customer vs staff prompt, tool list)
// is decided by the server from the session's role, never by the browser.
export default function Chat({ user, onApiError, onOpenAudit }) {
  const [turns, setTurns] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef(null);

  // Braces matter: newer browsers return a Promise from scrollIntoView, which React would call as a cleanup.
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const updateLast = (fn) => setTurns((all) => [...all.slice(0, -1), fn(all[all.length - 1])]);

  const send = async (e) => {
    e.preventDefault();
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);
    setTurns((all) => [...all, { question: message, events: [], previews: [], answer: null, error: null }]);
    let answered = false;
    try {
      await streamChat(message, conversationId, (event) => {
        answered ||= event.type === "answer";
        if (event.type === "start") setConversationId(event.conversation_id);
        else if (event.type === "answer") updateLast((t) => ({ ...t, answer: event }));
        else if (event.type === "action_preview") updateLast((t) => ({ ...t, previews: [...t.previews, event] }));
        else if (event.type === "error") updateLast((t) => ({ ...t, error: event.message }));
        else updateLast((t) => ({ ...t, events: [...t.events, event] }));
      });
      if (!answered) updateLast((t) => ({ ...t, error: "The connection closed before an answer arrived. Please try again." }));
    } catch (err) {
      onApiError(err);
      updateLast((t) => ({ ...t, error: err.message }));
    } finally {
      setBusy(false);
    }
  };

  const newChat = () => {
    setTurns([]);
    setConversationId(null);
  };

  return (
    <div className="chat">
      <div className="chat-head">
        <div>
          <h2>{user.internal ? "Staff copilot" : "Support assistant"}</h2>
          <p className="muted">
            {user.internal
              ? "Internal assistant: policies, contracts, orders, tickets, SLA and escalations. Every tool call is shown and audited."
              : "Ask about your orders, tickets, cancellations or service credits. You only see your own account."}
          </p>
        </div>
        <div className="row">
          {conversationId && onOpenAudit && (
            <button className="secondary" onClick={() => onOpenAudit(conversationId)}>Audit this chat</button>
          )}
          <button className="secondary" onClick={newChat} disabled={busy}>New chat</button>
        </div>
      </div>

      <div className="messages">
        {turns.length === 0 && <div className="empty muted">Start by asking a question below.</div>}
        {turns.map((turn, i) => (
          <div key={i} className="turn">
            <div className="bubble user">{turn.question}</div>
            <div className="bubble bot">
              <Trace events={turn.events} running={busy && i === turns.length - 1 && !turn.answer} />
              {turn.previews.map((p) => (
                <ActionPreview key={p.preview_id} preview={p} onApiError={onApiError} />
              ))}
              {turn.error && <div className="error">{turn.error}</div>}
              {turn.answer && (
                <>
                  <RichText text={turn.answer.text} />
                  <TrustPanel answer={turn.answer} />
                </>
              )}
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <form className="composer" onSubmit={send}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) send(e);
          }}
          placeholder="Type your question… (Enter to send, Shift+Enter for a new line)"
          rows={2}
          maxLength={4000}
        />
        <button className="primary" disabled={busy || !input.trim()}>{busy ? "Working…" : "Send"}</button>
      </form>
    </div>
  );
}
