"""Retrieval and generation metrics for RAG evaluation.

All metrics are computed from EvalResult objects. No LLM calls here —
LLM-based judgments happen in judges.py before metrics are computed.
"""

import re
from statistics import mean

from shared.models import EvalResult, RetrievalResult


# --- Retrieval metrics ---


def hit_at_k(retrieved_sources: list[str], expected_sources: list[str]) -> bool:
    """Did at least one expected source appear in retrieved results?"""
    return any(src in expected_sources for src in retrieved_sources)


def reciprocal_rank(retrieved_sources: list[str], expected_sources: list[str]) -> float:
    """1/rank of first relevant result. 0 if none found."""
    for rank, src in enumerate(retrieved_sources, 1):
        if src in expected_sources:
            return 1.0 / rank
    return 0.0


def precision_at_k(retrieved_sources: list[str], expected_sources: list[str]) -> float:
    """Fraction of retrieved results that are relevant."""
    if not retrieved_sources:
        return 0.0
    relevant = sum(1 for src in retrieved_sources if src in expected_sources)
    return relevant / len(retrieved_sources)


# --- Citation metrics (mechanical, no LLM) ---


def extract_citations(answer: str) -> list[dict]:
    """Parse [Source: filename#section] citations from an answer."""
    pattern = r"\[Source:\s*([^#\]]+?)(?:#([^\]]*))?\]"
    citations = []
    for match in re.finditer(pattern, answer):
        citations.append({
            "source_path": match.group(1).strip(),
            "section": match.group(2).strip() if match.group(2) else None,
        })
    return citations


def citation_accuracy(
    answer: str, retrieved_chunks: list[RetrievalResult]
) -> float:
    """Check what fraction of citations point to a retrieved chunk."""
    citations = extract_citations(answer)
    if not citations:
        return 1.0  # no citations to be wrong about

    retrieved_paths = {c.source_path for c in retrieved_chunks}
    verified = sum(1 for c in citations if c["source_path"] in retrieved_paths)
    return verified / len(citations)


# --- Aggregate metrics ---


def aggregate_results(results: list[EvalResult]) -> dict:
    """Compute summary statistics across all eval results."""
    if not results:
        return {}

    summary = {
        "total_cases": len(results),
        "hit_rate_at_k": mean(r.hit for r in results),
        "mrr": mean(r.reciprocal_rank for r in results),
        "precision_at_k": mean(r.precision_at_k for r in results),
    }

    # Generation metrics (only where available)
    faith_scores = [r.faithfulness for r in results if r.faithfulness is not None]
    if faith_scores:
        summary["faithfulness"] = mean(faith_scores)

    rel_scores = [r.relevancy for r in results if r.relevancy is not None]
    if rel_scores:
        summary["relevancy_avg"] = mean(rel_scores)
        summary["relevancy_pass_rate"] = mean(1.0 if s == 3 else 0.0 for s in rel_scores)

    corr_scores = [r.correctness for r in results if r.correctness is not None]
    if corr_scores:
        summary["correctness_avg"] = mean(corr_scores)
        summary["correctness_pass_rate"] = mean(1.0 if s == 3 else 0.0 for s in corr_scores)

    cite_scores = [r.citation_accuracy for r in results if r.citation_accuracy is not None]
    if cite_scores:
        summary["citation_accuracy"] = mean(cite_scores)

    latencies = [r.latency_ms for r in results if r.latency_ms > 0]
    if latencies:
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        summary["latency_p50_ms"] = sorted_lat[int(n * 0.50)]
        summary["latency_p95_ms"] = sorted_lat[min(int(n * 0.95), n - 1)]
        summary["latency_mean_ms"] = mean(sorted_lat)

    return summary


def aggregate_by_category(results: list[EvalResult], cases: dict[str, dict]) -> dict:
    """Group results by category and compute per-category metrics."""
    by_cat: dict[str, list[EvalResult]] = {}
    for r in results:
        cat = cases.get(r.case_id, {}).get("category", "unknown")
        by_cat.setdefault(cat, []).append(r)

    return {cat: aggregate_results(cat_results) for cat, cat_results in by_cat.items()}


def check_regression(
    current: dict, baseline: dict, thresholds: dict | None = None
) -> list[str]:
    """Compare current eval against baseline. Return list of regressions."""
    if thresholds is None:
        thresholds = {
            "hit_rate_at_k": 0.03,
            "faithfulness": 0.05,
            "relevancy_pass_rate": 0.05,
            "latency_p95_ms": -500,  # negative: higher is worse
        }

    regressions = []
    for metric, threshold in thresholds.items():
        if metric not in current or metric not in baseline:
            continue
        cur = current[metric]
        base = baseline[metric]
        if threshold < 0:
            # For latency-type metrics where higher is worse
            if cur > base + abs(threshold):
                regressions.append(
                    f"REGRESSION: {metric} increased from {base:.1f} to {cur:.1f} "
                    f"(threshold: {abs(threshold):.1f})"
                )
        else:
            if cur < base - threshold:
                regressions.append(
                    f"REGRESSION: {metric} dropped from {base:.3f} to {cur:.3f} "
                    f"(threshold: {threshold})"
                )
    return regressions
