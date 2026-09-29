import { connect, type NatsConnection } from "nats";
import type { EventBus, RinoEvent } from "./event-bus";

/**
 * One-way adapter from the process-local SwitchBot bus to JetStream.
 * It deliberately never subscribes to NATS, so a bridged event cannot loop
 * back into the local bus. NATS reconnects automatically after a disconnect.
 */
export interface SwitchBotNatsBridgeOptions {
  url?: string;
  name?: string;
  onError?: (error: unknown, event?: RinoEvent) => void;
}

const SUBJECTS: Record<string, string> = {
  "switchbot.temperature_changed": "switchbot.temperature_changed.v1",
  "switchbot.humidity_changed": "switchbot.humidity_changed.v1",
  "switchbot.co2_changed": "switchbot.co2_changed.v1",
  "switchbot.device_state_changed": "switchbot.device_state_changed.v1",
};

export class SwitchBotNatsBridge {
  private connection?: NatsConnection;
  private bus?: EventBus;
  private readonly listener = (event: RinoEvent) => void this.forward(event);

  constructor(private readonly options: SwitchBotNatsBridgeOptions = {}) {}

  async connect(): Promise<this> {
    if (this.connection) return this;
    try {
      this.connection = await connect({ servers: this.options.url ?? process.env.RINO_LIFE_NATS_URL ?? "nats://127.0.0.1:54222", name: this.options.name ?? "rino-switchbot-event-bridge-v1" });
      (async () => {
        for await (const status of this.connection!.status()) {
          if (status.type === "disconnect" || status.type === "error") this.options.onError?.(new Error(`NATS ${status.type}: ${status.data}`));
        }
      })().catch((error) => this.options.onError?.(error));
      return this;
    } catch (error) {
      this.options.onError?.(error);
      throw error;
    }
  }

  attach(bus: EventBus): this {
    this.bus = bus;
    for (const type of Object.keys(SUBJECTS)) bus.on(type, this.listener);
    return this;
  }

  detach(): this {
    if (this.bus) for (const type of Object.keys(SUBJECTS)) this.bus.off(type, this.listener);
    this.bus = undefined;
    return this;
  }

  async close(): Promise<void> { this.detach(); await this.connection?.drain(); this.connection = undefined; }

  private async forward(event: RinoEvent): Promise<void> {
    const subject = SUBJECTS[event.type];
    // Events emitted by this adapter are never accepted as inputs.
    if (!subject || event.source === "rino-switchbot-nats-bridge") return;
    try {
      await this.connect();
      await this.connection!.jetstream().publish(subject, JSON.stringify({
        id: event.id, type: subject, occurred_at: new Date(event.timestamp).toISOString(),
        source: event.source, confidence: 1, payload: payloadFor(event),
      }));
    } catch (error) { this.options.onError?.(error, event); }
  }
}

function payloadFor(event: RinoEvent): Record<string, unknown> {
  const input = event.payload as Record<string, unknown>;
  const observed_at = typeof input.observedAt === "number" ? new Date(input.observedAt).toISOString() : new Date(event.timestamp).toISOString();
  switch (event.type) {
    case "switchbot.temperature_changed": return { device_id: input.deviceId, temperature_c: input.temperatureC, observed_at };
    case "switchbot.humidity_changed": return { device_id: input.deviceId, humidity_percent: input.humidityPercent, observed_at };
    case "switchbot.co2_changed": return { device_id: input.deviceId, co2_ppm: input.co2Ppm, observed_at };
    case "switchbot.device_state_changed": return { device_id: input.deviceId, device_type: input.deviceType, state: input.state, observed_at };
    default: throw new Error(`Unsupported SwitchBot event: ${event.type}`);
  }
}
