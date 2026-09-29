# Rino Event Bus

Process-local EventEmitter2-based event bus for Rino integrations. It has no
broker or persistence layer; cross-process producers should forward their
events through a future adapter.

イベント追加・既存コンポーネントの段階移行は、[Event Bus ガイド](../docs/architecture/Rino_EventBus.md)を参照してください。

```ts
import { eventBus, EventLogger } from "@rino/event-bus";

new EventLogger().attach(eventBus); // observe every event
eventBus.on("vision.*", (event) => console.log(event.payload));
eventBus.emit("vision.screen_changed", {
  source: "screen-vision",
  payload: { windowTitle: "Example Game" },
});

// A Python Agent Service is a separate process. Attach the boundary adapter
// once in the Node runtime; producers remain unaware of Agent's HTTP API.
// new AgentEventBridge({ endpoint: "http://127.0.0.1:8787/events", token }).attach(eventBus);
```

Every listener receives `{ id, type, timestamp, source, priority?, payload }`.
`id` and `timestamp` are created when omitted. Available facade methods are
`emit`, `emitAsync`, `on`, `once`, `off`, and `onAny` (plus `offAny` for cleanup).
