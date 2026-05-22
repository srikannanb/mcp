import asyncio
import json
import time
from collections import Counter
from dataclasses import dataclass, field

import anthropic
import openai
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from .evaluator import (
    DEFAULT_OLLAMA_BASE_URL,
    _build_openai_tool,
    _build_tools_with_cache,
    _picked_tool,
)

DEFAULT_RUNS = 5


@dataclass
class StabilityResult:
    prompt: str
    expected: str
    expected_description: str = ""
    runs: int = 0
    passes: int = 0
    pass_rate: float = 0.0
    picks: dict = field(default_factory=dict)
    errors: int = 0
    extracted_params: list = field(default_factory=list)


def _aggregate(case, per_run_results: list, op_by_id: dict) -> StabilityResult:
    """Fold a list of (name, params, errored) tuples into one StabilityResult."""
    expected = case.expected_operation_id
    counts = Counter()
    passes = 0
    errors = 0
    passing_params = []
    for name, params, errored in per_run_results:
        if errored:
            counts["ERROR"] += 1
            errors += 1
            continue
        counts[name or "(no tool)"] += 1
        if name == expected:
            passes += 1
            passing_params.append(params)
    runs = len(per_run_results)
    expected_op = op_by_id.get(expected)
    return StabilityResult(
        prompt=case.prompt,
        expected=expected,
        expected_description=expected_op.description if expected_op else "",
        runs=runs,
        passes=passes,
        pass_rate=(passes / runs) if runs else 0.0,
        picks=dict(counts),
        errors=errors,
        extracted_params=passing_params,
    )


async def _evaluate_anthropic_async(operations, test_cases, model, concurrency, runs):
    if not test_cases:
        return []

    client = anthropic.AsyncAnthropic()
    tools = _build_tools_with_cache(operations)
    op_by_id = {op.operation_id: op for op in operations}
    sem = asyncio.Semaphore(concurrency)

    async def run_one(case):
        async with sem:
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=256,
                    tools=tools,
                    tool_choice={"type": "any"},
                    messages=[{"role": "user", "content": case.prompt}],
                )
                name, params = _picked_tool(response.content)
                return (name, params, False)
            except Exception:
                return ("", {}, True)

    case_indices = []
    coros = []
    for i, case in enumerate(test_cases):
        for _ in range(runs):
            case_indices.append(i)
            coros.append(run_one(case))

    # Warm the tools-block cache with one call before fanning out. Without this,
    # every concurrent task pays the full uncached price.
    first = await coros[0]
    rest = await asyncio.gather(*coros[1:])
    all_results = [first] + list(rest)

    per_case = [[] for _ in test_cases]
    for idx, result in zip(case_indices, all_results):
        per_case[idx].append(result)

    return [_aggregate(case, per_case[i], op_by_id) for i, case in enumerate(test_cases)]


async def _evaluate_ollama_async(operations, test_cases, model, concurrency, base_url, runs):
    if not test_cases:
        return []

    client = openai.AsyncOpenAI(base_url=base_url, api_key="ollama")
    tools = [_build_openai_tool(op) for op in operations]
    op_by_id = {op.operation_id: op for op in operations}
    sem = asyncio.Semaphore(concurrency)

    async def run_one(case):
        async with sem:
            try:
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
                    name = fn.name
                    try:
                        params = json.loads(fn.arguments) if fn.arguments else {}
                    except (TypeError, json.JSONDecodeError):
                        params = {}
                else:
                    name, params = "", {}
                return (name, params, False)
            except Exception:
                return ("", {}, True)

    case_indices = []
    coros = []
    for i, case in enumerate(test_cases):
        for _ in range(runs):
            case_indices.append(i)
            coros.append(run_one(case))

    all_results = await asyncio.gather(*coros)

    per_case = [[] for _ in test_cases]
    for idx, result in zip(case_indices, all_results):
        per_case[idx].append(result)

    return [_aggregate(case, per_case[i], op_by_id) for i, case in enumerate(test_cases)]


def evaluate_stability(
    operations: list,
    test_cases: list,
    model: str,
    runs: int = DEFAULT_RUNS,
    concurrency: int = 8,
    provider: str = "anthropic",
    base_url: str = None,
) -> list:
    """Run each case `runs` times concurrently; return one StabilityResult per case."""
    if provider == "anthropic":
        return asyncio.run(_evaluate_anthropic_async(operations, test_cases, model, concurrency, runs))
    if provider == "ollama":
        return asyncio.run(
            _evaluate_ollama_async(
                operations, test_cases, model, concurrency, base_url or DEFAULT_OLLAMA_BASE_URL, runs
            )
        )
    raise ValueError(f"Unknown provider: {provider!r} (expected 'anthropic' or 'ollama')")


def evaluate_stability_batch(
    operations: list,
    test_cases: list,
    model: str,
    runs: int = DEFAULT_RUNS,
    poll_interval: int = 10,
) -> list:
    """Submit N*M requests through the Anthropic batch API; aggregate by case."""
    if not test_cases:
        return []

    client = anthropic.Anthropic()
    tools = _build_tools_with_cache(operations)
    op_by_id = {op.operation_id: op for op in operations}

    requests = [
        Request(
            custom_id=f"case-{i}-run-{j}",
            params=MessageCreateParamsNonStreaming(
                model=model,
                max_tokens=256,
                tools=tools,
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": case.prompt}],
            ),
        )
        for i, case in enumerate(test_cases)
        for j in range(runs)
    ]

    batch = client.messages.batches.create(requests=requests)
    print(f"Batch submitted: {batch.id} ({len(requests)} requests)")

    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        c = batch.request_counts
        print(
            f"  status={batch.processing_status} "
            f"processing={c.processing} succeeded={c.succeeded} errored={c.errored}"
        )
        time.sleep(poll_interval)

    by_id = {}
    for r in client.messages.batches.results(batch.id):
        if r.result.type == "succeeded":
            name, params = _picked_tool(r.result.message.content)
            by_id[r.custom_id] = (name, params, False)
        else:
            by_id[r.custom_id] = ("", {}, True)

    per_case = [[] for _ in test_cases]
    for i in range(len(test_cases)):
        for j in range(runs):
            per_case[i].append(by_id.get(f"case-{i}-run-{j}", ("", {}, True)))

    return [_aggregate(case, per_case[i], op_by_id) for i, case in enumerate(test_cases)]
