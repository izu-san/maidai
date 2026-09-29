"""Idempotently provision Phase 0 JetStream streams and a durable pull consumer."""
from __future__ import annotations

import asyncio
import os

import nats
from nats.js.api import ConsumerConfig, DeliverPolicy, RetentionPolicy, StorageType, StreamConfig

STREAMS = (
    StreamConfig(name="RINO_LIFE", subjects=["life.>"], storage=StorageType.FILE, retention=RetentionPolicy.LIMITS, max_age=365 * 24 * 60 * 60),
    StreamConfig(name="RINO_DEVICE", subjects=["switchbot.>", "pc.>", "vision.>", "mqtt.>", "home_assistant.>", "calendar.>"], storage=StorageType.FILE, retention=RetentionPolicy.LIMITS, max_age=90 * 24 * 60 * 60),
    StreamConfig(name="RINO_SYSTEM", subjects=["system.>", "agent.>"], storage=StorageType.FILE, retention=RetentionPolicy.LIMITS, max_age=90 * 24 * 60 * 60),
)
CONSUMER = ConsumerConfig(durable_name="life-phase0-contract-checker-v1", filter_subject="life.>", ack_policy="explicit", ack_wait=30, max_deliver=5, deliver_policy=DeliverPolicy.ALL)
ENVIRONMENT_CONSUMER = ConsumerConfig(durable_name="life-environment-state-v1", filter_subject="switchbot.>", ack_policy="explicit", ack_wait=30, max_deliver=5, deliver_policy=DeliverPolicy.ALL)
NOTIFICATION_CONSUMER = ConsumerConfig(durable_name="life-notification-router-v1", filter_subject="life.consumable.low.v1", ack_policy="explicit", ack_wait=30, max_deliver=5, deliver_policy=DeliverPolicy.ALL)
PC_NOTIFICATION_CONSUMER = ConsumerConfig(durable_name="life-notification-pc-v1", filter_subject="pc.>", ack_policy="explicit", ack_wait=30, max_deliver=5, deliver_policy=DeliverPolicy.ALL)
SWITCHBOT_NOTIFICATION_CONSUMER = ConsumerConfig(durable_name="life-notification-switchbot-v1", filter_subject="switchbot.>", ack_policy="explicit", ack_wait=30, max_deliver=5, deliver_policy=DeliverPolicy.NEW)
PC_CONSUMER = ConsumerConfig(durable_name="life-pc-state-v1", filter_subject="pc.>", ack_policy="explicit", ack_wait=30, max_deliver=5, deliver_policy=DeliverPolicy.ALL)
VISION_CONSUMER = ConsumerConfig(durable_name="life-vision-candidates-v1", filter_subject="vision.>", ack_policy="explicit", ack_wait=30, max_deliver=5, deliver_policy=DeliverPolicy.ALL)


async def ensure_jetstream(url: str | None = None) -> None:
    connection = await nats.connect(url or os.environ.get("RINO_LIFE_NATS_URL", "nats://127.0.0.1:54222"))
    try:
        js = connection.jetstream()
        for config in STREAMS:
            try:
                await js.add_stream(config)
            except Exception as error:
                if "already in use" not in str(error).lower():
                    raise
                await js.update_stream(config)
        for stream, consumer in (("RINO_LIFE", CONSUMER), ("RINO_LIFE", NOTIFICATION_CONSUMER), ("RINO_DEVICE", ENVIRONMENT_CONSUMER), ("RINO_DEVICE", PC_CONSUMER), ("RINO_DEVICE", PC_NOTIFICATION_CONSUMER), ("RINO_DEVICE", SWITCHBOT_NOTIFICATION_CONSUMER), ("RINO_DEVICE", VISION_CONSUMER)):
            try:
                await js.add_consumer(stream, consumer)
            except Exception as error:
                if "already in use" not in str(error).lower():
                    raise
                await js.update_consumer(stream, consumer)
    finally:
        await connection.drain()


if __name__ == "__main__":
    asyncio.run(ensure_jetstream())
