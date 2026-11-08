import { useEffect, useState } from "react";
import { api, setToken } from "../api.js";
import { ROLE_LABELS } from "../labels.js";

// Test logins come from the server (data/users.json), so there is no user list in the UI code.
export default function Login({ onLogin }) {
  const [logins, setLogins] = useState([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.testLogins().then(setLogins).catch(() => setError("Cannot reach the server."));
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { token, user } = await api.login(username, password);
      setToken(token);
      onLogin(user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const groups = [
    ["Customers", logins.filter((l) => l.account_id)],
    ["Internal staff", logins.filter((l) => !l.account_id)],
  ];

  return (
    <div className="login">
      <form className="card login-form" onSubmit={submit}>
        <h1>Ascent Support</h1>
        <p className="muted">Sign in with a test login. All test logins share the demo password.</p>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 autoComplete="current-password" required />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>

      <div className="card logins">
        <h2>Test logins</h2>
        {groups.map(([title, items]) => (
          <div key={title}>
            <h3>{title}</h3>
            {items.map((l) => (
              <button key={l.username} type="button"
                      className={username === l.username ? "login-pick selected" : "login-pick"}
                      onClick={() => setUsername(l.username)}>
                <code>{l.username}</code>
                <span>{ROLE_LABELS[l.role]}{l.account_id ? ` · ${l.account_id}` : ""}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
