// Run with: npm test (Node's built-in test runner, no extra dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { takeEvents } from "../src/api.js";

test("complete events are parsed and the unfinished tail is kept", () => {
  const [events, rest] = takeEvents('data: {"type": "start"}\n\ndata: {"type": "pl');
  assert.deepEqual(events, [{ type: "start" }]);
  assert.equal(rest, 'data: {"type": "pl');
});

test("an event split across chunks is parsed once both parts arrive", () => {
  let [events, rest] = takeEvents('data: {"type": "answer", "text": "a\\n');
  assert.deepEqual(events, []);
  [events, rest] = takeEvents(rest + 'b"}\n\n');
  assert.deepEqual(events, [{ type: "answer", text: "a\nb" }]);
  assert.equal(rest, "");
});
