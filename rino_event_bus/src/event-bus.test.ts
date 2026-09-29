import assert from "node:assert/strict";
import test from "node:test";
import { ContextStateAggregator, createEventBus, EventLogger, type RinoEvent } from "./index";

test("normalizes envelopes and dispatches wildcard subscribers", () => {
  const bus = createEventBus();
  const received: RinoEvent[] = [];
  bus.on("vision.*", (event) => received.push(event));

  bus.emit("vision.screen_changed", { source: "screen-vision", payload: { windowId: 42 } });

  assert.equal(received.length, 1);
  assert.equal(received[0].type, "vision.screen_changed");
  assert.equal(received[0].source, "screen-vision");
  assert.equal(typeof received[0].id, "string");
  assert.equal(typeof received[0].timestamp, "number");
});

test("supports once, off, emitAsync, and all-event logging", async () => {
  const bus = createEventBus();
  let calls = 0;
  const listener = () => { calls += 1; return "done"; };
  bus.once("game.started", listener);
  bus.emit("game.started", { source: "game-detector", payload: {} });
  bus.emit("game.started", { source: "game-detector", payload: {} });
  bus.on("game.stopped", listener).off("game.stopped", listener);
  bus.emit("game.stopped", { source: "game-detector", payload: {} });
  assert.equal(calls, 1);

  bus.on("agent.action_completed", async () => "completed");
  assert.deepEqual(await bus.emitAsync("agent.action_completed", { source: "agent", payload: {} }), ["completed"]);

  const logged: RinoEvent[] = [];
  new EventLogger({ info: (_message, event) => logged.push(event) }).attach(bus);
  bus.emit("pc.active_window_changed", { source: "windows", payload: { title: "Game" } });
  assert.equal(logged[0].type, "pc.active_window_changed");
});

test("isolates failing consumers and emits context changes only once per value", async () => {
  const errors: unknown[] = [];
  const bus = createEventBus({ onListenerError: (error) => errors.push(error) });
  let delivered = 0;
  bus.on("vision.screen_changed", () => { throw new Error("consumer failed"); });
  bus.on("vision.screen_changed", () => { delivered += 1; });
  await bus.emitAsync("vision.screen_changed", { source: "vision", payload: {} });
  assert.equal(delivered, 1);
  assert.equal(errors.length, 1);

  new ContextStateAggregator().attach(bus);
  const updates: RinoEvent[] = [];
  bus.on("context.updated", (event) => updates.push(event));
  bus.emit("pc.active_window_changed", { source: "windows", payload: { processName: "game.exe" } });
  bus.emit("pc.active_window_changed", { source: "windows", payload: { processName: "game.exe" } });
  assert.equal(updates.length, 1);
});
