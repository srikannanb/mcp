import argparse
from pathlib import Path

from dotenv import load_dotenv

from .oas_loader import load_operations
from .eval_loader import load_test_cases
from .stability import DEFAULT_RUNS, evaluate_stability, evaluate_stability_batch
from .stability_report import render_html


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="MCP Readiness Stability Evaluator (runs each case N times)"
    )

    oas_group = parser.add_mutually_exclusive_group(required=True)
    oas_group.add_argument("--oas", metavar="FILE", help="Single OAS JSON file")
    oas_group.add_argument("--oas-list", metavar="FILE", nargs="+", help="Multiple OAS JSON files")
    oas_group.add_argument("--oas-dir", metavar="DIR", help="Directory of OAS JSON files")

    parser.add_argument("--eval", required=True, metavar="FILE", help="Eval JSON file")
    parser.add_argument("--output", default="stability-report.html", metavar="PATH", help="HTML report output path")
    parser.add_argument("--model", default="claude-sonnet-4-6", metavar="ID", help="Model ID (e.g. claude-sonnet-4-6 or llama3.1:8b)")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, metavar="N", help=f"Runs per case (default {DEFAULT_RUNS})")
    parser.add_argument("--concurrency", type=int, default=8, metavar="N", help="Max concurrent API calls")
    parser.add_argument("--batch", action="store_true", help="Submit via Anthropic batch API (50%% cheaper; Anthropic only)")
    parser.add_argument("--provider", choices=["anthropic", "ollama"], default="anthropic", help="Which backend to call")
    parser.add_argument("--base-url", metavar="URL", help="Override base URL (for remote Ollama / vLLM / LM Studio)")

    args = parser.parse_args()

    if args.batch and args.provider != "anthropic":
        parser.error("--batch is only supported with --provider anthropic")
    if args.runs < 1:
        parser.error("--runs must be >= 1")

    if args.oas:
        oas_paths = [Path(args.oas)]
    elif args.oas_list:
        oas_paths = [Path(f) for f in args.oas_list]
    else:
        oas_paths = sorted(Path(args.oas_dir).glob("*.json"))

    operations = load_operations(oas_paths)
    test_cases = load_test_cases(Path(args.eval))

    print(
        f"Loaded {len(operations)} operations, {len(test_cases)} test cases, "
        f"{args.runs} runs per case "
        f"({len(test_cases) * args.runs} total calls)"
    )

    if args.batch:
        results = evaluate_stability_batch(operations, test_cases, args.model, args.runs)
    else:
        results = evaluate_stability(
            operations,
            test_cases,
            args.model,
            runs=args.runs,
            concurrency=args.concurrency,
            provider=args.provider,
            base_url=args.base_url,
        )

    total = len(results)
    stable_pass = sum(1 for r in results if r.pass_rate == 1.0)
    stable_fail = sum(1 for r in results if r.pass_rate == 0.0)
    flaky = total - stable_pass - stable_fail
    mean_pct = (sum(r.pass_rate for r in results) / total * 100) if total else 0
    print(
        f"Results: {stable_pass}/{total} stable-pass, {flaky} flaky, "
        f"{stable_fail} stable-fail — {mean_pct:.0f}% mean pass rate"
    )

    render_html(results, args.output)
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
