import { useEffect, useState } from "react";
import { api, ApiError, getToken, setToken } from "./api.js";
import { ROLE_LABELS } from "./labels.js";
import Login from "./components/Login.jsx";
import Chat from "./components/Chat.jsx";
import Dashboard from "./components/Dashboard.jsx";
import AuditViewer from "./components/AuditViewer.jsx";

// Which screens a role gets. This only shapes the menu; the API enforces the same rules (403 otherwise).
function viewsFor(user) {
  if (!user.internal) return [{ id: "chat", label: "Support chat" }];
  const views = [{ id: "chat", label: "Staff copilot" }];
  if (user.role === "ops_manager") views.push({ id: "dashboard", label: "Ops dashboard" });
  views.push({ id: "audit", label: "Audit trail" });
  return views;
}

export default function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(Boolean(getToken()));
  const [view, setView] = useState("chat");
  const [auditFilter, setAuditFilter] = useState({});

  useEffect(() => {
    if (!getToken()) return;
    api.me().then(setUser).catch(() => setToken(null)).finally(() => setChecking(false));
  }, []);

  const signOut = () => {
    setToken(null);
    setUser(null);
    setView("chat");
  };

  // Any 401 (expired session) sends the user back to the login screen.
  const onApiError = (err) => {
    if (err instanceof ApiError && err.status === 401) signOut();
  };

  if (checking) return <div className="center muted">Loading…</div>;
  if (!user) return <Login onLogin={(u) => setUser(u)} />;

  const openAudit = (conversationId) => {
    setAuditFilter({ conversation_id: conversationId });
    setView("audit");
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Ascent <span>{user.internal ? "Internal Support" : "Customer Support"}</span>
        </div>
        <nav>
          {viewsFor(user).map((v) => (
            <button key={v.id} className={view === v.id ? "tab active" : "tab"}
                    onClick={() => { if (v.id === "audit") setAuditFilter({}); setView(v.id); }}>
              {v.label}
            </button>
          ))}
        </nav>
        <div className="who">
          <strong>{user.name}</strong>
          <span className="pill">{ROLE_LABELS[user.role]}</span>
          {user.account_id && <span className="pill light">{user.account_id}</span>}
          <button className="link" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <main>
        {/* Chat stays mounted so the conversation survives switching tabs. */}
        <div hidden={view !== "chat"}>
          <Chat user={user} onApiError={onApiError} onOpenAudit={user.internal ? openAudit : null} />
        </div>
        {view === "dashboard" && <Dashboard onApiError={onApiError} />}
        {view === "audit" && <AuditViewer initialFilter={auditFilter} onApiError={onApiError} />}
      </main>
    </div>
  );
}
