"""Eval runner: orchestrates retrieval-only, generation-only, and end-to-end evals.

Three modes:
  - retrieval: test retrieval quality (no LLM generation, fast)
  - generation: test generation with fixed contexts (isolates LLM quality)
  - e2e: full pipeline (retrieval + generation + LLM judge)

Results are stored as JSON in services/eval/results/ for comparison.
"""

import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from qdrant_client import QdrantClient

from shared.config import settings
from shared.db import get_pg_conn, get_qdrant
from shared.models import EvalCase, EvalResult, QueryRequest, RetrievalResult
from services.eval.judges import LLMJudge
from services.eval.metrics import (
    aggregate_by_category,
    aggregate_results,
    citation_accuracy,
    hit_at_k,
    precision_at_k,
    reciprocal_rank,
)
from services.ingestion.embedder import embed_query
from services.query.generator import generate
from services.query.reranker import rerank
from services.query.retriever import keyword_search, reciprocal_rank_fusion, semantic_search

log = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def load_test_set(path: str | Path) -> list[EvalCase]:
    """Load test cases from JSON file."""
    data = json.loads(Path(path).read_text())
    return [EvalCase(**case) for case in data]


def _get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _get_git_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


# --- Retrieval-only eval ---


def eval_retrieval(
    cases: list[EvalCase],
    conn: psycopg.Connection,
    qdrant: QdrantClient,
    top_k: int = 5,
) -> list[EvalResult]:
    """Evaluate retrieval quality without any LLM calls."""
    results = []
    for case in cases:
        t0 = time.time()
        query_embedding = embed_query(case.question)

        semantic_results = semantic_search(query_embedding, qdrant, case.filters)
        keyword_results = keyword_search(case.question, conn, case.filters)
        merged = reciprocal_rank_fusion(semantic_results, keyword_results)
        top_chunks = rerank(case.question, merged, top_k)

        retrieved_sources = [c.source_path for c in top_chunks]
        elapsed = (time.time() - t0) * 1000

        results.append(EvalResult(
            case_id=case.id,
            hit=hit_at_k(retrieved_sources, case.expected_sources),
            reciprocal_rank=reciprocal_rank(retrieved_sources, case.expected_sources),
            precision_at_k=precision_at_k(retrieved_sources, case.expected_sources),
            retrieved_sources=retrieved_sources,
            latency_ms=elapsed,
        ))

        log.info(
            f"[{case.id}] hit={results[-1].hit} rr={results[-1].reciprocal_rank:.2f} "
            f"({elapsed:.0f}ms)"
        )

    return results


# --- End-to-end eval ---


def eval_e2e(
    cases: list[EvalCase],
    conn: psycopg.Connection,
    qdrant: QdrantClient,
    judge: LLMJudge | None = None,
    top_k: int = 5,
) -> list[EvalResult]:
    """Full end-to-end eval: retrieve + generate + judge."""
    results = []
    for i, case in enumerate(cases):
        log.info(f"[{i+1}/{len(cases)}] Evaluating: {case.question[:60]}...")
        t0 = time.time()

        # Retrieve
        query_embedding = embed_query(case.question)
        semantic_results = semantic_search(query_embedding, qdrant, case.filters)
        keyword_results = keyword_search(case.question, conn, case.filters)
        merged = reciprocal_rank_fusion(semantic_results, keyword_results)
        top_chunks = rerank(case.question, merged, top_k)

        retrieved_sources = [c.source_path for c in top_chunks]

        # Generate
        answer = ""
        if top_chunks:
            try:
                answer = generate(case.question, top_chunks)
            except Exception as e:
                log.warning(f"[{case.id}] Generation failed: {e}")
                answer = f"[GENERATION FAILED: {e}]"

        elapsed = (time.time() - t0) * 1000

        result = EvalResult(
            case_id=case.id,
            hit=hit_at_k(retrieved_sources, case.expected_sources),
            reciprocal_rank=reciprocal_rank(retrieved_sources, case.expected_sources),
            precision_at_k=precision_at_k(retrieved_sources, case.expected_sources),
            retrieved_sources=retrieved_sources,
            answer=answer,
            citation_accuracy=citation_accuracy(answer, top_chunks) if answer else None,
            latency_ms=elapsed,
        )

        # LLM judge (if provided)
        if judge and answer and not answer.startswith("[GENERATION FAILED"):
            context_text = "\n---\n".join(c.content for c in top_chunks)
            result.faithfulness = judge.evaluate_faithfulness(answer, context_text)
            result.relevancy = judge.evaluate_relevancy(case.question, answer)
            if case.expected_answer:
                result.correctness = judge.evaluate_correctness(
                    case.question, case.expected_answer, answer
                )

        results.append(result)
        log.info(
            f"[{case.id}] hit={result.hit} faith={result.faithfulness} "
            f"rel={result.relevancy} ({elapsed:.0f}ms)"
        )

    return results


# --- Run and store results ---


def run_eval(
    test_set_path: str | Path,
    mode: str = "retrieval",
    judge_provider: str = "ollama",
    judge_model: str | None = None,
    top_k: int = 5,
) -> dict:
    """Run an evaluation and store results.

    Args:
        test_set_path: Path to test set JSON file.
        mode: "retrieval" or "e2e".
        judge_provider: "ollama" or "anthropic".
        judge_model: Model for LLM judge (defaults to settings.ollama_model).
        top_k: Number of chunks to retrieve.

    Returns:
        Full eval results dict with summary, per-case, and per-category breakdowns.
    """
    cases = load_test_set(test_set_path)
    # autocommit so one failed query can't poison the connection for the rest
    # of the run (read-mostly eval workload).
    conn = get_pg_conn(autocommit=True)
    qdrant = get_qdrant()

    log.info(f"Running {mode} eval on {len(cases)} cases (top_k={top_k})")

    # Resolve the effective judge model per provider (anthropic defaults to a
    # Claude model, not the Ollama model).
    effective_judge_model = judge_model or (
        settings.anthropic_model if judge_provider == "anthropic" else settings.ollama_model
    )

    if mode == "retrieval":
        results = eval_retrieval(cases, conn, qdrant, top_k)
    elif mode == "e2e":
        judge = LLMJudge(provider=judge_provider, model=effective_judge_model)
        results = eval_e2e(cases, conn, qdrant, judge, top_k)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    conn.close()

    # Build case lookup for per-category aggregation
    case_lookup = {c.id: {"category": c.category, "difficulty": c.difficulty} for c in cases}

    run_id = f"eval-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    output = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": _get_git_commit(),
        "git_branch": _get_git_branch(),
        "test_set": str(test_set_path),
        "mode": mode,
        "config": {
            "top_k": top_k,
            "reranker": settings.reranker_model,
            "llm": settings.ollama_model,
            "prompt_version": "system_v1",
            "judge_provider": judge_provider,
            "judge_model": effective_judge_model,
        },
        "summary": aggregate_results(results),
        "per_category": aggregate_by_category(results, case_lookup),
        "per_case": [r.model_dump() for r in results],
    }

    # Store results
    result_path = RESULTS_DIR / f"{run_id}.json"
    result_path.write_text(json.dumps(output, indent=2, default=str))
    log.info(f"Results saved to {result_path}")

    return output


def print_summary(output: dict) -> None:
    """Print a human-readable summary table."""
    s = output["summary"]
    print(f"\n{'='*60}")
    print(f"  EVAL RUN: {output['run_id']}")
    print(f"  {output['timestamp']}  |  {output['git_commit']}")
    print(f"  Mode: {output['mode']}  |  Cases: {s.get('total_cases', 0)}")
    print(f"{'='*60}")

    targets = {
        "hit_rate_at_k": 0.85,
        "mrr": 0.70,
        "faithfulness": 0.90,
        "relevancy_pass_rate": 0.85,
        "correctness_pass_rate": 0.75,
        "citation_accuracy": 0.90,
    }

    print(f"  {'Metric':<25} {'Value':>10} {'Target':>10} {'Status':>8}")
    print(f"  {'-'*53}")

    for metric, value in s.items():
        if metric == "total_cases":
            continue
        target = targets.get(metric)
        if isinstance(value, float):
            val_str = f"{value:.3f}"
        else:
            val_str = str(value)
        target_str = f"{target:.3f}" if target else ""
        if target:
            status = "PASS" if value >= target else "FAIL"
        else:
            status = ""
        print(f"  {metric:<25} {val_str:>10} {target_str:>10} {status:>8}")

    # Per-category
    if output.get("per_category"):
        print(f"\n  Per-Category Hit Rate:")
        for cat, metrics in output["per_category"].items():
            hr = metrics.get("hit_rate_at_k", 0)
            n = metrics.get("total_cases", 0)
            print(f"    {cat:<20} {hr:.3f}  (n={n})")

    print()
