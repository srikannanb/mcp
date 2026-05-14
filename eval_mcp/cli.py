import argparse
from pathlib import Path

from dotenv import load_dotenv

from .oas_loader import load_operations
from .eval_loader import load_test_cases
from .evaluator import evaluate, evaluate_batch
from .report import render_html


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="MCP Readiness Evaluator")

    oas_group = parser.add_mutually_exclusive_group(required=True)
    oas_group.add_argument("--oas", metavar="FILE", help="Single OAS JSON file")
    oas_group.add_argument("--oas-list", metavar="FILE", nargs="+", help="Multiple OAS JSON files")
    oas_group.add_argument("--oas-dir", metavar="DIR", help="Directory of OAS JSON files")

    parser.add_argument("--eval", required=True, metavar="FILE", help="Eval JSON file")
    parser.add_argument("--output", default="eval-report.html", metavar="PATH", help="HTML report output path")
    parser.add_argument("--model", default="claude-sonnet-4-6", metavar="ID", help="Model ID (e.g. claude-sonnet-4-6 or llama3.1:8b)")
    parser.add_argument("--concurrency", type=int, default=8, metavar="N", help="Max concurrent API calls (default mode)")
    parser.add_argument("--batch", action="store_true", help="Submit via Anthropic batch API (50%% cheaper; runs within 24h)")
    parser.add_argument("--provider", choices=["anthropic", "ollama"], default="anthropic", help="Which backend to call")
    parser.add_argument("--base-url", metavar="URL", help="Override base URL (e.g. for a remote Ollama / vLLM / LM Studio server)")

    args = parser.parse_args()

    if args.batch and args.provider != "anthropic":
        parser.error("--batch is only supported with --provider anthropic")

    if args.oas:
        oas_paths = [Path(args.oas)]
    elif args.oas_list:
        oas_paths = [Path(f) for f in args.oas_list]
    else:
        oas_paths = sorted(Path(args.oas_dir).glob("*.json"))

    operations = load_operations(oas_paths)
    test_cases = load_test_cases(Path(args.eval))

    print(f"Loaded {len(operations)} operations, {len(test_cases)} test cases")

    if args.batch:
        results = evaluate_batch(operations, test_cases, args.model)
    else:
        results = evaluate(
            operations,
            test_cases,
            args.model,
            args.concurrency,
            provider=args.provider,
            base_url=args.base_url,
        )

    passed = sum(1 for r in results if r.passed)
    print(f"Results: {passed}/{len(results)} passed")

    render_html(results, args.output)
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
