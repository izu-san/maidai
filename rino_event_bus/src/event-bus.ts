import { EventEmitter2 } from "eventemitter2";
import { randomUUID } from "node:crypto";

/** Events reserved for the Rino platform. New dotted event names may be added safely. */
export interface RinoEventPayloads {
  "vision.screen_changed": { windowTitle?: string; captureId?: string; changedRegions?: number; capturedAt?: number };
  "vision.game_detected": { gameId?: string; gameName?: string; confidence?: number };
  "vision.error_detected": { code: string; message: string; confidence?: number };
  "game.started": { gameId: string; sessionId?: string };
  "game.stopped": { gameId?: string; sessionId?: string };
  "game.changed": { previousGameId?: string; gameId?: string; sessionId?: string };
  "pc.active_window_changed": { processName?: string; windowTitle?: string };
  "pc.idle_started": { idleSeconds?: number };
  "pc.idle_ended": { idleSeconds?: number };
  "switchbot.temperature_changed": { deviceId?: string; temperatureC: number; observedAt?: number };
  "switchbot.humidity_changed": { deviceId?: string; humidityPercent: number; observedAt?: number };
  "switchbot.co2_changed": { deviceId?: string; co2Ppm: number; observedAt?: number };
  "switchbot.device_state_changed": { deviceId: string; deviceType?: string; state: Record<string, unknown>; observedAt?: number };
  "switchbot.light_changed": { deviceId?: string; lightLevel: number; observedAt?: number };
  "memory.created": { memoryId?: string; summary?: string };
  "memory.updated": { memoryId?: string; summary?: string };
  "context.updated": { changedSources: string[]; reason?: string };
  "agent.action_started": { actionId: string; sessionId?: string; action?: string };
  "agent.action_completed": { actionId: string; sessionId?: string; result?: string; verification?: string };
  "agent.action_failed": { actionId: string; sessionId?: string; code: string; retryable?: boolean };
  "agent.speech_requested": { text: string; sessionId?: string };
  "system.error": { code: string; message: string };
}

export type RinoEventType = keyof RinoEventPayloads | (string & {});

/** Canonical envelope passed to every Event Bus listener. */
export interface RinoEvent<TPayload = unknown> {
  id: string;
  type: RinoEventType;
  timestamp: number;
  source: string;
  priority?: number;
  payload: TPayload;
}

/** Input accepted by emit methods; the bus owns id, type, and timestamp defaults. */
export interface EventInput<TPayload = unknown> {
  id?: string;
  timestamp?: number;
  source: string;
  priority?: number;
  payload: TPayload;
}

export type EventListener<TPayload = unknown> = (event: RinoEvent<TPayload>) => unknown;
export type AnyEventListener = (event: RinoEvent) => unknown;
export type EventErrorListener = (error: unknown, event: RinoEvent) => void;

export interface EventBusOptions {
  /** Errors are isolated per listener so one consumer cannot stop other consumers. */
  onListenerError?: EventErrorListener;
}

/**
 * Thin, typed facade over EventEmitter2. Consumers never need to access the
 * emitter directly; wildcard subscriptions use EventEmitter2's `*` syntax.
 */
export class EventBus {
  private readonly emitter = new EventEmitter2({ wildcard: true, delimiter: "." });
  private readonly anyListeners = new Map<AnyEventListener, (type: string | string[], event: RinoEvent) => unknown>();
  private readonly listeners = new Map<EventListener, EventListener>();

  constructor(private readonly options: EventBusOptions = {}) {}

  emit<TType extends keyof RinoEventPayloads>(type: TType, input: EventInput<RinoEventPayloads[TType]>): boolean;
  emit(type: RinoEventType, input: EventInput): boolean;
  emit<TPayload>(type: RinoEventType, input: EventInput<TPayload>): boolean {
    return this.emitter.emit(type, this.toEvent(type, input));
  }

  emitAsync<TType extends keyof RinoEventPayloads>(type: TType, input: EventInput<RinoEventPayloads[TType]>): Promise<unknown[]>;
  emitAsync(type: RinoEventType, input: EventInput): Promise<unknown[]>;
  emitAsync<TPayload>(type: RinoEventType, input: EventInput<TPayload>): Promise<unknown[]> {
    return this.emitter.emitAsync(type, this.toEvent(type, input));
  }

  on<TType extends RinoEventType>(type: TType, listener: EventListener<TType extends keyof RinoEventPayloads ? RinoEventPayloads[TType] : unknown>): this {
    this.emitter.on(type, this.wrap(listener as EventListener));
    return this;
  }

  once<TType extends RinoEventType>(type: TType, listener: EventListener<TType extends keyof RinoEventPayloads ? RinoEventPayloads[TType] : unknown>): this {
    this.emitter.once(type, this.wrap(listener as EventListener));
    return this;
  }

  off<TType extends RinoEventType>(type: TType, listener: EventListener<TType extends keyof RinoEventPayloads ? RinoEventPayloads[TType] : unknown>): this {
    const wrapped = this.listeners.get(listener as EventListener);
    if (wrapped) {
      this.emitter.off(type, wrapped);
    }
    return this;
  }

  /** Subscribe to every event. The event type is available in event.type. */
  onAny(listener: AnyEventListener): this {
    const wrapped = (_type: string | string[], event: RinoEvent) => this.invoke(listener, event);
    this.anyListeners.set(listener, wrapped);
    this.emitter.onAny(wrapped);
    return this;
  }

  offAny(listener: AnyEventListener): this {
    const wrapped = this.anyListeners.get(listener);
    if (wrapped) {
      this.emitter.offAny(wrapped);
      this.anyListeners.delete(listener);
    }
    return this;
  }

  private wrap(listener: EventListener): EventListener {
    const existing = this.listeners.get(listener);
    if (existing) return existing;
    const wrapped: EventListener = (event) => this.invoke(listener, event);
    this.listeners.set(listener, wrapped);
    return wrapped;
  }

  private invoke(listener: EventListener | AnyEventListener, event: RinoEvent): unknown {
    try {
      const result = listener(event);
      if (result && typeof (result as Promise<unknown>).then === "function") {
        return Promise.resolve(result).catch((error) => this.reportListenerError(error, event));
      }
      return result;
    } catch (error) {
      this.reportListenerError(error, event);
      return undefined;
    }
  }

  private reportListenerError(error: unknown, event: RinoEvent): void {
    try {
      this.options.onListenerError?.(error, event);
    } catch {
      // Error reporting itself must never affect event delivery.
    }
  }

  private toEvent<TPayload>(type: RinoEventType, input: EventInput<TPayload>): RinoEvent<TPayload> {
    return {
      id: input.id ?? randomUUID(),
      type,
      timestamp: input.timestamp ?? Date.now(),
      source: input.source,
      ...(input.priority === undefined ? {} : { priority: input.priority }),
      payload: input.payload,
    };
  }
}

/** Creates a separate bus for tests, adapters, or isolated application instances. */
export const createEventBus = (options?: EventBusOptions): EventBus => new EventBus(options);

/** Default process-local Event Bus for Rino integrations. */
export const eventBus = createEventBus();
