"""Build eval_mcp_walkthrough.ipynb — a step-by-step notebook with all logic inlined."""
import json
from pathlib import Path


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text.splitlines(keepends=True),
    }


cells = [
    md("""# eval-mcp — Step-by-Step Walkthrough

This notebook walks through the entire pipeline one cell at a time. Every function is defined inline so you can read it, run it, and modify it.

**Pipeline:**
1. Load the OpenAPI spec → list of `Operation` objects
2. Load the eval file → list of `TestCase` objects
3. Convert each `Operation` to a Claude tool definition
4. Call Claude once per test case with all tools attached
5. Compare picked tool to expected → `EvalResult`
6. Render an HTML report

**How to run:** click any cell, press **Shift+Enter** to execute. Output appears below the cell.
"""),
    md("## 0. Setup"),
    code("""import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from pprint import pprint

from dotenv import load_dotenv

# Loads ANTHROPIC_API_KEY from .env into os.environ
load_dotenv()
print("ANTHROPIC_API_KEY set:", "ANTHROPIC_API_KEY" in os.environ)
"""),
    code("""# Edit these to point at your files.
OAS_PATH = Path("/Users/sri-19761/eclipse-workspace/zohodesk/resources/openapi-specifications/v1.0/support/CustomView.json")
EVAL_PATH = Path("evals/CustomView.json")
MODEL = "claude-sonnet-4-6"

assert OAS_PATH.exists(), f"OAS file not found: {OAS_PATH}"
assert EVAL_PATH.exists(), f"Eval file not found: {EVAL_PATH}"
print("OAS file:  ", OAS_PATH)
print("Eval file: ", EVAL_PATH)
print("Model:     ", MODEL)
"""),
    md("""## 1. Inspect the raw OpenAPI spec

Before writing any loader, let's see what the JSON file actually looks like.
"""),
    code("""with open(OAS_PATH) as f:
    raw_spec = json.load(f)

print("Top-level keys:", list(raw_spec.keys()))
print("Number of paths:", len(raw_spec.get("paths", {})))
print()

# Show one path entry to understand the shape
first_path = next(iter(raw_spec["paths"]))
print(f"Sample path: {first_path}")
pprint(raw_spec["paths"][first_path])
"""),
    md("""## 2. Define the `Operation` dataclass

A Python `@dataclass` is like a Java `record`: auto-generates `__init__`, `__repr__`, `__eq__`. Each Operation captures one endpoint.
"""),
    code("""@dataclass
class Operation:
    operation_id: str
    summary: str
    description: str
    method: str
    path: str
    parameters: list = field(default_factory=list)

# Quick sanity check
sample = Operation(
    operation_id="getViews",
    summary="Get views",
    description="Returns all custom views.",
    method="GET",
    path="/customViews",
)
print(sample)
"""),
    md("""## 3. Resolve `$ref` parameters

OpenAPI specs often use `$ref` to point at parameter definitions stored elsewhere. This helper resolves both inline (`#/components/...`) and cross-file (`../common/X.json#/...`) references.
"""),
    code("""def resolve_parameters(raw_params: list, inline_params: dict, oas_path: Path, cache: dict) -> list:
    resolved = []
    for param in raw_params:
        ref = param.get("$ref", "")
        if not ref:
            resolved.append(param)
            continue

        if ref.startswith("#/"):
            # Inline reference: look up in the same file's components/parameters
            key = ref.split("/")[-1]
            resolved_param = inline_params.get(key)
            if resolved_param:
                resolved.append(resolved_param)
        else:
            # Cross-file reference: open another file and walk the JSON pointer
            file_part, fragment = ref.split("#", 1)
            ref_path = (oas_path.parent / file_part).resolve()
            ref_key = str(ref_path)

            if ref_key not in cache:
                try:
                    with open(ref_path) as f:
                        cache[ref_key] = json.load(f)
                except (OSError, json.JSONDecodeError):
                    continue

            node = cache[ref_key]
            for part in fragment.strip("/").split("/"):
                node = node.get(part, {})
            if node:
                resolved.append(node)
    return resolved

# Pure function — no output yet, just defined.
print("resolve_parameters defined")
"""),
    md("""## 4. Load operations from the OAS file

Loop over `paths × methods`, skip internal operations, build an `Operation` per endpoint.
"""),
    code("""def load_operations_from_file(oas_path: Path) -> list:
    with open(oas_path) as f:
        spec = json.load(f)

    inline_params = spec.get("components", {}).get("parameters", {})
    cache = {}

    operations = []
    for path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            # Skip the top-level "parameters" key on path items (OAS 3.0 shared params)
            if not isinstance(op, dict):
                continue
            # Skip operations marked x-internal
            if op.get("x-internal") is True:
                continue

            operation_id = op.get("operationId", "")
            if not operation_id:
                continue

            params = resolve_parameters(
                op.get("parameters", []), inline_params, oas_path, cache
            )
            operations.append(
                Operation(
                    operation_id=operation_id,
                    summary=op.get("summary", ""),
                    description=op.get("description", ""),
                    method=method.upper(),
                    path=path,
                    parameters=params,
                )
            )
    return operations

# Run it
operations = load_operations_from_file(OAS_PATH)
print(f"Loaded {len(operations)} operations\\n")
for op in operations[:5]:
    print(f"  {op.method:6} {op.path:50} -> {op.operation_id}")
"""),
    md("## 5. Inspect one Operation in detail"),
    code("""op = operations[0]
print(f"operation_id: {op.operation_id}")
print(f"method:       {op.method}")
print(f"path:         {op.path}")
print(f"summary:      {op.summary}")
print(f"description:  {op.description[:200]}")
print(f"parameters:   {len(op.parameters)}")
if op.parameters:
    print()
    print("First parameter:")
    pprint(op.parameters[0])
"""),
    md("""## 6. Load the eval cases

Each case is a `(prompt, expected_operation_id)` pair — the human prompt and the operation we expect Claude to pick.
"""),
    code("""@dataclass
class TestCase:
    prompt: str
    expected_operation_id: str


def load_test_cases(eval_path: Path) -> list:
    with open(eval_path) as f:
        data = json.load(f)
    return [
        TestCase(prompt=case["prompt"], expected_operation_id=case["expected"])
        for case in data.get("cases", [])
    ]

test_cases = load_test_cases(EVAL_PATH)
print(f"Loaded {len(test_cases)} test cases\\n")
for i, case in enumerate(test_cases):
    print(f"  [{i}] {case.prompt!r}  -> expected: {case.expected_operation_id}")
"""),
    md("""## 7. Convert an Operation to a Claude tool definition

This is the JSON shape Claude's API expects in the `tools` array. The `description` field is what Claude reads to decide if this tool matches the prompt.
"""),
    code("""def build_tool(op: Operation) -> dict:
    if op.summary and op.description:
        description = f"{op.summary}\\n\\n{op.description}"
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

# Build one tool and show its JSON
tool = build_tool(operations[0])
print(json.dumps(tool, indent=2))
"""),
    md("""## 8. Build all tools (with prompt caching)

We mark the last tool with `cache_control` so Claude caches the entire tools block. After the first call writes the cache, subsequent calls read at ~10% of the input-token cost.
"""),
    code("""tools = [build_tool(op) for op in operations]
tools[-1]["cache_control"] = {"type": "ephemeral"}

print(f"Built {len(tools)} tools")
print(f"First tool name: {tools[0]['name']}")
print(f"Last tool name:  {tools[-1]['name']}")
print(f"Last tool has cache_control: {'cache_control' in tools[-1]}")
"""),
    md("""## 9. One API call to Claude

Send one prompt + all tools, force Claude to pick exactly one tool (`tool_choice={"type": "any"}`).
"""),
    code("""import anthropic

client = anthropic.Anthropic()
case = test_cases[0]

print(f"Prompt:        {case.prompt!r}")
print(f"Expected tool: {case.expected_operation_id}\\n")

response = client.messages.create(
    model=MODEL,
    max_tokens=256,
    tools=tools,
    tool_choice={"type": "any"},
    messages=[{"role": "user", "content": case.prompt}],
)
print("Got response. stop_reason:", response.stop_reason)
"""),
    md("## 10. Inspect the response in detail"),
    code("""print(f"Model:       {response.model}")
print(f"Stop reason: {response.stop_reason}")
print(f"Usage:")
print(f"  input_tokens:                  {response.usage.input_tokens}")
print(f"  output_tokens:                 {response.usage.output_tokens}")
print(f"  cache_creation_input_tokens:   {response.usage.cache_creation_input_tokens}")
print(f"  cache_read_input_tokens:       {response.usage.cache_read_input_tokens}")
print()
print(f"Content blocks ({len(response.content)}):")
for i, block in enumerate(response.content):
    print(f"  [{i}] type={block.type}")
    if block.type == "tool_use":
        print(f"      name:  {block.name}")
        print(f"      input: {block.input}")
    elif block.type == "text":
        print(f"      text:  {block.text[:120]!r}")
"""),
    md("## 11. Extract the picked tool and score this case"),
    code("""picked = ""
for block in response.content:
    if block.type == "tool_use":
        picked = block.name
        break

print(f"Picked:   {picked}")
print(f"Expected: {case.expected_operation_id}")
print(f"Match:    {picked == case.expected_operation_id}")
"""),
    md("""## 12. Define `EvalResult` and run all cases

A simple synchronous loop — easier to step through than the async version in `evaluator.py`. The second call onwards will read the cached tools block (watch `cache_read_input_tokens`).
"""),
    code("""@dataclass
class EvalResult:
    prompt: str
    expected: str
    actual: str
    passed: bool
    expected_description: str = ""
    actual_description: str = ""


op_by_id = {op.operation_id: op for op in operations}
results = []

for case in test_cases:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=256,
        tools=tools,
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": case.prompt}],
    )
    actual = ""
    for block in resp.content:
        if block.type == "tool_use":
            actual = block.name
            break

    expected_op = op_by_id.get(case.expected_operation_id)
    actual_op = op_by_id.get(actual)
    result = EvalResult(
        prompt=case.prompt,
        expected=case.expected_operation_id,
        actual=actual,
        passed=(actual == case.expected_operation_id),
        expected_description=expected_op.description if expected_op else "",
        actual_description=actual_op.description if actual_op else "",
    )
    results.append(result)

    status = "PASS" if result.passed else "FAIL"
    cache_read = resp.usage.cache_read_input_tokens
    print(f"  [{status}] cache_read={cache_read:5}  {case.prompt!r}  -> {actual}")

passed = sum(1 for r in results if r.passed)
print(f"\\nResults: {passed}/{len(results)} passed")
"""),
    md("""## 13. Render the HTML report

Build a self-contained HTML page with one row per result.
"""),
    code("""def html_escape(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def render_html(results: list, output_path: str) -> None:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    pct = int(passed / total * 100) if total else 0

    rows = []
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        row_bg = "#d8f3dc" if r.passed else "#ffe0e0"
        badge_color = "#2d6a4f" if r.passed else "#9b2226"
        rows.append(f'''
        <tr style="background:{row_bg}">
            <td>{html_escape(r.prompt)}</td>
            <td>{html_escape(r.expected)}</td>
            <td>{html_escape(r.actual)}</td>
            <td><span style="color:{badge_color};font-weight:bold">{status}</span></td>
        </tr>''')

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Eval Report</title>
<style>
body {{font-family: sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem}}
table {{border-collapse: collapse; width: 100%}}
th, td {{border: 1px solid #ccc; padding: .5rem .75rem; text-align: left}}
th {{background: #f0f0f0}}
.score {{font-size: 1.5rem; font-weight: bold; margin-bottom: 1rem}}
</style></head><body>
<h1>Eval Report</h1>
<p class="score">{passed} / {total} passed &mdash; {pct}%</p>
<table><thead><tr><th>Prompt</th><th>Expected</th><th>Actual</th><th>Result</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
</body></html>'''

    with open(output_path, "w") as f:
        f.write(html)


output_path = "walkthrough-report.html"
render_html(results, output_path)
print(f"Report written: {Path(output_path).resolve()}")
"""),
    md("Display the report inline in the notebook:"),
    code("""from IPython.display import IFrame
IFrame(src=output_path, width="100%", height=600)
"""),
    md("""---

## Appendix: Use a local model via Ollama

Anthropic uses one tool-call format; OpenAI (and Ollama's OpenAI-compatible endpoint) uses a different one. The cell below shows the local-model path. Prereq: `ollama serve` running and `ollama pull llama3.1:8b` done.
"""),
    code("""import openai

# Convert tools to OpenAI function-calling format
openai_tools = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in [build_tool(op) for op in operations]  # rebuild without cache_control
]

ollama_client = openai.OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

case = test_cases[0]
print(f"Prompt: {case.prompt!r}")
print(f"Expected: {case.expected_operation_id}\\n")

resp = ollama_client.chat.completions.create(
    model="llama3.1:8b",
    max_tokens=256,
    tools=openai_tools,
    tool_choice="required",
    messages=[{"role": "user", "content": case.prompt}],
)
msg = resp.choices[0].message
picked = msg.tool_calls[0].function.name if msg.tool_calls else "(no tool call)"
print(f"Local model picked: {picked}")
"""),
]

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "version": "3.14",
        },
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

for i, cell in enumerate(cells):
    cell["id"] = f"cell-{i:02d}"

output = Path(__file__).parent / "eval_mcp_walkthrough.ipynb"
output.write_text(json.dumps(notebook, indent=1))
print(f"Wrote {output}")
