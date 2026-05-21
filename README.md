# eval-mcp

CLI tool that evaluates whether OpenAPI Specification (OAS) endpoint descriptions enable a Large Language Model to correctly pick the right tool for a given user prompt.

## What it does

1. Loads one or more OAS JSON files and extracts operations as candidate tools
2. Loads an eval file (JSON) containing prompts and expected `operationId` selections
3. For each test case, calls a model with tool-use enabled and forces a tool pick. Two backends supported:
   - **Anthropic** (default): `client.messages.create` with `tool_choice={"type":"any"}`; tools block is prompt-cached and cases run concurrently with a semaphore. Optional `--batch` submits via the Anthropic batch API (50% cheaper, runs within 24h).
   - **Ollama / OpenAI-compatible**: any local server exposing `/v1/chat/completions` (Ollama, LM Studio, vLLM, llama.cpp). Tools are sent in OpenAI's function-calling format with `tool_choice="required"`.
4. Generates a self-contained HTML report showing per-case pass/fail and an overall score

## Install

```bash
pip install -e .
```

This exposes the `eval-mcp` console script.

For development:

```bash
pip install -e ".[dev]"
```

If the `eval-mcp` command is not on your `PATH` (or you prefer not to use the console script), you can run the CLI as a module instead:

```bash
python3 -m eval_mcp.cli --oas ... --eval ... --output ...
```

Every flag shown below works identically with either form — replace `eval-mcp` with `python3 -m eval_mcp.cli`.

## Configure

### Anthropic backend (default)

Create a `.env` file in your working directory (or any parent) with your Anthropic API key:

```bash
cp .env.example .env
# Then edit .env and set your real key
```

`.env` contents:

```
ANTHROPIC_API_KEY=sk-ant-...
```

The CLI loads `.env` automatically via `python-dotenv`. If `ANTHROPIC_API_KEY` is already set in the shell environment, that value takes precedence and the `.env` file is ignored for that key.

### Ollama / local-model backend

No API key required — point the CLI at any OpenAI-compatible server.

```bash
# 1. Install and start Ollama
ollama serve &

# 2. Pull a tool-capable model
ollama pull llama3.1:8b
```

Tool-calling capable local models include `llama3.1`, `llama3.2`, `qwen2.5`, `mistral-nemo`, `firefunction-v2`. Models without tool-calling support will return no tool call and every case will fail.

## Usage

### Anthropic (default)

```bash
# Single OAS file
eval-mcp \
  --oas path/to/CustomView.json \
  --eval evals/CustomView.json \
  --output eval-report.html

# Multiple OAS files (pools all operations as candidate tools)
eval-mcp \
  --oas-list path/to/CustomView.json path/to/Account.json \
  --eval evals/mixed.json

# All *.json files in a directory
eval-mcp \
  --oas-dir path/to/openapi-specifications/support/ \
  --eval evals/all.json

# Pick a different Claude model
eval-mcp \
  --oas path/to/CustomView.json \
  --eval evals/CustomView.json \
  --model claude-opus-4-7

# Tune concurrency (default 8)
eval-mcp \
  --oas path/to/CustomView.json \
  --eval evals/CustomView.json \
  --concurrency 16

# Submit via the Anthropic batch API (50% cheaper, runs within 24h)
eval-mcp \
  --oas path/to/CustomView.json \
  --eval evals/CustomView.json \
  --batch
```

### Ollama / local model

```bash
# Local Ollama with default endpoint http://localhost:11434/v1
eval-mcp \
  --provider ollama \
  --model llama3.1:8b \
  --oas path/to/CustomView.json \
  --eval evals/CustomView.json

# Remote / non-default endpoint (Ollama on another host, LM Studio, vLLM, llama.cpp)
eval-mcp \
  --provider ollama \
  --base-url http://other-host:11434/v1 \
  --model qwen2.5:14b \
  --oas path/to/CustomView.json \
  --eval evals/CustomView.json
```

`--batch` is only supported with `--provider anthropic` (local servers have no batch endpoint).

## Eval file format

```json
{
  "cases": [
    { "prompt": "Star a view for quick access", "expected": "addStarredView" },
    { "prompt": "Record the view I just opened", "expected": "updateRecentView" }
  ]
}
```

Each case is a natural-language user prompt and the `operationId` you expect Claude to pick.

## Flags

| Flag | Description | Default |
|---|---|---|
| `--oas <file>` | Single OAS JSON file | — |
| `--oas-list <f1> <f2> ...` | Multiple OAS JSON files | — |
| `--oas-dir <dir>` | All `*.json` files in directory | — |
| `--eval <file>` | Eval JSON file | required |
| `--output <path>` | HTML report output path | `eval-report.html` |
| `--model <id>` | Model ID (Claude alias, or Ollama model name like `llama3.1:8b`) | `claude-sonnet-4-6` |
| `--provider {anthropic,ollama}` | Which backend to call | `anthropic` |
| `--base-url <url>` | Override base URL (for remote Ollama / LM Studio / vLLM / llama.cpp) | `http://localhost:11434/v1` when `--provider ollama` |
| `--concurrency <n>` | Max concurrent API calls in default mode | `8` |
| `--batch` | Submit via Anthropic batch API (50% cheaper, runs within 24h). Anthropic only. | off |

`--oas`, `--oas-list`, and `--oas-dir` are mutually exclusive; exactly one is required. `--batch` and `--provider ollama` are incompatible.

## Behaviour notes

- Operations with `x-internal: true` are skipped
- `$ref` parameters are resolved: both inline (`#/components/parameters/X`) and cross-file (`../common/Common.json#/components/parameters/X`)
- Top-level `parameters` arrays on path items (OAS 3.0 shared params) are skipped — they apply to all methods at that path but are not themselves operations

## Run tests

```bash
pytest
```

## Project layout

```
eval-mcp/
├── pyproject.toml
├── README.md
├── eval_mcp/
│   ├── __init__.py
│   ├── oas_loader.py     # OAS JSON → list[Operation], resolves $ref
│   ├── eval_loader.py    # eval JSON → list[TestCase]
│   ├── evaluator.py      # Operation → Claude tool def, runs API calls
│   ├── report.py         # list[EvalResult] → self-contained HTML
│   └── cli.py            # argparse entry point (eval-mcp console script)
├── tests/                # pytest tests (no live API calls; both providers mocked)
└── evals/
    └── CustomView.json   # example eval file
```
