import asyncio
import json
import time
from dataclasses import dataclass, field

import anthropic
import openai
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from .oas_loader import Operation

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"


@dataclass
class EvalResult:
    prompt: str
    expected: str
    actual: str
    passed: bool
    expected_description: str = ""
    actual_description: str = ""
    extracted_params: dict = field(default_factory=dict)


def build_tool(op: Operation) -> dict:
    """Convert an Operation into a Claude tool definition."""
    if op.summary and op.description:
        description = f"{op.summary}\n\n{op.description}"
    else:
        description = op.summary or op.description

    properties = {}
    required = []
    for param in op.parameters:
        name = param.get("name", "")
        if not name:
            continue

        schema = param.get("schema", {})
        raw_type = schema.get("type", "string")
        param_type = raw_type if isinstance(raw_type, str) else "string"

        prop = {"type": param_type}
        if param.get("description"):
            prop["description"] = param["description"]

        properties[name] = prop
        if param.get("required"):
            required.append(name)

    input_schema = {"type": "object", "properties": properties}
    if required:
        input_schema["required"] = required

    return {
        "name": op.operation_id,
        "description": description,
        "input_schema": input_schema,
    }


def _build_tools_with_cache(operations: list) -> list:
    """Build the tools list and mark it cacheable.

    Tools render at the front of the prompt prefix and are identical across
    every test case, so caching the block trades a one-time write premium for
    ~90% cheaper input on every subsequent call.
    """
    tools = [build_tool(op) for op in operations]
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools


def _build_openai_tool(op: Operation) -> dict:
    """Convert an Operation into an OpenAI-format tool (function calling)."""
    base = build_tool(op)
    return {
        "type": "function",
        "function": {
            "name": base["name"],
            "description": base["description"],
            "parameters": base["input_schema"],
        },
    }


def _picked_tool(content) -> tuple:
    """Return (name, input_dict) of the first tool_use block, or ('', {})."""
    for block in content:
        if block.type == "tool_use":
            return block.name, block.input or {}
    return "", {}


def _to_result(case, actual: str, extracted: dict, op_by_id: dict) -> EvalResult:
    expected_op = op_by_id.get(case.expected_operation_id)
    actual_op = op_by_id.get(actual)
    passed = actual == case.expected_operation_id
    return EvalResult(
        prompt=case.prompt,
        expected=case.expected_operation_id,
        actual=actual,
        passed=passed,
        expected_description=expected_op.description if expected_op else "",
        actual_description=actual_op.description if actual_op else "",
        extracted_params=extracted if passed else {},
    )


async def _evaluate_anthropic_async(operations: list, test_cases: list, model: str, concurrency: int) -> list:
    if not test_cases:
        return []

    client = anthropic.AsyncAnthropic()
    tools = _build_tools_with_cache(operations)
    op_by_id = {op.operation_id: op for op in operations}
    sem = asyncio.Semaphore(concurrency)

    async def run_one(case):
        async with sem:
            response = await client.messages.create(
                model=model,
                max_tokens=256,
                tools=tools,
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": case.prompt}],
            )
            name, params = _picked_tool(response.content)
            return _to_result(case, name, params, op_by_id)

    # Warm the cache with one call before fanning out. Parallel requests can't
    # share an in-flight cache write — without the warm-up, every concurrent
    # call pays the full uncached price.
    first = await run_one(test_cases[0])
    rest = await asyncio.gather(*(run_one(c) for c in test_cases[1:]))
    return [first] + rest


async def _evaluate_ollama_async(operations: list, test_cases: list, model: str, concurrency: int, base_url: str) -> list:
    if not test_cases:
        return []

    # Ollama's OpenAI-compatible endpoint ignores the api_key but the SDK requires one.
    client = openai.AsyncOpenAI(base_url=base_url, api_key="ollama")
    tools = [_build_openai_tool(op) for op in operations]
    op_by_id = {op.operation_id: op for op in operations}
    sem = asyncio.Semaphore(concurrency)

    async def run_one(case):
        async with sem:
            response = await client.chat.completions.create(
                model=model,
                max_tokens=256,
                tools=tools,
                tool_choice="required",
                messages=[{"role": "user", "content": case.prompt}],
            )
            msg = response.choices[0].message
            if msg.tool_calls:
                fn = msg.tool_calls[0].function
                actual = fn.name
                try:
                    params = json.loads(fn.arguments) if fn.arguments else {}
                except (TypeError, json.JSONDecodeError):
                    params = {}
            else:
                actual, params = "", {}
            return _to_result(case, actual, params, op_by_id)

    return await asyncio.gather(*(run_one(c) for c in test_cases))


def evaluate(
    operations: list,
    test_cases: list,
    model: str,
    concurrency: int = 8,
    provider: str = "anthropic",
    base_url: str = None,
) -> list:
    """Run test cases concurrently and return an EvalResult list."""
    if provider == "anthropic":
        return asyncio.run(_evaluate_anthropic_async(operations, test_cases, model, concurrency))
    if provider == "ollama":
        return asyncio.run(
            _evaluate_ollama_async(operations, test_cases, model, concurrency, base_url or DEFAULT_OLLAMA_BASE_URL)
        )
    raise ValueError(f"Unknown provider: {provider!r} (expected 'anthropic' or 'ollama')")


def evaluate_batch(operations: list, test_cases: list, model: str, poll_interval: int = 10) -> list:
    """Submit cases via the Anthropic batch API (50% cheaper; runs within 24h)."""
    client = anthropic.Anthropic()
    tools = _build_tools_with_cache(operations)
    op_by_id = {op.operation_id: op for op in operations}

    requests = [
        Request(
            custom_id=f"case-{i}",
            params=MessageCreateParamsNonStreaming(
                model=model,
                max_tokens=256,
                tools=tools,
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": case.prompt}],
            ),
        )
        for i, case in enumerate(test_cases)
    ]

    batch = client.messages.batches.create(requests=requests)
    print(f"Batch submitted: {batch.id}")

    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        counts = batch.request_counts
        print(
            f"  status={batch.processing_status} "
            f"processing={counts.processing} "
            f"succeeded={counts.succeeded} errored={counts.errored}"
        )
        time.sleep(poll_interval)

    picked_by_id = {}
    for result in client.messages.batches.results(batch.id):
        if result.result.type == "succeeded":
            picked_by_id[result.custom_id] = _picked_tool(result.result.message.content)
        else:
            picked_by_id[result.custom_id] = ("", {})

    return [
        _to_result(case, *picked_by_id.get(f"case-{i}", ("", {})), op_by_id=op_by_id)
        for i, case in enumerate(test_cases)
    ]
