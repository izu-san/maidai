import type { AnyEventListener, EventBus, RinoEvent } from "./event-bus";

export interface EventLogSink {
  info(message: string, event: RinoEvent): void;
}

/** Observes all bus events without modifying their delivery. */
export class EventLogger {
  private readonly listener: AnyEventListener;

  constructor(private readonly sink: EventLogSink = console) {
    this.listener = (event) => this.sink.info(`[event] ${event.type}`, event);
  }

  attach(bus: EventBus): this {
    bus.onAny(this.listener);
    return this;
  }

  detach(bus: EventBus): this {
    bus.offAny(this.listener);
    return this;
  }
}
