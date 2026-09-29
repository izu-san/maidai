import type { EventBus, RinoEvent } from "./event-bus";

export interface AgentEventBridgeOptions {
  endpoint: string;
  token: string;
  fetch?: typeof globalThis.fetch;
  onError?: (error: unknown, event: RinoEvent) => void;
}

/** Translates Bus envelopes to the Python Agent Service's existing `/events` API. */
export class AgentEventBridge {
  private readonly listener = (event: RinoEvent) => void this.forward(event);
  private attached = false;

  constructor(private readonly options: AgentEventBridgeOptions) {}

  attach(bus: EventBus): this {
    if (this.attached) return this;
    for (const domain of ["vision.*", "game.*", "pc.*", "switchbot.*", "system.*"]) bus.on(domain, this.listener);
    this.attached = true;
    return this;
  }

  detach(bus: EventBus): this {
    if (!this.attached) return this;
    for (const domain of ["vision.*", "game.*", "pc.*", "switchbot.*", "system.*"]) bus.off(domain, this.listener);
    this.attached = false;
    return this;
  }

  private async forward(event: RinoEvent): Promise<void> {
    if (event.source === "rino-agent" || event.source === "rino-agent-bridge") return;
    try {
      const payload = JSON.stringify(event.payload);
      if (new TextEncoder().encode(payload).byteLength > 16_384) throw new Error("Event payload exceeds Agent gateway limit.");
      const response = await (this.options.fetch ?? globalThis.fetch)(this.options.endpoint, {
        method: "POST",
        headers: { "content-type": "application/json", authorization: `Bearer ${this.options.token}` },
        body: JSON.stringify({ type: event.type, source: event.source, timestamp: new Date(event.timestamp).toISOString(), data: event.payload }),
      });
      if (!response.ok) throw new Error(`Agent event gateway returned HTTP ${response.status}.`);
    } catch (error) {
      // A disconnected Agent Service must never break a producer.
      this.options.onError?.(error, event);
    }
  }
}
