"""Phase 0 compatibility probe for Gemma 4 through KoboldCpp and MAF.

This program does not access any device.  It only exposes two in-process tools
and reports whether the complete function-call round trip succeeds.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from agent_framework import Agent, tool
from agent_framework.openai import OpenAIChatCompletionClient

executed_tools: list[str] = []


@tool(name="test.echo", description="Return precisely the supplied text.")
def echo(text: str) -> str:
    executed_tools.append("test.echo")
    return text


@tool(name="test.get_time", description="Get the current UTC time in ISO 8601 format.")
def get_time() -> str:
    executed_tools.append("test.get_time")
    return datetime.now(timezone.utc).isoformat()


@tool(name="test.approved_echo", description="Echo text, but only after human approval.", approval_mode="always_require")
def approved_echo(text: str) -> str:
    executed_tools.append("test.approved_echo")
    return text


async def run(prompt: str, *, base_url: str, model: str, stream: bool = False) -> str:
    executed_tools.clear()
    client = OpenAIChatCompletionClient(
        base_url=base_url,
        api_key="local-not-used",
        model=model,
    )
    agent = Agent(
        client=client,
        name="RinoCompatibilityProbe",
        instructions=(
            "Use a tool when it can answer the request. "
            "For an echo request, always call test.echo. "
            "For a time request, always call test.get_time. "
            "After a tool result, answer concisely in Japanese."
        ),
        tools=[echo, get_time],
    )
    if stream:
        response_stream = agent.run(prompt, stream=True)
        async for _ in response_stream:
            pass
        result = await response_stream.get_final_response()
    else:
        result = await agent.run(prompt)
    if result.user_input_requests:
        raise RuntimeError("Unexpected approval request in compatibility probe.")
    if not executed_tools:
        raise RuntimeError("The model returned text without invoking a requested tool.")
    return result.text


async def approval_probe(*, base_url: str, model: str) -> str:
    agent = Agent(
        client=OpenAIChatCompletionClient(base_url=base_url, api_key="local-not-used", model=model),
        name="RinoApprovalProbe",
        instructions="Always call test.approved_echo for the user's request.",
        tools=[approved_echo],
    )
    result = await agent.run("「承認が必要なPoC」を復唱して。必ず test.approved_echo を使って。")
    if not result.user_input_requests:
        raise RuntimeError("Expected a MAF approval request, but none was emitted.")
    request = result.user_input_requests[0]
    if request.function_call is None or request.function_call.name != "test.approved_echo":
        raise RuntimeError("Approval request was not bound to test.approved_echo.")
    return request.function_call.name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5001/v1/")
    parser.add_argument("--model", default="koboldcpp/gemma-4-26B_q4_0-it")
    parser.add_argument("--prompt", default="「梨乃 PoC」と正確に復唱して。必ず test.echo を使って。")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--approval", action="store_true")
    args = parser.parse_args()
    if args.approval:
        print(f"POC_PASS approval_request={asyncio.run(approval_probe(base_url=args.base_url, model=args.model))}")
        return
    print(asyncio.run(run(args.prompt, base_url=args.base_url, model=args.model, stream=args.stream)))
    print(f"POC_PASS tools={','.join(executed_tools)}")


if __name__ == "__main__":
    main()
