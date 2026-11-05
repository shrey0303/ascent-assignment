// Thin client for the FastAPI backend. The session token lives in sessionStorage (cleared with the tab).
// The UI never decides what a user may see: every request is checked again on the server.

const TOKEN_KEY = "ascent.token";

export const getToken = () => sessionStorage.getItem(TOKEN_KEY);
export const setToken = (token) =>
  token ? sessionStorage.setItem(TOKEN_KEY, token) : sessionStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (getToken()) headers.Authorization = `Bearer ${getToken()}`;
  const res = await fetch(path, { method, headers, body: body && JSON.stringify(body) });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(res.status, data.detail || `Request failed (${res.status})`);
  }
  return res;
}

const json = async (path, options) => (await request(path, options)).json();

export const api = {
  testLogins: () => json("/api/test-logins"),
  health: () => json("/api/health"),
  login: (username, password) => json("/api/login", { method: "POST", body: { username, password } }),
  me: () => json("/api/me"),
  confirm: (preview) =>
    json("/api/actions/confirm", { method: "POST", body: { preview_id: preview.preview_id, token: preview.token } }),
  actions: () => json("/api/actions"),
  alerts: () => json("/api/dashboard/alerts"),
  taskFromAlert: (alertId) => json(`/api/dashboard/alerts/${encodeURIComponent(alertId)}/task`, { method: "POST" }),
  audit: (filters) => json(`/api/audit?${new URLSearchParams(Object.entries(filters).filter(([, v]) => v))}`),
};

// Splits received text into complete server-sent events and the unfinished remainder, which may be
// cut anywhere (even inside a JSON string) and is kept until the next chunk arrives.
export function takeEvents(buffer) {
  const chunks = buffer.split("\n\n");
  const rest = chunks.pop();
  const events = chunks
    .map((chunk) => chunk.split("\n").find((l) => l.startsWith("data: ")))
    .filter(Boolean)
    .map((line) => JSON.parse(line.slice(6)));
  return [events, rest];
}

// POST /api/chat answers with server-sent events. Calls onEvent for each event as it arrives.
export async function streamChat(message, conversationId, onEvent) {
  const res = await request("/api/chat", { method: "POST", body: { message, conversation_id: conversationId } });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const [events, rest] = takeEvents(buffer + decoder.decode(value, { stream: true }));
    buffer = rest;
    events.forEach(onEvent);
  }
}
