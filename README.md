# eval-mcp

CLI tool that evaluates whether OpenAPI Specification (OAS) endpoint descriptions enable a Large Language Model to correctly pick the right tool for a given user prompt.

## What it does

1. Loads one or more OAS JSON files and extracts operations as candidate tools
2. Loads an eval file (JSON) containing prompts and expected `operationId` selections
3. For each test case, calls a model with tool-use enabled and forces a tool pick. Two backends supported:
   - **Anthropic** (default): `client.messages.create` with `tool_choice={"type":"any"}`; tools block is prompt-cached and cases run concurrently with a semaphore. Optional `--batch` submits via the Anthropic batch API (50% cheaper, runs within 24h).
   - **Ollama / OpenAI-compatible**: any local server exposing `/v1/chat/completions` (Ollama, LM Studio, vLLM, llama.cpp). Tools are sent in OpenAI's function-calling format with `tool_choice="required"`.
4. Generates a self-contained HTML report showing per-case pass/fail, the parameter values the model extracted from the prompt (when the correct tool was picked), and an overall score

There's also a sibling command, `eval-mcp-stability`, that runs each case N times and reports a stability score per case — useful because a single run is noisy. See [Stability evaluator](#stability-evaluator) below.

## Install

```bash
pip install -e .
```

This exposes two console scripts: `eval-mcp` (single-run evaluation) and `eval-mcp-stability` (N-runs-per-case stability evaluation).

For development:

```bash
pip install -e ".[dev]"
```

If the console scripts are not on your `PATH` (or you prefer not to use them), you can run the CLIs as modules instead:

```bash
python3 -m eval_mcp.cli --oas ... --eval ... --output ...
python3 -m eval_mcp.stability_cli --oas ... --eval ... --runs 5 --output ...
```

Every flag shown below works identically with either form — replace `eval-mcp` with `python3 -m eval_mcp.cli` and `eval-mcp-stability` with `python3 -m eval_mcp.stability_cli`.

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

## Stability evaluator

`eval-mcp-stability` runs each test case N times (default 5) instead of once, and reports a pass rate per case plus an aggregate stability score. This catches LLM nondeterminism that a single-run eval hides — a case that passes 3/5 is very different from one that passes 5/5, but both look identical to `eval-mcp`.

```bash
# Default (5 runs per case)
eval-mcp-stability \
  --oas path/to/CustomView.json \
  --eval evals/CustomView.json \
  --output stability-report.html

# More runs for higher signal
eval-mcp-stability \
  --oas path/to/CustomView.json \
  --eval evals/CustomView.json \
  --runs 10

# Batch mode strongly recommended for N×M requests (cheaper, dodges 529 overload errors)
eval-mcp-stability \
  --oas path/to/CustomView.json \
  --eval evals/CustomView.json \
  --runs 10 \
  --batch

# Local model
eval-mcp-stability \
  --provider ollama \
  --model llama3.1:8b \
  --oas path/to/CustomView.json \
  --eval evals/CustomView.json
```

The report shows a histogram of which tools the model picked across the N runs (the expected tool is highlighted green; transient API errors show as `ERROR`), and classifies each case as **STABLE-PASS** (N/N), **STABLE-FAIL** (0/N), or **FLAKY** (anything in between). Transient per-run failures are caught and recorded as `ERROR` in the histogram rather than aborting the whole run.

Flags are the same as `eval-mcp` plus:

| Flag | Description | Default |
|---|---|---|
| `--runs <n>` | Runs per case | `5` |
| `--output <path>` | HTML report output path | `stability-report.html` |

## Eval file format

```json
{
  "cases": [
    { "prompt": "Star a view for quick access", "expected": "addStarredView" },
    { "prompt": "Record the view I just opened", "expected": "updateRecentView" }
  ]
}
```

Each case is a natural-language user prompt and the `operationId` you expect Claude to pick. The same file format is used by both `eval-mcp` and `eval-mcp-stability`.

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
│   ├── oas_loader.py         # OAS JSON → list[Operation], resolves $ref
│   ├── eval_loader.py        # eval JSON → list[TestCase]
│   ├── evaluator.py          # Operation → tool def; runs single-pass API calls
│   ├── report.py             # list[EvalResult] → self-contained HTML
│   ├── cli.py                # argparse entry point (eval-mcp console script)
│   ├── stability.py          # N-runs-per-case runner; reuses helpers from evaluator.py
│   ├── stability_report.py   # list[StabilityResult] → self-contained HTML
│   └── stability_cli.py      # argparse entry point (eval-mcp-stability console script)
├── tests/                    # pytest tests (no live API calls; both providers mocked)
└── evals/
    └── CustomView.json       # example eval file
```
