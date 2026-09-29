"""Small operator verification for the Phase 0 Compose stack."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import nats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rino_life.contracts import validate_event

CONSUMER = "life-phase0-contract-checker-v1"


async def main(mode: str) -> None:
    url = os.environ["RINO_LIFE_NATS_URL"]
    nc = await nats.connect(url)
    try:
        js = nc.jetstream()
        if mode == "assert-ready":
            streams = [await js.stream_info(name) for name in ("RINO_LIFE", "RINO_DEVICE", "RINO_SYSTEM")]
            consumer = await js.consumer_info("RINO_LIFE", CONSUMER)
            print(json.dumps({"streams": [item.config.name for item in streams], "consumer": consumer.config.durable_name}))
        elif mode == "publish":
            event = {"id": str(uuid4()), "type": "life.phase0.verified.v1", "occurred_at": datetime.now(timezone.utc).isoformat(), "source": "phase0-verifier", "payload": {"check": "persistence"}}
            validate_event(event["type"], event)
            await js.publish(event["type"], json.dumps(event).encode("utf-8"))
            print(event["id"])
        else:
            subscription = await js.pull_subscribe("life.>", durable=CONSUMER, stream="RINO_LIFE")
            messages = await subscription.fetch(1, timeout=5)
            for message in messages:
                validate_event(message.subject, json.loads(message.data))
                await message.ack()
                print(json.loads(message.data)["id"])
    finally:
        await nc.drain()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("assert-ready", "publish", "consume"))
    asyncio.run(main(parser.parse_args().mode))
