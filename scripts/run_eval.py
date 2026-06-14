"""CLI entry point for running RAG evaluations.

Usage:
    # Retrieval-only (fast, no LLM generation or judging)
    python scripts/run_eval.py --mode retrieval

    # End-to-end with LLM judge
    python scripts/run_eval.py --mode e2e

    # End-to-end with Claude API judge (defaults to settings.anthropic_model = claude-opus-4-8)
    python scripts/run_eval.py --mode e2e --judge-provider anthropic
    python scripts/run_eval.py --mode e2e --judge-provider anthropic --judge-model claude-opus-4-8

    # Custom test set and top-k
    python scripts/run_eval.py --test-set services/eval/test_sets/v2.json --top-k 3
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.eval.eval_runner import print_summary, run_eval

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main():
    parser = argparse.ArgumentParser(description="Run RAG evaluation")
    parser.add_argument(
        "--test-set",
        default="services/eval/test_sets/v1.json",
        help="Path to test set JSON file",
    )
    parser.add_argument(
        "--mode",
        choices=["retrieval", "e2e"],
        default="retrieval",
        help="Eval mode: retrieval-only or end-to-end",
    )
    parser.add_argument(
        "--judge-provider",
        choices=["ollama", "anthropic"],
        default="ollama",
        help="LLM provider for judging (e2e mode only)",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Model for LLM judge (defaults to configured ollama model)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of chunks to retrieve",
    )

    args = parser.parse_args()

    results = run_eval(
        test_set_path=args.test_set,
        mode=args.mode,
        judge_provider=args.judge_provider,
        judge_model=args.judge_model,
        top_k=args.top_k,
    )

    print_summary(results)

    # Exit with non-zero if critical metrics fail
    summary = results["summary"]
    if summary.get("hit_rate_at_k", 0) < 0.85:
        print("WARNING: Hit Rate below target (0.85)")
    if summary.get("faithfulness", 1.0) < 0.90:
        print("WARNING: Faithfulness below target (0.90)")


if __name__ == "__main__":
    main()
