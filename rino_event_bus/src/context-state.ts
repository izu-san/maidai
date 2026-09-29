import type { EventBus, RinoEvent } from "./event-bus";

export interface ContextState {
  vision?: unknown;
  game?: unknown;
  pc?: unknown;
  switchbot?: unknown;
  memory?: unknown;
}

/** Latest-state context consumer. It deliberately never subscribes to context.*. */
export class ContextStateAggregator {
  private readonly state: ContextState = {};
  private readonly listener = (event: RinoEvent) => this.update(event);
  private bus?: EventBus;

  attach(bus: EventBus): this {
    this.bus = bus;
    for (const domain of ["vision.*", "game.*", "pc.*", "switchbot.*", "memory.*"]) bus.on(domain, this.listener);
    return this;
  }

  detach(bus: EventBus): this {
    for (const domain of ["vision.*", "game.*", "pc.*", "switchbot.*", "memory.*"]) bus.off(domain, this.listener);
    if (this.bus === bus) this.bus = undefined;
    return this;
  }

  snapshot(): Readonly<ContextState> { return { ...this.state }; }

  private update(event: RinoEvent): void {
    const domain = event.type.split(".")[0] as keyof ContextState;
    if (!(["vision", "game", "pc", "switchbot", "memory"] as string[]).includes(domain)) return;
    if (JSON.stringify(this.state[domain]) === JSON.stringify(event.payload)) return;
    this.state[domain] = event.payload;
    this.bus?.emit("context.updated", { source: "rino-context", payload: { changedSources: [domain], reason: event.type } });
  }
}
